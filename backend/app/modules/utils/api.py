from collections.abc import Awaitable
from typing import Any, cast

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from pydantic.networks import EmailStr
from redis.asyncio import Redis
from sqlalchemy import text

from app.core.base_schema import Message
from app.core.config import settings
from app.core.deps import SessionDep, get_current_active_superuser
from app.core.security import get_password_hash
from app.modules.user.model import User
from app.modules.user.schema import UserPublic
from app.utils.email import generate_test_email, send_email

router = APIRouter(tags=["utils"])


@router.post(
    "/utils/test-email/",
    dependencies=[Depends(get_current_active_superuser)],
    status_code=201,
)
def test_email(email_to: EmailStr) -> Message:
    email_data = generate_test_email(email_to=email_to)
    send_email(
        email_to=email_to,
        subject=email_data.subject,
        html_content=email_data.html_content,
    )
    return Message(message="Test email sent")


@router.get("/utils/health/live")
async def health_live() -> bool:
    return True


@router.get("/utils/health/ready")
async def health_ready(db: SessionDep) -> bool:
    await db.execute(text("SELECT 1"))
    return True



@router.get("/utils/health/infrastructure")
async def infrastructure_health(db: SessionDep) -> dict[str, str]:
    """Check the configured shared infrastructure dependencies."""
    checks: dict[str, str] = {}
    try:
        await db.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:
        checks["postgres"] = "error"
        raise HTTPException(status_code=503, detail=checks) from exc

    redis_client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    try:
        await cast(Awaitable[bool], redis_client.ping())
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = "error"
        raise HTTPException(status_code=503, detail=checks) from exc
    finally:
        await redis_client.aclose()

    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(
                f"{settings.LITELLM_BASE_URL.rstrip('/')}/health/liveliness"
            )
            response.raise_for_status()
        checks["litellm"] = "ok"
    except Exception as exc:
        checks["litellm"] = "error"
        raise HTTPException(status_code=503, detail=checks) from exc

    return checks

@router.get("/utils/health-check/", include_in_schema=False)
async def health_check(db: SessionDep) -> bool:
    return await health_ready(db)


class PrivateUserCreate(BaseModel):
    email: str
    password: str
    full_name: str
    is_verified: bool = False


private_router = APIRouter(tags=["private"], prefix="/private")


@private_router.post("/users/", response_model=UserPublic)
async def private_create_user(user_in: PrivateUserCreate, db: SessionDep) -> Any:
    """Create a new user (local development only)."""
    user = User(
        email=user_in.email,
        full_name=user_in.full_name,
        hashed_password=get_password_hash(user_in.password),
    )
    db.add(user)
    await db.commit()
    return user
