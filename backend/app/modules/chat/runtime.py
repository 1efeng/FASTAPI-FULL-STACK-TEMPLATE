import asyncio
import logging
import math
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol, cast
from zoneinfo import ZoneInfo

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.infra.redis import get_redis, namespaced_key

logger = logging.getLogger(__name__)

AdmissionErrorCode = Literal[
    "RATE_LIMITED",
    "QUOTA_EXCEEDED",
    "CONCURRENCY_LIMITED",
    "INTERNAL_ERROR",
]


@dataclass(slots=True)
class ChatAdmissionRejected(Exception):
    code: AdmissionErrorCode
    message: str
    retryable: bool = True


@dataclass(slots=True)
class ChatAdmissionLease:
    concurrency_key: str | None = None


class ChatRuntime(Protocol):
    async def admit(
        self, *, client_ip: str, user_id: uuid.UUID
    ) -> ChatAdmissionLease: ...

    async def release(self, lease: ChatAdmissionLease) -> None: ...

    async def wait_for_cancel(self, request_id: uuid.UUID) -> None: ...

    async def signal_cancel(self, request_id: uuid.UUID) -> None: ...

    async def finish_request(self, request_id: uuid.UUID) -> None: ...


class LocalChatRuntime:
    """Test/fail-open runtime that only propagates same-process cancellation."""

    def __init__(self) -> None:
        self._cancel_events: dict[uuid.UUID, asyncio.Event] = {}

    async def admit(
        self, *, client_ip: str, user_id: uuid.UUID
    ) -> ChatAdmissionLease:
        del client_ip, user_id
        return ChatAdmissionLease()

    async def release(self, lease: ChatAdmissionLease) -> None:
        del lease

    async def wait_for_cancel(self, request_id: uuid.UUID) -> None:
        event = self._cancel_events.setdefault(request_id, asyncio.Event())
        await event.wait()

    async def signal_cancel(self, request_id: uuid.UUID) -> None:
        self._cancel_events.setdefault(request_id, asyncio.Event()).set()

    async def finish_request(self, request_id: uuid.UUID) -> None:
        self._cancel_events.pop(request_id, None)


_ACQUIRE_CONCURRENCY_SCRIPT = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
local limit = tonumber(ARGV[1])
if current >= limit then
  return 0
end
current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[2]))
end
return current
"""

_RELEASE_CONCURRENCY_SCRIPT = """
local current = tonumber(redis.call('GET', KEYS[1]) or '0')
if current <= 1 then
  redis.call('DEL', KEYS[1])
  return 0
