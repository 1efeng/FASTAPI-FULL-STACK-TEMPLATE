from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.exceptions import (
    AppError,
    ConflictError,
    InvalidRequestError,
    PermissionDeniedError,
    ResourceNotFoundError,
)


def _status_code_for(exc: AppError) -> int:
    if isinstance(exc, ResourceNotFoundError):
        return 404
    if isinstance(exc, PermissionDeniedError):
        return 403
    if isinstance(exc, ConflictError):
        return 409
    if isinstance(exc, InvalidRequestError):
        return 400
    return 400


async def app_error_handler(_: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, AppError):
        raise exc
    return JSONResponse(
        status_code=_status_code_for(exc),
        content={"detail": exc.detail},
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
