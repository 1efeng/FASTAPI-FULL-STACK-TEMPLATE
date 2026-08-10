from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.infra.llm import init_llm
from app.infra.redis import close_redis, init_redis


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Initialize and release process-scoped infrastructure clients."""
    await init_redis()
    init_llm()
    try:
        yield
    finally:
        await close_redis()
