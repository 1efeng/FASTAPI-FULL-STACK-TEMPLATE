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

    async def claim_active(self, key: str, *, ttl_seconds: int) -> bool:
        del ttl_seconds
        async with self.bus.lock:
            if key in self.bus.values:
                return False
            self.bus.values[key] = "ACTIVE"
            return True

    async def get(self, key: str) -> str | None:
        return self.bus.values.get(key)

    async def set(self, key: str, value: str, *, ttl_seconds: int) -> None:
        del ttl_seconds
        self.bus.values[key] = value

    async def expire(self, key: str, *, ttl_seconds: int) -> None:
        del key, ttl_seconds

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
