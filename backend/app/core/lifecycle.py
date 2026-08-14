from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.infra.redis import close_redis, init_redis
from app.modules.chat.execution import get_execution_supervisor


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initialize and release framework-independent shared infrastructure."""
    await init_redis()
    try:
        yield
    finally:
        await get_execution_supervisor().shutdown()
        await close_redis()
