from __future__ import annotations

import os
import uuid

import pytest

from app.infra.stream_resume import RedisStreamResumeStore, StreamState


@pytest.mark.asyncio
async def test_real_redis_cross_store_resume() -> None:
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        pytest.skip("REDIS_URL is required for real Redis integration test")

    redis = pytest.importorskip("redis.asyncio")
    client_a = redis.from_url(redis_url, decode_responses=True)
    client_b = redis.from_url(redis_url, decode_responses=True)
    prefix = f"test:stream-resume:{uuid.uuid4().hex}"
    owner = RedisStreamResumeStore(client_a, key_prefix=prefix)
    replica = RedisStreamResumeStore(client_b, key_prefix=prefix)

    try:
        release = __import__("asyncio").Event()

        async def producer():
            yield "A"
            await release.wait()
            yield "B"

        original = await owner.start("request-1", producer)
        assert original is not None
        assert await anext(original) == "A"

        resumed = await replica.resume("request-1")
        assert resumed is not None
        assert await anext(resumed) == "A"

        release.set()
        assert "".join([chunk async for chunk in original]) == "B"
        assert "".join([chunk async for chunk in resumed]) == "B"
        assert await replica.status("request-1") is StreamState.DONE
    finally:
        await replica.close()
        await owner.close()
        await client_b.aclose()
        await client_a.aclose()
