from pathlib import Path

import sentry_sdk
from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.exception_handlers import register_exception_handlers
from app.db import (
    models as _models,  # noqa: F401   # 显式注册所有模型,不依赖 router 链路传递加载
)
from app.modules.auth.api import router as auth_router
from app.modules.item.api import router as item_router
from app.modules.user.api import router as user_router
from app.modules.utils.api import private_router
from app.modules.utils.api import router as utils_router

FRONTEND_DIR = Path(__file__).parent / "frontend"


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"


if settings.SENTRY_DSN and settings.ENVIRONMENT != "local":
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
)

# Service/domain errors are translated to HTTP responses only at the API boundary.
register_exception_handlers(app)

# Set all CORS enabled origins
if settings.all_cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.all_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# 注册各业务模块的路由
app.include_router(auth_router, prefix=settings.API_V1_STR)
app.include_router(user_router, prefix=settings.API_V1_STR)
app.include_router(item_router, prefix=settings.API_V1_STR)
app.include_router(utils_router, prefix=settings.API_V1_STR)

# 仅本地环境暴露的开发路由
if settings.ENVIRONMENT == "local":
    app.include_router(private_router, prefix=settings.API_V1_STR)

# 仅在构建产物存在时挂载前端,否则跳过(避免未构建前端时启动即崩溃)
if FRONTEND_DIR.exists():
    app.frontend("/", directory=FRONTEND_DIR)
