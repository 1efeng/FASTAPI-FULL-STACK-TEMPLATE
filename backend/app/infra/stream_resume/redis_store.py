from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from ._backend import MessageHandler, ResumeBackend
from .protocol import ChunkStream, StreamFactory, StreamState
from .runtime import ResumableStreamRuntime

logger = logging.getLogger(__name__)

# Claim a lease only while transport state is missing or ACTIVE. A terminal state
# fences all future starts for that stream_id until its retention TTL expires.
_CLAIM_LEASE_SCRIPT = """
local state = redis.call("GET", KEYS[2])
if state and state ~= "ACTIVE" then
    return 0
end
return redis.call("SET", KEYS[1], ARGV[1], "NX", "EX", ARGV[2]) and 1 or 0
"""

# Lua compare-and-renew: only extend the lease if we still hold it. Returns 1 when
# the token matches (lease renewed), 0 otherwise (lease lost / another producer).
_RENEW_LEASE_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    redis.call("EXPIRE", KEYS[1], ARGV[2])
    redis.call("EXPIRE", KEYS[2], ARGV[2])
    return 1
end
return 0
"""

# State transitions are fenced atomically. A stale producer cannot pass an
# ownership check and then overwrite state after another producer takes over.
_SET_STATE_IF_OWNER_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    redis.call("SET", KEYS[2], ARGV[2], "EX", ARGV[3])
    return 1
end
return 0
"""

# Lua compare-and-release: only clear the lease if we still hold it. Prevents a
# stale producer from deleting the new owner's lease.
_RELEASE_LEASE_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
end
return 0
"""


class _RedisBackend(ResumeBackend):
    """Redis KV + Pub/Sub backend over an injected redis.asyncio.Redis client."""

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client
        self._pubsub: Any = None
        self._handlers: dict[str, MessageHandler] = {}
        self._ready_lock = asyncio.Lock()
        self._subscription_lock = asyncio.Lock()
        self._listener_task: asyncio.Task[None] | None = None
        self._closed = False

    async def ensure_ready(self) -> None:
        if self._pubsub is not None:
            return
        async with self._ready_lock:
            if self._pubsub is not None:
                return
            if self._closed:
                raise RuntimeError("stream-resume Redis backend is closed")
            await self._redis.ping()
            self._pubsub = self._redis.pubsub()

    async def get(self, key: str) -> str | None:
        await self.ensure_ready()
        value = await self._redis.get(key)
        if value is None:
            return None
        if isinstance(value, bytes):
            return value.decode()
        return str(value)

    async def publish(self, channel: str, message: str) -> int:
        await self.ensure_ready()
        return int(await self._redis.publish(channel, message))

    async def subscribe(self, channel: str, handler: MessageHandler) -> None:
        await self.ensure_ready()
        async with self._subscription_lock:
            assert self._pubsub is not None
            self._handlers[channel] = handler
            await self._pubsub.subscribe(channel)
            if self._listener_task is None or self._listener_task.done():
                self._listener_task = asyncio.create_task(
                    self._listen(), name="stream-resume:redis-pubsub"
                )

    async def unsubscribe(self, channel: str) -> None:
        if self._pubsub is None:
            return
        async with self._subscription_lock:
            self._handlers.pop(channel, None)
            await self._pubsub.unsubscribe(channel)

    async def claim_lease(
        self,
        lease_key: str,
        state_key: str,
        token: str,
        *,
        ttl_seconds: int,
    ) -> bool:
        await self.ensure_ready()
        result = await self._redis.eval(
            _CLAIM_LEASE_SCRIPT,
            2,
            lease_key,
            state_key,
            token,
            ttl_seconds,
        )
        return bool(result)

    async def renew_lease(
        self,
        lease_key: str,
        state_key: str,
        token: str,
        *,
        ttl_seconds: int,
    ) -> bool:
        await self.ensure_ready()
        result = await self._redis.eval(
            _RENEW_LEASE_SCRIPT,
            2,
            lease_key,
            state_key,
            token,
            ttl_seconds,
        )
        return bool(result)

    async def release_lease(self, key: str, token: str) -> None:
        await self.ensure_ready()
        await self._redis.eval(_RELEASE_LEASE_SCRIPT, 1, key, token)

    async def set_state_if_lease_owner(
        self,
        lease_key: str,
        state_key: str,
        token: str,
        state: str,
        *,
        ttl_seconds: int,
    ) -> bool:
        await self.ensure_ready()
        result = await self._redis.eval(
            _SET_STATE_IF_OWNER_SCRIPT,
            2,
            lease_key,
            state_key,
            token,
            state,
            ttl_seconds,
        )
        return bool(result)


    async def _listen(self) -> None:
        assert self._pubsub is not None
        try:
            async for message in self._pubsub.listen():
                if message.get("type") != "message":
                    continue
                channel_raw = message["channel"]
                data_raw = message["data"]

                channel = (
                    channel_raw.decode()
                    if isinstance(channel_raw, bytes)
                    else str(channel_raw)
                )
                data = data_raw.decode() if isinstance(data_raw, bytes) else str(data_raw)
                handler = self._handlers.get(channel)
                if handler is None:
                    continue
                try:
                    # Sequential dispatch preserves ordering on this Pub/Sub connection.
                    await handler(data)
                except Exception:
                    logger.exception("stream-resume handler failed: %s", channel)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("stream-resume Redis Pub/Sub listener stopped")

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._listener_task is not None and not self._listener_task.done():
            self._listener_task.cancel()
            await asyncio.gather(self._listener_task, return_exceptions=True)
        self._listener_task = None
        self._handlers.clear()
        if self._pubsub is not None:
            await self._pubsub.aclose()
        self._pubsub = None
        # Intentionally do NOT close the injected Redis client. Product infra owns it.


class RedisStreamResumeStore:
    """Redis-backed implementation of the StreamResumeStore port.

    The provided Redis client remains owned by app.infra.redis. Closing this store only
    tears down its Pub/Sub connection and in-process producer tasks.
    """

    def __init__(
        self,
        redis_client: Any,
        *,
        key_prefix: str = "travel-agent:stream-resume",
        ttl_seconds: int = 3600,
        resume_ack_timeout_seconds: float = 2.0,
        heartbeat_interval_seconds: float | None = None,
        wait_until: Callable[[Awaitable[object]], None] | None = None,
    ) -> None:
        self._runtime = ResumableStreamRuntime(
            _RedisBackend(redis_client),
            key_prefix=key_prefix,
            ttl_seconds=ttl_seconds,
            resume_ack_timeout_seconds=resume_ack_timeout_seconds,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
            wait_until=wait_until,
        )

    async def start(
        self,
        stream_id: str,
        producer: StreamFactory,
    ) -> ChunkStream | None:
        return await self._runtime.start(stream_id, producer)

    async def resume(
        self,
        stream_id: str,
        *,
        skip_characters: int = 0,
    ) -> ChunkStream | None:
        return await self._runtime.resume(
            stream_id,
            skip_characters=skip_characters,
        )

    async def start_or_resume(
        self,
        stream_id: str,
        producer: StreamFactory,
        *,
        skip_characters: int = 0,
    ) -> ChunkStream | None:
        return await self._runtime.start_or_resume(
            stream_id,
            producer,
            skip_characters=skip_characters,
        )

    async def status(self, stream_id: str) -> StreamState:
        return await self._runtime.status(stream_id)

    async def close(self) -> None:
        await self._runtime.close()
