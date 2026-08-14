import asyncio
import os
import uuid
from collections.abc import Awaitable
from typing import Any, cast

import pytest
from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.modules.chat.runtime import (
    ChatAdmissionRejected,
    RedisChatRuntime,
)

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_REDIS_INTEGRATION") != "1",
    reason="Set RUN_REDIS_INTEGRATION=1 to run real Redis chat protection tests",
)


async def _runtime() -> tuple[RedisChatRuntime, Redis]:
    client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    await cast(Awaitable[bool], client.ping())
    return RedisChatRuntime(client), client


async def test_redis_ip_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CHAT_IP_RATE_LIMIT_PER_MINUTE", 1)
    monkeypatch.setattr(settings, "CHAT_USER_RATE_LIMIT_PER_MINUTE", 100)
    monkeypatch.setattr(settings, "CHAT_DAILY_QUOTA", 100)
    monkeypatch.setattr(settings, "CHAT_CONCURRENT_LIMIT", 10)
    runtime, client = await _runtime()
    ip = f"m6-ip-{uuid.uuid4()}"

    first = await runtime.admit(client_ip=ip, user_id=uuid.uuid4())
    await runtime.release(first)
    with pytest.raises(ChatAdmissionRejected) as exc:
        await runtime.admit(client_ip=ip, user_id=uuid.uuid4())
    assert exc.value.code == "RATE_LIMITED"
    await client.aclose()


async def test_redis_user_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CHAT_IP_RATE_LIMIT_PER_MINUTE", 100)
    monkeypatch.setattr(settings, "CHAT_USER_RATE_LIMIT_PER_MINUTE", 1)
    monkeypatch.setattr(settings, "CHAT_DAILY_QUOTA", 100)
    monkeypatch.setattr(settings, "CHAT_CONCURRENT_LIMIT", 10)
    runtime, client = await _runtime()
    user_id = uuid.uuid4()

    first = await runtime.admit(client_ip="m6-user-a", user_id=user_id)
    await runtime.release(first)
    with pytest.raises(ChatAdmissionRejected) as exc:
        await runtime.admit(client_ip="m6-user-b", user_id=user_id)
    assert exc.value.code == "RATE_LIMITED"
    await client.aclose()


async def test_redis_daily_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "CHAT_IP_RATE_LIMIT_PER_MINUTE", 100)
    monkeypatch.setattr(settings, "CHAT_USER_RATE_LIMIT_PER_MINUTE", 100)
    monkeypatch.setattr(settings, "CHAT_DAILY_QUOTA", 1)
    monkeypatch.setattr(settings, "CHAT_CONCURRENT_LIMIT", 10)
    runtime, client = await _runtime()
    user_id = uuid.uuid4()

    first = await runtime.admit(client_ip="m6-quota-a", user_id=user_id)
    await runtime.release(first)
    with pytest.raises(ChatAdmissionRejected) as exc:
        await runtime.admit(client_ip="m6-quota-b", user_id=user_id)
    assert exc.value.code == "QUOTA_EXCEEDED"
    assert exc.value.retryable is False
    await client.aclose()


async def test_redis_concurrency_and_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "CHAT_IP_RATE_LIMIT_PER_MINUTE", 100)
    monkeypatch.setattr(settings, "CHAT_USER_RATE_LIMIT_PER_MINUTE", 100)
    monkeypatch.setattr(settings, "CHAT_DAILY_QUOTA", 100)
    monkeypatch.setattr(settings, "CHAT_CONCURRENT_LIMIT", 1)
    runtime, client = await _runtime()
    user_id = uuid.uuid4()

    first = await runtime.admit(client_ip="m6-concurrency-a", user_id=user_id)
    with pytest.raises(ChatAdmissionRejected) as exc:
        await runtime.admit(client_ip="m6-concurrency-b", user_id=user_id)
    assert exc.value.code == "CONCURRENCY_LIMITED"
    await runtime.release(first)

    second = await runtime.admit(client_ip="m6-concurrency-c", user_id=user_id)
    await runtime.release(second)
    await client.aclose()


async def test_redis_cancel_signal_cross_runtime() -> None:
    first_runtime, first_client = await _runtime()
    second_runtime, second_client = await _runtime()
    request_id = uuid.uuid4()
    waiter = asyncio.create_task(second_runtime.wait_for_cancel(request_id))

    await first_runtime.signal_cancel(request_id)
    await asyncio.wait_for(waiter, timeout=2)

    await first_runtime.finish_request(request_id)
    await second_runtime.finish_request(request_id)
    await first_client.aclose()
    await second_client.aclose()


class FailingRedis:
    async def eval(self, *_: Any, **__: Any) -> Any:
        raise RedisError("forced Redis failure")


@pytest.mark.parametrize(
    ("policy", "raises"),
    [("fail_open", False), ("fail_closed", True)],
)
async def test_redis_failure_policy(
    policy: str,
    raises: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "CHAT_REDIS_FAILURE_POLICY", policy)
    runtime = RedisChatRuntime(cast(Redis, FailingRedis()))

    if raises:
        with pytest.raises(ChatAdmissionRejected) as exc:
            await runtime.admit(client_ip="failure", user_id=uuid.uuid4())
        assert exc.value.code == "INTERNAL_ERROR"
    else:
        lease = await runtime.admit(client_ip="failure", user_id=uuid.uuid4())
        assert lease.concurrency_key is None
