from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from fastapi.encoders import jsonable_encoder
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.messages.utils import convert_to_messages

from app.agent.agent import get_agent


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
    """Process-local bridge between Agent Protocol and one LangGraph thread.

    This deliberately solves only browser disconnect/reconnect while this Python
    process stays alive. It is not durable execution and is not safe for
    multi-worker replay without a shared session/event store.
    """

    def __init__(
        self,
        thread_id: str,
        *,
        agent_factory: Callable[[], Any] = get_agent,
    ) -> None:
        self.thread_id = thread_id
        self._agent_factory = agent_factory
        self._events: list[dict[str, Any]] = []
        self._subscribers: set[int] = set()
        self._subscriber_by_id: dict[int, _Subscriber] = {}
        self._next_subscriber_id = 0
        self._seq = 0
        self._lock = asyncio.Lock()
        self._messages: list[BaseMessage] = []
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

        run_id = str(uuid4())
        task = asyncio.create_task(
            self._execute_run(run_id, params),
            name=f"agent-run:{self.thread_id}:{run_id}",
        )
        self.active_run = ActiveRun(run_id=run_id, task=task)
        return {
            "type": "success",
            "id": command_id,
            "result": {"runId": run_id},
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

    def state(self) -> dict[str, Any]:
        active = self.active_run
        return {
            "values": {"messages": [_serialize_message(message) for message in self._messages]},
            "next": [],
            "tasks": [],
            "metadata": {
                "activeRunId": (
                    active.run_id if active is not None and not active.task.done() else None
                )
            },
            "checkpoint": None,
            "parent_checkpoint": None,
        }

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
        new_messages = _input_messages(input_payload)
        run_messages = [*self._messages, *new_messages]
        # Persist the submitted user input immediately so a refresh during an
        # active run can hydrate the same thread without starting another run.
        self._messages = run_messages

        await self._publish_values()
        await self._publish(
            "lifecycle",
            {"event": "started", "graphName": "agent", "runId": run_id},
        )
        await self._publish(
            "lifecycle",
            {"event": "running", "graphName": "agent", "runId": run_id},
        )

        model_streams: dict[str, dict[str, Any]] = {}
        tool_call_ids: dict[str, str] = {}
        final_messages: list[BaseMessage] | None = None

        config = dict(params.get("config") or {})
        configurable = dict(config.get("configurable") or {})
        configurable["thread_id"] = self.thread_id
        config["configurable"] = configurable

        try:
            agent = self._agent_factory()
            async for event in agent.astream_events(
                {"messages": run_messages},
                config=config,
                version="v2",
            ):
                event_name = event.get("event")
                event_run_id = str(event.get("run_id") or uuid4())
                data = event.get("data") if isinstance(event.get("data"), dict) else {}

                if event_name == "on_chat_model_stream":
                    chunk = data.get("chunk")
                    text = _message_text(chunk)
                    if not text:
                        continue
                    stream_state = model_streams.get(event_run_id)
                    if stream_state is None:
                        message_id = str(getattr(chunk, "id", None) or f"ai-{event_run_id}")
                        stream_state = {"id": message_id, "text": ""}
                        model_streams[event_run_id] = stream_state
                        await self._publish(
                            "messages",
                            {"event": "message-start", "role": "ai", "id": message_id},
                            node=_event_node(event),
                        )
                        await self._publish(
                            "messages",
                            {
                                "event": "content-block-start",
                                "index": 0,
                                "content": {"type": "text", "text": ""},
                            },
                            node=_event_node(event),
                        )
                    stream_state["text"] += text
                    await self._publish(
                        "messages",
                        {
                            "event": "content-block-delta",
                            "index": 0,
                            "delta": {"type": "text-delta", "text": text},
                        },
                        node=_event_node(event),
                    )
                    continue

                if event_name == "on_chat_model_end":
                    stream_state = model_streams.pop(event_run_id, None)
                    if stream_state is not None:
                        await self._publish(
                            "messages",
                            {
                                "event": "content-block-finish",
                                "index": 0,
                                "content": {"type": "text", "text": stream_state["text"]},
                            },
                            node=_event_node(event),
                        )
                        await self._publish(
                            "messages",
                            {"event": "message-finish"},
                            node=_event_node(event),
                        )
                    continue

                if event_name == "on_tool_start":
                    metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else {}
                    tool_call_id = str(metadata.get("tool_call_id") or event_run_id)
                    tool_call_ids[event_run_id] = tool_call_id
                    await self._publish(
                        "tools",
                        {
                            "event": "tool-started",
                            "toolCallId": tool_call_id,
                            "toolName": str(event.get("name") or "tool"),
                            "input": _jsonable(data.get("input")),
                        },
                        node=_event_node(event),
                    )
                    continue

                if event_name == "on_tool_end":
                    tool_call_id = tool_call_ids.pop(event_run_id, event_run_id)
                    await self._publish(
                        "tools",
                        {
                            "event": "tool-finished",
                            "toolCallId": tool_call_id,
                            "output": _jsonable(data.get("output")),
                        },
                        node=_event_node(event),
                    )
                    continue

                if event_name == "on_tool_error":
                    tool_call_id = tool_call_ids.pop(event_run_id, event_run_id)
                    await self._publish(
                        "tools",
                        {
                            "event": "tool-error",
                            "toolCallId": tool_call_id,
                            "message": str(data.get("error") or "Tool execution failed"),
                        },
                        node=_event_node(event),
                    )
                    continue

                if event_name == "on_chain_end" and not event.get("parent_ids"):
                    output = data.get("output")
                    if isinstance(output, dict) and isinstance(output.get("messages"), list):
                        final_messages = list(convert_to_messages(output["messages"]))

            if final_messages is not None:
                self._messages = final_messages
            await self._publish_values()
            if self.active_run is not None and self.active_run.run_id == run_id:
                self.active_run.status = "completed"
            await self._publish(
                "lifecycle",
                {"event": "completed", "graphName": "agent", "runId": run_id},
            )
        except asyncio.CancelledError:
            if self.active_run is not None and self.active_run.run_id == run_id:
                self.active_run.status = "interrupted"
            await self._publish(
                "lifecycle",
                {"event": "interrupted", "graphName": "agent", "runId": run_id},
            )
            raise
        except Exception as exc:
            if self.active_run is not None and self.active_run.run_id == run_id:
                self.active_run.status = "failed"
            await self._publish(
                "lifecycle",
                {
                    "event": "failed",
                    "graphName": "agent",
                    "runId": run_id,
                    "error": str(exc),
                },
            )

    async def _publish_values(self) -> None:
        await self._publish(
            "values",
            {"messages": [_serialize_message(message) for message in self._messages]},
            data_is_values=True,
        )

    async def _publish(
        self,
        method: str,
        data: Any,
        *,
        node: str | None = None,
        data_is_values: bool = False,
    ) -> None:
        async with self._lock:
            self._seq += 1
            params: dict[str, Any] = {
                "namespace": [],
                "timestamp": int(time.time() * 1000),
                "data": _jsonable(data),
            }
            if node:
                params["node"] = node
            event = {
                "type": "event",
                "eventId": str(self._seq),
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


def _input_messages(payload: Any) -> list[BaseMessage]:
    if not isinstance(payload, dict):
        raise ValueError("run.start input must be an object")
    raw_messages = payload.get("messages")
    if raw_messages is None:
        return []
    if not isinstance(raw_messages, list):
        raise ValueError("run.start input.messages must be an array")
    return list(convert_to_messages(raw_messages))


def _event_node(event: dict[str, Any]) -> str | None:
    metadata = event.get("metadata")
    if isinstance(metadata, dict):
        node = metadata.get("langgraph_node")
        if isinstance(node, str):
            return node
    name = event.get("name")
    return str(name) if isinstance(name, str) else None


def _message_text(message: Any) -> str:
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for block in content:
            if isinstance(block, str):
                chunks.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        return "".join(chunks)
    return ""


def _serialize_message(message: BaseMessage) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": message.type,
        "content": _jsonable(message.content),
    }
    if message.id:
        result["id"] = message.id
    if message.name:
        result["name"] = message.name
    if isinstance(message, AIMessage) and message.tool_calls:
        result["tool_calls"] = _jsonable(message.tool_calls)
    if isinstance(message, ToolMessage):
        result["tool_call_id"] = message.tool_call_id
        if message.status:
            result["status"] = message.status
    return result


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseMessage):
        return _serialize_message(value)
    try:
        return jsonable_encoder(value)
    except (TypeError, ValueError):
        return str(value)


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
    return f"id: {event['eventId']}\nevent: message\ndata: {payload}\n\n"


_sessions: dict[tuple[str, str], ThreadSession] = {}


def get_thread_session(owner_id: str, thread_id: str) -> ThreadSession:
    key = (owner_id, thread_id)
    session = _sessions.get(key)
    if session is None:
        session = ThreadSession(thread_id)
        _sessions[key] = session
    return session


def clear_thread_sessions() -> None:
    _sessions.clear()
