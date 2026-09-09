import json

import pytest
from fastapi import FastAPI

from app.core.exception_handlers import _status_code_for, app_error_handler, register_exception_handlers
from app.core.exceptions import (
    AppError,
    ConflictError,
    InvalidRequestError,
    PermissionDeniedError,
    ResourceNotFoundError,
)


@pytest.mark.parametrize(
    ("exc", "expected_status"),
    [
        (ResourceNotFoundError("missing"), 404),
        (PermissionDeniedError("forbidden"), 403),
        (ConflictError("conflict"), 409),
        (InvalidRequestError("invalid"), 400),
        (AppError("application error"), 400),
    ],
)
def test_status_code_for(exc: AppError, expected_status: int) -> None:
    assert _status_code_for(exc) == expected_status


async def test_app_error_handler_returns_fastapi_detail_shape() -> None:
    response = await app_error_handler(
        None,  # type: ignore[arg-type]
        ConflictError("User with this email already exists"),
    )

    assert response.status_code == 409
    assert json.loads(response.body) == {
        "detail": "User with this email already exists"
    }


async def test_app_error_handler_reraises_unexpected_exception() -> None:
    error = RuntimeError("unexpected")

    with pytest.raises(RuntimeError, match="unexpected"):
        await app_error_handler(None, error)  # type: ignore[arg-type]


def test_register_exception_handlers() -> None:
    app = FastAPI()

    register_exception_handlers(app)

    assert app.exception_handlers[AppError] is app_error_handler
