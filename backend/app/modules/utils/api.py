from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from pydantic.networks import EmailStr
from sqlalchemy import text

from app.core.base_schema import Message
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
