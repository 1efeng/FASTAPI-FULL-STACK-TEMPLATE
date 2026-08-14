from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

type MessageHandler = Callable[[str], Awaitable[None]]


class LeaseBackend(Protocol):
    """Producer lease coordination with fencing.

    A producer must hold a renewable lease to keep publishing/terminating;
    losing it fences the producer (P0-1).
    """

    async def ensure_ready(self) -> None: ...

    async def claim_lease(
        self,
        lease_key: str,
        state_key: str,
        token: str,
        *,
        ttl_seconds: int,
    ) -> bool: ...

    async def renew_lease(
        self,
        lease_key: str,
        state_key: str,
        token: str,
        *,
        ttl_seconds: int,
    ) -> bool: ...

    async def release_lease(self, key: str, token: str) -> None: ...

    async def set_state_if_lease_owner(
        self,
        lease_key: str,
        state_key: str,
        token: str,
        state: str,
        *,
        ttl_seconds: int,
    ) -> bool: ...


class ResumeBackend(LeaseBackend, Protocol):
    """Coordination backend: KV state + Pub/Sub + producer lease."""

    async def get(self, key: str) -> str | None: ...

    async def publish(self, channel: str, message: str) -> int: ...

    async def subscribe(self, channel: str, handler: MessageHandler) -> None: ...

    async def unsubscribe(self, channel: str) -> None: ...

    async def close(self) -> None: ...
