import os

import pytest

from app.infra.redis import close_redis, get_redis, init_redis, namespaced_key


async def test_namespaced_key() -> None:
    key = namespaced_key("rate", "user", "123")
    assert key.endswith(":rate:user:123")


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_REDIS_INTEGRATION") != "1",
    reason="set RUN_REDIS_INTEGRATION=1 to run against a real Redis service",
)
async def test_redis_client_lifecycle() -> None:
    client = await init_redis()
    key = namespaced_key("integration", "lifecycle")
    try:
        await client.set(key, "ok", ex=30)
        assert await client.get(key) == "ok"
    finally:
        await client.delete(key)
        await close_redis()

    with pytest.raises(RuntimeError):
        get_redis()
