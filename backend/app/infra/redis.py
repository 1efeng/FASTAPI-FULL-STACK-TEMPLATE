
from collections.abc import Awaitable
from typing import cast

from redis.asyncio import Redis

from app.core.config import settings

_client: Redis | None = None


def namespaced_key(*parts: object) -> str:
    """Build a Redis key owned by this application."""
    suffix = ":".join(str(part).strip(":") for part in parts)
    return f"{settings.REDIS_KEY_PREFIX.rstrip(':')}:{suffix}"


async def init_redis() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        await cast(Awaitable[bool], _client.ping())
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def get_redis() -> Redis:
    if _client is None:
        raise RuntimeError("Redis client has not been initialized")
    return _client
