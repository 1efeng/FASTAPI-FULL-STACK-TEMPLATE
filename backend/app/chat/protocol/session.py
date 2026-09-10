from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

MAX_EVENTS = 1000


class AgentStreamSession:
    """Process-local SSE transport.

    LangGraph owns agent runtime state, checkpoints, interrupts and recovery.
    This class only manages connected clients and a short-lived replay buffer.
    """

    def __init__(self, thread_id: str):
        self.thread_id = thread_id
        self._events: list[dict[str, Any]] = []
        self._subscribers: dict[int, asyncio.Queue[dict[str, Any]]] = {}
        self._seq = 0
        self._subscriber_id = 0
        self._lock = asyncio.Lock()

    async def publish(self, event: dict[str, Any]) -> None:
        """Store and broadcast native LangGraph protocol events unchanged."""
        async with self._lock:
            self._seq += 1
            payload = {
                "event_id": str(self._seq),
                "seq": self._seq,
                "data": event,
            }
            self._events.append(payload)

            if len(self._events) > MAX_EVENTS:
                self._events = self._events[-MAX_EVENTS:]

            for queue in self._subscribers.values():
                queue.put_nowait(payload)

    async def subscribe(self, last_event_id: int | None = None) -> AsyncIterator[str]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        async with self._lock:
            self._subscriber_id += 1
            subscriber_id = self._subscriber_id
            self._subscribers[subscriber_id] = queue

            replay = [
                item
                for item in self._events
                if last_event_id is None or item["seq"] > last_event_id
            ]

        try:
            for item in replay:
                yield self._sse(item)

            while True:
                yield self._sse(await queue.get())
        finally:
            async with self._lock:
                self._subscribers.pop(subscriber_id, None)

    @staticmethod
    def _sse(payload: dict[str, Any]) -> str:
        return (
            f"id: {payload['event_id']}\n"
            "event: message\n"
            f"data: {json.dumps(payload['data'], ensure_ascii=False)}\n\n"
        )


_sessions: dict[tuple[str, str], AgentStreamSession] = {}


def get_stream_session(owner_id: str, thread_id: str) -> AgentStreamSession:
    key = (owner_id, thread_id)
    if key not in _sessions:
        _sessions[key] = AgentStreamSession(thread_id)
    return _sessions[key]


def clear_stream_sessions() -> None:
    _sessions.clear()