end
return redis.call('DECR', KEYS[1])
"""

_RATE_AND_QUOTA_SCRIPT = """
local ip_count = tonumber(redis.call('GET', KEYS[1]) or '0')
local user_count = tonumber(redis.call('GET', KEYS[2]) or '0')
local daily_count = tonumber(redis.call('GET', KEYS[3]) or '0')
if ip_count >= tonumber(ARGV[1]) then return 1 end
if user_count >= tonumber(ARGV[2]) then return 2 end
if daily_count >= tonumber(ARGV[3]) then return 3 end
local ip_next = redis.call('INCR', KEYS[1])
local user_next = redis.call('INCR', KEYS[2])
local daily_next = redis.call('INCR', KEYS[3])
if ip_next == 1 then redis.call('EXPIRE', KEYS[1], tonumber(ARGV[4])) end
if user_next == 1 then redis.call('EXPIRE', KEYS[2], tonumber(ARGV[4])) end
if daily_next == 1 then redis.call('EXPIRE', KEYS[3], tonumber(ARGV[5])) end
return 0
"""


class RedisChatRuntime(LocalChatRuntime):
    def __init__(self, redis: Redis) -> None:
        super().__init__()
        self.redis = redis

    @staticmethod
    def _daily_bucket(now: datetime) -> tuple[str, int]:
        local_now = now.astimezone(ZoneInfo(settings.APP_TIMEZONE))
        next_day = (local_now + timedelta(days=1)).date()
        next_midnight = datetime.combine(
            next_day,
            datetime.min.time(),
            tzinfo=local_now.tzinfo,
        )
        ttl = max(1, math.ceil((next_midnight - local_now).total_seconds()))
        return local_now.strftime("%Y%m%d"), ttl

    async def _release_key(self, key: str) -> None:
        await self.redis.eval(_RELEASE_CONCURRENCY_SCRIPT, 1, key)

    def _redis_failure(self, exc: RedisError) -> ChatAdmissionLease:
        logger.exception("Redis chat protection failed")
        if settings.CHAT_REDIS_FAILURE_POLICY == "fail_open":
            return ChatAdmissionLease()
        raise ChatAdmissionRejected(
            code="INTERNAL_ERROR",
            message="请求保护服务暂时不可用，请稍后重试。",
        ) from exc

    async def admit(
        self, *, client_ip: str, user_id: uuid.UUID
    ) -> ChatAdmissionLease:
        concurrency_key = namespaced_key("chat", "concurrency", user_id)
        lease_ttl = max(30, math.ceil(settings.REQUEST_DEADLINE_SECONDS) + 30)
        try:
            acquired = int(
                await self.redis.eval(
                    _ACQUIRE_CONCURRENCY_SCRIPT,
                    1,
                    concurrency_key,
                    settings.CHAT_CONCURRENT_LIMIT,
                    lease_ttl,
                )
            )
            if acquired == 0:
                raise ChatAdmissionRejected(
                    code="CONCURRENCY_LIMITED",
                    message="当前并发请求已达上限，请等待现有请求完成。",
                )

            now = datetime.now(UTC)
            minute_bucket = now.strftime("%Y%m%d%H%M")
            daily_bucket, daily_ttl = self._daily_bucket(now)
            decision = int(
                await self.redis.eval(
                    _RATE_AND_QUOTA_SCRIPT,
                    3,
                    namespaced_key("chat", "rate", "ip", client_ip, minute_bucket),
                    namespaced_key("chat", "rate", "user", user_id, minute_bucket),
                    namespaced_key("chat", "quota", user_id, daily_bucket),
                    settings.CHAT_IP_RATE_LIMIT_PER_MINUTE,
                    settings.CHAT_USER_RATE_LIMIT_PER_MINUTE,
                    settings.CHAT_DAILY_QUOTA,
                    120,
                    daily_ttl,
                )
            )
            if decision:
                await self._release_key(concurrency_key)
                if decision == 3:
                    raise ChatAdmissionRejected(
                        code="QUOTA_EXCEEDED",
                        message="今日请求额度已用完，请明日再试。",
                        retryable=False,
                    )
                raise ChatAdmissionRejected(
                    code="RATE_LIMITED",
                    message="请求过于频繁，请稍后重试。",
                )
            return ChatAdmissionLease(concurrency_key=concurrency_key)
        except ChatAdmissionRejected:
            raise
        except RedisError as exc:
            try:
                await self._release_key(concurrency_key)
            except RedisError:
                logger.exception("Failed to release Redis concurrency lease")
            return self._redis_failure(exc)

    async def release(self, lease: ChatAdmissionLease) -> None:
        if lease.concurrency_key is None:
            return
        try:
            await self._release_key(lease.concurrency_key)
        except RedisError:
            logger.exception("Failed to release Redis concurrency lease")

    async def wait_for_cancel(self, request_id: uuid.UUID) -> None:
        event = self._cancel_events.setdefault(request_id, asyncio.Event())
        key = namespaced_key("chat", "cancel", request_id)
        while not event.is_set():
            try:
                if await self.redis.get(key):
                    event.set()
                    break
            except RedisError:
                logger.exception("Failed to poll Redis request cancellation")
            try:
                await asyncio.wait_for(event.wait(), timeout=0.25)
            except TimeoutError:
                pass

    async def signal_cancel(self, request_id: uuid.UUID) -> None:
        await super().signal_cancel(request_id)
        key = namespaced_key("chat", "cancel", request_id)
        ttl = max(60, math.ceil(settings.REQUEST_DEADLINE_SECONDS) + 60)
        try:
            await self.redis.set(key, "1", ex=ttl)
        except RedisError:
            logger.exception("Failed to publish Redis request cancellation")


_runtime: RedisChatRuntime | None = None


def get_chat_runtime() -> ChatRuntime:
    global _runtime
    redis = get_redis()
    if _runtime is None or _runtime.redis is not redis:
        _runtime = RedisChatRuntime(cast(Redis, redis))
    return _runtime
