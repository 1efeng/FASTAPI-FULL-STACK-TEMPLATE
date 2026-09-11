"""JWT auth bridge between the FastAPI application and Aegra.

The FastAPI app issues HS256 JWTs (``sub`` = user UUID). Aegra loads this
module from ``aegra.json`` and calls ``authenticate`` on every request; the
returned identity becomes ``config.configurable.user_id`` for the run, giving
per-thread owner isolation across instances.
"""

from __future__ import annotations

import os
from typing import Any

import jwt
from langgraph_sdk import Auth

ALGORITHM = "HS256"


def _env(name: str) -> str | None:
    value = os.environ.get(name)
    return value if value else None


auth = Auth()


@auth.authenticate
async def authenticate(headers: dict[str, str]) -> Auth.types.MinimalUserDict:
    authorization = headers.get("authorization") or headers.get("Authorization")
    if not authorization or not authorization.startswith("Bearer "):
        raise Auth.exceptions.HTTPException(status_code=401, detail="Not authenticated")

    token = authorization.removeprefix("Bearer ").strip()
    secret = _env("SECRET_KEY")
    if not secret:
        raise Auth.exceptions.HTTPException(
            status_code=500, detail="SECRET_KEY is not configured"
        )

    try:
        payload: dict[str, Any] = jwt.decode(token, secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise Auth.exceptions.HTTPException(
            status_code=401, detail="Invalid or expired token"
        ) from exc

    subject = payload.get("sub")
    if not subject:
        raise Auth.exceptions.HTTPException(status_code=401, detail="Token missing subject")

    return {
        "identity": str(subject),
        "permissions": [],
    }
