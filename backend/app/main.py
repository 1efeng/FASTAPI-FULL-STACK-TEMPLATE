from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import sentry_sdk
from fastapi import FastAPI
from fastapi.routing import APIRoute
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from starlette.middleware.cors import CORSMiddleware

from app.agent.agent import clear_agent, configure_agent
from app.auth.api import router as auth_router
from app.chat.api import router as chat_router
from app.core.config import settings
from app.db import models as _models  # noqa: F401
from app.demo.api import router as demo_router
from app.system.api import private_router
from app.system.api import router as system_router
from app.user.api import router as user_router

FRONTEND_DIR = Path(__file__).parent / "frontend"


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Keep the async checkpoint connection alive for the compiled agent."""
    async with AsyncPostgresSaver.from_conn_string(
        str(settings.LANGGRAPH_CHECKPOINT_DATABASE_URI)
    ) as checkpointer:
        configure_agent(checkpointer=checkpointer)
        try:
            yield
        finally:
            clear_agent()


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"


if settings.SENTRY_DSN and settings.ENVIRONMENT != "local":
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
    lifespan=lifespan,
)

if settings.all_cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.all_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(auth_router, prefix=settings.API_V1_STR)
app.include_router(user_router, prefix=settings.API_V1_STR)
app.include_router(demo_router, prefix=settings.API_V1_STR)
app.include_router(chat_router, prefix=settings.API_V1_STR)
app.include_router(system_router, prefix=settings.API_V1_STR)

if settings.ENVIRONMENT == "local":
    app.include_router(private_router, prefix=settings.API_V1_STR)

if FRONTEND_DIR.exists():
    app.frontend("/", directory=FRONTEND_DIR)
