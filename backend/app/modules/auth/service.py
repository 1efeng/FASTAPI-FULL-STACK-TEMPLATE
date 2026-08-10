import uuid
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token, get_password_hash, verify_password
from app.modules.user.model import User
from app.modules.user.repository import UserRepository
from app.utils.email import (
    EmailData,
    generate_password_reset_token,
    generate_reset_password_email,
    verify_password_reset_token,
)

# Dummy hash to use for timing attack prevention when user is not found
# This is an Argon2 hash of a random password, used to ensure constant-time comparison
DUMMY_HASH = "$argon2id$v=19$m=65536,t=3,p=4$MjQyZWE1MzBjYjJlZTI0Yw$YTU4NGM5ZTZmYjE2NzZlZjY0ZWY3ZGRkY2U2OWFjNjk"


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.user_repo = UserRepository(User, db)

    async def authenticate(self, email: str, password: str) -> User | None:
        db_user = await self.user_repo.get_by_email(email)
        if not db_user:
            # Prevent timing attacks by running password verification even when user doesn't exist
            verify_password(password, DUMMY_HASH)
            return None
        verified, updated_password_hash = verify_password(
            password, db_user.hashed_password
        )
        if not verified:
            return None
        if updated_password_hash:
            db_user.hashed_password = updated_password_hash
            self.db.add(db_user)
            await self.db.commit()
            await self.db.refresh(db_user)
        return db_user

    def create_access_token(self, user_id: uuid.UUID) -> str:
        expires_delta = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        return create_access_token(user_id, expires_delta=expires_delta)

    async def recover_password(self, email: str) -> str | None:
        """返回注册邮箱；接口层以统一响应异步安排邮件，避免阻塞请求。"""
        user = await self.user_repo.get_by_email(email)
        if not user:
            return None
        return user.email

    async def reset_password(self, token: str, new_password: str) -> None:
        email = verify_password_reset_token(token=token)
        if not email:
            raise HTTPException(status_code=400, detail="Invalid token")
        user = await self.user_repo.get_by_email(email)
        if not user:
            # Don't reveal that the user doesn't exist - use same error as invalid token
            raise HTTPException(status_code=400, detail="Invalid token")
        elif not user.is_active:
            raise HTTPException(status_code=400, detail="Inactive user")
        user.hashed_password = get_password_hash(new_password)
        self.db.add(user)
        await self.db.commit()

    async def password_recovery_html(self, email: str) -> EmailData | None:
        user = await self.user_repo.get_by_email(email)
        if not user:
            return None
        password_reset_token = generate_password_reset_token(email=email)
        return generate_reset_password_email(
            email_to=user.email, email=email, token=password_reset_token
        )
