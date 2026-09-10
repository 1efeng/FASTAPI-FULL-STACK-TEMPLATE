from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app.agent.agent import get_agent
from app.chat.protocol.adapter import (
    AgentEventAdapter,
    input_messages,
    jsonable,
    run_completed,
    run_failed,
    run_interrupted,
    run_started,
    serialize_state,
)
from app.chat.protocol.events import ProtocolEvent


@dataclass(slots=True)
class ActiveRun:
    run_id: str
    task: asyncio.Task[None]
    status: str = "started"


@dataclass(slots=True)
class _Subscriber:
    queue: asyncio.Queue[dict[str, Any]]
    channels: set[str]
    namespaces: list[list[str]]
    depth: int | None


class ThreadSession:
    """Process-local streaming bridge for one checkpointed LangGraph thread.

    LangGraph messages/state live in Postgres checkpoints. Active tasks,
    subscribers, and the SSE replay buffer remain process-local and are not
    safe for multi-worker replay without a shared event transport.
    """

    def __init__(
        self,
        thread_id: str,
        *,
        checkpoint_thread_id: str | None = None,
        agent_factory: Callable[[], Any] = get_agent,
    ) -> None:
        self.thread_id = thread_id
        self.checkpoint_thread_id = checkpoint_thread_id or thread_id
        self._agent_factory = agent_factory
        self._events: list[dict[str, Any]] = []
        self._subscribers: set[int] = set()
        self._subscriber_by_id: dict[int, _Subscriber] = {}
        self._next_subscriber_id = 0
        self._seq = 0
        self._lock = asyncio.Lock()
        self.active_run: ActiveRun | None = None

    async def handle_command(self, command: dict[str, Any]) -> dict[str, Any]:
        command_id = command.get("id")
        if command.get("method") != "run.start":
            return self._error(command_id, "unknown_command", "Unsupported command")

        params = command.get("params")
        if not isinstance(params, dict) or "input" not in params:
            return self._error(command_id, "invalid_argument", "run.start requires params.input")

        if self.active_run is not None and not self.active_run.task.done():
            return self._error(
                command_id,
                "invalid_argument",
                "This thread already has an active run",
            )

        if await self._checkpoint_has_pending_work():
            return self._error(
                command_id,
                "invalid_argument",
                "This thread has unfinished checkpointed work",
            )

        run_id = str(uuid4())
        task = asyncio.create_task(
            self._execute_run(run_id, params),
            name=f"agent-run:{self.thread_id}:{run_id}",
        )
        self.active_run = ActiveRun(run_id=run_id, task=task)
        return {
            "type": "success",
            "id": command_id,
            "result": {"run_id": run_id},
        }

    async def cancel_run(self, run_id: str, *, wait: bool = False) -> bool:
        active = self.active_run
        if active is None or active.run_id != run_id or active.task.done():
            return False

        active.task.cancel()
        if wait:
            with suppress(asyncio.CancelledError):
                await active.task
        return True

    async def state(self) -> dict[str, Any]:
        snapshot = await self._agent_factory().aget_state(self._config())
        state = serialize_state(snapshot, thread_id=self.thread_id)
        active = self.active_run
        active_run_id = (
            active.run_id if active is not None and not active.task.done() else None
        )
        if active_run_id is not None and not state["next"]:
            # The local task can start before LangGraph writes its first
            # checkpoint. Keep the reconnect signal accurate in that window.
            state["next"] = ["agent"]
        metadata = state["metadata"] if isinstance(state["metadata"], dict) else {}
        state["metadata"] = {**metadata, "active_run_id": active_run_id}
        return state

    async def event_stream(self, request: dict[str, Any]) -> AsyncIterator[str]:
        channels_raw = request.get("channels")
        channels = (
            {str(channel) for channel in channels_raw}
            if isinstance(channels_raw, list) and channels_raw
            else {"values", "messages", "tools", "lifecycle"}
        )
        namespaces_raw = request.get("namespaces")
        namespaces = (
            [list(namespace) for namespace in namespaces_raw if isinstance(namespace, list)]
            if isinstance(namespaces_raw, list)
            else []
        )
        depth = request.get("depth") if isinstance(request.get("depth"), int) else None
        since = request.get("since") if isinstance(request.get("since"), int) else None

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        async with self._lock:
            replay = [
                event
                for event in self._events
                if (since is None or int(event["seq"]) > since)
                and _matches(event, channels, namespaces, depth)
            ]
            subscriber_id = self._next_subscriber_id
            self._next_subscriber_id += 1
            self._subscribers.add(subscriber_id)
            self._subscriber_by_id[subscriber_id] = _Subscriber(
                queue=queue,
                channels=channels,
                namespaces=namespaces,
                depth=depth,
            )

        try:
            for event in replay:
                yield _to_sse(event)
            while True:
                event = await queue.get()
                yield _to_sse(event)
        finally:
            async with self._lock:
                self._subscribers.discard(subscriber_id)
                self._subscriber_by_id.pop(subscriber_id, None)

    async def _execute_run(self, run_id: str, params: dict[str, Any]) -> None:
        active = self.active_run
        if active is not None and active.run_id == run_id:
            active.status = "running"

        input_payload = params.get("input")
        new_messages = input_messages(input_payload)
        for event in run_started(run_id):
            await self._publish_event(event)

        adapter = AgentEventAdapter()

        config = self._config(params.get("config"))

        try:
            agent = self._agent_factory()
            async for event in agent.astream_events(
                {"messages": new_messages},
                config=config,
                version="v2",
            ):
                for protocol_event in adapter.adapt(event):
                    await self._publish_event(protocol_event)

            if self.active_run is not None and self.active_run.run_id == run_id:
                self.active_run.status = "completed"
            await self._publish_event(run_completed(run_id))
        except asyncio.CancelledError:
            if self.active_run is not None and self.active_run.run_id == run_id:
                self.active_run.status = "interrupted"
            await self._publish_event(run_interrupted(run_id))
            raise
        except Exception as exc:
            if self.active_run is not None and self.active_run.run_id == run_id:
                self.active_run.status = "failed"
            await self._publish_event(run_failed(run_id, exc))

    def _config(self, raw_config: Any = None) -> dict[str, Any]:
        config = dict(raw_config) if isinstance(raw_config, dict) else {}
        configurable = dict(config.get("configurable") or {})
        configurable["thread_id"] = self.checkpoint_thread_id
        config["configurable"] = configurable
        return config

    async def _checkpoint_has_pending_work(self) -> bool:
        snapshot = await self._agent_factory().aget_state(self._config())
        if snapshot.next:
            return True
        return any(getattr(task, "interrupts", ()) for task in snapshot.tasks)

    async def _publish_event(self, event: ProtocolEvent) -> None:
        await self._publish(event.method, event.data, node=event.node)

    async def _publish(
        self,
        method: str,
        data: Any,
        *,
        node: str | None = None,
    ) -> None:
        async with self._lock:
            self._seq += 1
            params: dict[str, Any] = {
                "namespace": [],
                "timestamp": int(time.time() * 1000),
                "data": jsonable(data),
            }
            if node:
                params["node"] = node
            event = {
                "type": "event",
                "event_id": str(self._seq),
                "seq": self._seq,
                "method": method,
                "params": params,
            }
            self._events.append(event)
            for subscriber_id in list(self._subscribers):
                subscriber = self._subscriber_by_id.get(subscriber_id)
                if subscriber is None:
                    continue
                if _matches(
                    event,
                    subscriber.channels,
                    subscriber.namespaces,
                    subscriber.depth,
                ):
                    subscriber.queue.put_nowait(event)

    @staticmethod
    def _error(command_id: Any, code: str, message: str) -> dict[str, Any]:
        return {
            "type": "error",
            "id": command_id if isinstance(command_id, int) else None,
            "error": code,
            "message": message,
        }

def _matches(
    event: dict[str, Any],
    channels: set[str],
    namespaces: list[list[str]],
    depth: int | None,
) -> bool:
    method = str(event.get("method") or "")
    channel = "input" if method == "input.requested" else method.split(":", 1)[0]
    if channel not in channels and method not in channels:
        return False

    if not namespaces:
        return True
    params = event.get("params")
    namespace = params.get("namespace", []) if isinstance(params, dict) else []
    if not isinstance(namespace, list):
        return False
    for prefix in namespaces:
        if namespace[: len(prefix)] != prefix:
            continue
        if depth is None or len(namespace) - len(prefix) <= depth:
            return True
    return False


def _to_sse(event: dict[str, Any]) -> str:
    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event['event_id']}\nevent: message\ndata: {payload}\n\n"


_sessions: dict[tuple[str, str], ThreadSession] = {}


def get_thread_session(owner_id: str, thread_id: str) -> ThreadSession:
    key = (owner_id, thread_id)
    session = _sessions.get(key)
    if session is None:
        session = ThreadSession(
            thread_id,
            checkpoint_thread_id=f"{owner_id}:{thread_id}",
        )
        _sessions[key] = session
    return session


def clear_thread_sessions() -> None:
    _sessions.clear()
