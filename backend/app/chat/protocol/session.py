from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any


class AgentStreamSession:
    """Transport session only.

    This class owns SSE subscribers, replay buffer and event sequencing.
    LangGraph state, messages and checkpoints are owned by the LangGraph
    checkpointer and must never live here.
    """

    def __init__(self, thread_id: str):
        self.thread_id = thread_id
        self._events: list[dict[str, Any]] = []
        self._subscribers: dict[int, asyncio.Queue[dict[str, Any]]] = {}
        self._seq = 0
        self._subscriber_id = 0
        self._lock = asyncio.Lock()

    async def publish(self, event: dict[str, Any]) -> None:
        async with self._lock:
            self._seq += 1
            payload = {
                "type": "event",
                "event_id": str(self._seq),
                "seq": self._seq,
                "timestamp": int(time.time() * 1000),
                "data": event,
            }
            self._events.append(payload)
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
    def _sse(event: dict[str, Any]) -> str:
        return (
            f"id: {event['event_id']}\n"
            "event: message\n"
            f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        )


_sessions: dict[tuple[str, str], AgentStreamSession] = {}


def get_stream_session(owner_id: str, thread_id: str) -> AgentStreamSession:
    key = (owner_id, thread_id)
    if key not in _sessions:
        _sessions[key] = AgentStreamSession(thread_id)
    return _sessions[key]


def clear_stream_sessions() -> None:
    _sessions.clear()
