from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import pytest

from app.infra.stream_resume import (
    RedisStreamResumeStore,
    StreamProducerInterrupted,
    StreamState,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("REDIS_URL"),
    reason="REDIS_URL is required for real Redis integration tests",
)


@asynccontextmanager
async def real_redis() -> AsyncIterator[tuple[Any, Any, str]]:
    redis_url = os.environ["REDIS_URL"]

    redis = pytest.importorskip("redis.asyncio")
    client_a = redis.from_url(redis_url, decode_responses=True)
    client_b = redis.from_url(redis_url, decode_responses=True)
    prefix = f"test:stream-resume:{uuid.uuid4().hex}"
    try:
        await client_a.ping()
        await client_b.ping()
        yield client_a, client_b, prefix
    finally:
        keys = [key async for key in client_a.scan_iter(f"{prefix}:*")]
        if keys:
            await client_a.delete(*keys)
        await client_b.aclose()
        await client_a.aclose()


async def collect(stream: AsyncIterator[str]) -> str:
    return "".join([chunk async for chunk in stream])


@pytest.mark.asyncio
async def test_real_redis_cross_store_resume() -> None:
    async with real_redis() as (client_a, client_b, prefix):
        owner = RedisStreamResumeStore(client_a, key_prefix=prefix)
        replica = RedisStreamResumeStore(client_b, key_prefix=prefix)
        release = asyncio.Event()

        async def producer():
            yield "A"
            await release.wait()
            yield "B"

        try:
            original = await owner.start("request-1", producer)
            assert original is not None
            assert await anext(original) == "A"

            resumed = await replica.resume("request-1")
            assert resumed is not None
            assert await anext(resumed) == "A"

            release.set()
            assert await collect(original) == "B"
            assert await collect(resumed) == "B"
            assert await replica.status("request-1") is StreamState.DONE
        finally:
            await replica.close()
            await owner.close()


@pytest.mark.asyncio
async def test_real_redis_concurrent_claim_has_one_producer() -> None:
    async with real_redis() as (client_a, client_b, prefix):
        owner = RedisStreamResumeStore(client_a, key_prefix=prefix)
        contender = RedisStreamResumeStore(client_b, key_prefix=prefix)
        release = asyncio.Event()
        producer_calls = 0

        async def producer():
            nonlocal producer_calls
            producer_calls += 1
            await release.wait()
            yield "done"

        try:
            first, second = await asyncio.gather(
                owner.start("claim-race", producer),
                contender.start("claim-race", producer),
            )
            assert (first is None) != (second is None)
            assert producer_calls == 1

            release.set()
            winner = first if first is not None else second
            assert winner is not None
            assert await collect(winner) == "done"
        finally:
            await contender.close()
            await owner.close()


@pytest.mark.asyncio
async def test_real_redis_terminal_state_blocks_restart() -> None:
    async with real_redis() as (client_a, client_b, prefix):
        first_store = RedisStreamResumeStore(client_a, key_prefix=prefix)
        second_store = RedisStreamResumeStore(client_b, key_prefix=prefix)
        producer_calls = 0

        async def producer():
            nonlocal producer_calls
            producer_calls += 1
            yield "done"

        try:
            first = await first_store.start("terminal", producer)
            assert first is not None
            assert await collect(first) == "done"

            second = await second_store.start("terminal", producer)
            assert second is None
            assert producer_calls == 1
            assert await second_store.status("terminal") is StreamState.DONE
        finally:
            await second_store.close()
            await first_store.close()


@pytest.mark.asyncio
async def test_real_redis_ttl_takeover_fences_stale_owner() -> None:
    async with real_redis() as (client_a, client_b, prefix):
        old_owner = RedisStreamResumeStore(
            client_a,
            key_prefix=prefix,
            ttl_seconds=10,
            heartbeat_interval_seconds=0.2,
        )
        new_owner = RedisStreamResumeStore(
            client_b,
            key_prefix=prefix,
            ttl_seconds=10,
            heartbeat_interval_seconds=0.05,
        )
        release_old = asyncio.Event()
        release_new = asyncio.Event()
        lease_key = f"{prefix}:lease:takeover"

        async def old_producer():
            yield "old"
            await release_old.wait()
            yield "stale-final"

        async def new_producer():
            yield "new"
            await release_new.wait()
            yield "winner-final"

        try:
            old_stream = await old_owner.start("takeover", old_producer)
            assert old_stream is not None
            assert await anext(old_stream) == "old"

            # Accelerate the real Redis TTL path without weakening the production
            # runtime's minimum configured lease TTL.
            assert await client_a.pexpire(lease_key, 20)
            await asyncio.sleep(0.05)

            new_stream = await new_owner.start("takeover", new_producer)
            assert new_stream is not None
            assert await anext(new_stream) == "new"

            # Let the old owner's compare-and-renew observe the replacement token.
            await asyncio.sleep(0.2)
            release_old.set()
            with pytest.raises(StreamProducerInterrupted):
                await anext(old_stream)

            # The stale owner's compare-and-release must not delete the new lease,
            # and its terminal path must not overwrite the new ACTIVE state.
            assert await client_b.get(lease_key) is not None
            assert await new_owner.status("takeover") is StreamState.ACTIVE

            release_new.set()
            assert await collect(new_stream) == "winner-final"
            assert await new_owner.status("takeover") is StreamState.DONE
        finally:
            await new_owner.close()
            await old_owner.close()


@pytest.mark.asyncio
async def test_real_redis_close_keeps_shared_client_usable() -> None:
    async with real_redis() as (client_a, _client_b, prefix):
        store = RedisStreamResumeStore(client_a, key_prefix=prefix)
        release = asyncio.Event()

        async def producer():
            yield "started"
            await release.wait()

        stream = await store.start("close", producer)
        assert stream is not None
        assert await anext(stream) == "started"

        await store.close()

        assert await client_a.ping()
        assert await client_a.get(f"{prefix}:state:close") == "INTERRUPTED"
        with pytest.raises(StreamProducerInterrupted):
            await anext(stream)
