from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable

MessageHandler = Callable[[str], Awaitable[None]]


class MemoryBus:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.handlers: dict[str, list[MessageHandler]] = defaultdict(list)
        self.lock = asyncio.Lock()


class MemoryBackend:
    def __init__(self, bus: MemoryBus) -> None:
        self.bus = bus
        self._closed = False
        self._subscriptions: list[tuple[str, MessageHandler]] = []

    async def ensure_ready(self) -> None:
        if self._closed:
            raise RuntimeError("closed")

    async def claim_lease(
        self,
        lease_key: str,
        state_key: str,
        token: str,
        *,
        ttl_seconds: int,
    ) -> bool:
        del ttl_seconds
        async with self.bus.lock:
            state = self.bus.values.get(state_key)
            if state is not None and state != "ACTIVE":
                return False
            if lease_key in self.bus.values:
                return False
            self.bus.values[lease_key] = token
            return True

    async def renew_lease(
        self,
        lease_key: str,
        state_key: str,
        token: str,
        *,
        ttl_seconds: int,
    ) -> bool:
        del state_key, ttl_seconds
        async with self.bus.lock:
            return self.bus.values.get(lease_key) == token

    async def release_lease(self, key: str, token: str) -> None:
        async with self.bus.lock:
            if self.bus.values.get(key) == token:
                self.bus.values.pop(key, None)

    async def set_state_if_lease_owner(
        self,
        lease_key: str,
        state_key: str,
        token: str,
        state: str,
        *,
        ttl_seconds: int,
    ) -> bool:
        del ttl_seconds
        async with self.bus.lock:
            if self.bus.values.get(lease_key) != token:
                return False
            self.bus.values[state_key] = state
            return True

    async def get(self, key: str) -> str | None:
        return self.bus.values.get(key)

    async def publish(self, channel: str, message: str) -> int:
        handlers = list(self.bus.handlers.get(channel, []))
        for handler in handlers:
            await handler(message)
        return len(handlers)

    async def subscribe(self, channel: str, handler: MessageHandler) -> None:
        self.bus.handlers[channel].append(handler)
        self._subscriptions.append((channel, handler))

    async def unsubscribe(self, channel: str) -> None:
        remaining: list[tuple[str, MessageHandler]] = []
        for subscribed_channel, handler in self._subscriptions:
            if subscribed_channel == channel:
                handlers = self.bus.handlers.get(channel, [])
                if handler in handlers:
                    handlers.remove(handler)
            else:
                remaining.append((subscribed_channel, handler))
        self._subscriptions = remaining

    async def close(self) -> None:
        for channel, _ in list(self._subscriptions):
            await self.unsubscribe(channel)
        self._closed = True
