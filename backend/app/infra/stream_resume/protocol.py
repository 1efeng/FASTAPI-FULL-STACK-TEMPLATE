from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from enum import StrEnum
from typing import Protocol

type ChunkStream = AsyncIterator[str]
type StreamFactory = Callable[[], ChunkStream]


class StreamState(StrEnum):
    """Transport-level state only; never use as Product RequestRun state."""

    MISSING = "MISSING"
    ACTIVE = "ACTIVE"
    DONE = "DONE"
    FAILED = "FAILED"
    INTERRUPTED = "INTERRUPTED"


class StreamResumeStore(Protocol):
    """Framework-neutral active-stream resumption port.

    This port owns transport resumption only. It does not own Product RequestRun,
    cancellation policy, authentication, business persistence, or execution durability.
    """

    async def start(
        self,
        stream_id: str,
        producer: StreamFactory,
    ) -> ChunkStream | None:
        """Atomically start a new producer, or return None if the ID already exists."""
        ...

    async def resume(
        self,
        stream_id: str,
        *,
        skip_characters: int = 0,
    ) -> ChunkStream | None:
        """Attach to an active stream; return None when missing/already done."""
        ...

    async def start_or_resume(
        self,
        stream_id: str,
        producer: StreamFactory,
        *,
        skip_characters: int = 0,
    ) -> ChunkStream | None:
        """Idempotently become the producer or attach to the existing producer."""
        ...

    async def status(self, stream_id: str) -> StreamState:
        ...

    async def close(self) -> None:
        ...
