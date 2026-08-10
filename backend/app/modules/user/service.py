import uuid
from collections.abc import Awaitable, Callable
from typing import TypeVar

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_password_hash, verify_password
from app.modules.user.model import User
from app.modules.user.repository import UserRepository
from app.modules.user.schema import UserCreate, UserUpdate, UserUpdateMe

T = TypeVar("T")


class UserService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = UserRepository(User, db)

    async def _commit_email_change(self, operation: Callable[[], Awaitable[T]]) -> T:
        try:
            result = await operation()
            await self.db.commit()
            return result
        except IntegrityError as exc:
            await self.db.rollback()
            if "email" in str(exc).lower():
                raise HTTPException(
                    status_code=409, detail="User with this email already exists"
                ) from exc
            raise

    async def list_users(self, skip: int, limit: int) -> tuple[list[User], int]:
        count_statement = select(func.count()).select_from(User)
        count = (await self.db.execute(count_statement)).scalar_one()
        statement = (
            select(User).order_by(User.created_at.desc()).offset(skip).limit(limit)
        )
        users = (await self.db.execute(statement)).scalars().all()
        return list(users), count

    async def get_user_by_id(self, user_id: uuid.UUID, current_user: User) -> User:
        user = await self.repo.get_by_id(user_id)
        if user is not None and user == current_user:
            return user
        if not current_user.is_superuser:
            raise HTTPException(
                status_code=403,
                detail="The user doesn't have enough privileges",
            )
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        return user

    async def update_user_by_id(self, user_id: uuid.UUID, user_in: UserUpdate) -> User:
        db_user = await self.repo.get_by_id(user_id)
        if not db_user:
            raise HTTPException(
                status_code=404,
                detail="The user with this id does not exist in the system",
            )
        return await self.update_user(db_user, user_in)

    async def delete_user_by_id(self, user_id: uuid.UUID, current_user: User) -> None:
        user = await self.repo.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        if user == current_user:
            raise HTTPException(
                status_code=403,
                detail="Super users are not allowed to delete themselves",
            )
        await self.delete_user(user)

    async def create_user(self, user_create: UserCreate) -> User:
        email = user_create.email.casefold()
        existing = await self.repo.get_by_email(email)
        if existing:
            raise HTTPException(
                status_code=409, detail="User with this email already exists"
            )
        user = User(
            email=email,
            is_active=user_create.is_active,
            is_superuser=user_create.is_superuser,
            full_name=user_create.full_name,
            hashed_password=get_password_hash(user_create.password),
        )
        return await self._commit_email_change(lambda: self.repo.create(user))

    async def update_user(self, db_user: User, user_in: UserUpdate) -> User:
        email = user_in.email.casefold() if user_in.email else None
        if email:
            existing_user = await self.repo.get_by_email(email)
            if existing_user and existing_user.id != db_user.id:
                raise HTTPException(
                    status_code=409, detail="User with this email already exists"
                )
        user_data = user_in.model_dump(exclude_unset=True, exclude={"password"})
        if email:
            user_data["email"] = email
        if user_in.password:
            db_user.hashed_password = get_password_hash(user_in.password)
        for field, value in user_data.items():
            setattr(db_user, field, value)
        return await self._commit_email_change(lambda: self.repo.update(db_user))

    async def update_user_me(self, current_user: User, user_in: UserUpdateMe) -> User:
        email = user_in.email.casefold() if user_in.email else None
        if email:
            existing_user = await self.repo.get_by_email(email)
            if existing_user and existing_user.id != current_user.id:
                raise HTTPException(
                    status_code=409, detail="User with this email already exists"
                )
        user_data = user_in.model_dump(exclude_unset=True)
        if email:
            user_data["email"] = email
        for field, value in user_data.items():
            setattr(current_user, field, value)
        return await self._commit_email_change(lambda: self.repo.update(current_user))

    async def update_password_me(
        self, current_user: User, current_password: str, new_password: str
    ) -> None:
        verified, _ = verify_password(current_password, current_user.hashed_password)
        if not verified:
            raise HTTPException(status_code=400, detail="Incorrect password")
        if current_password == new_password:
            raise HTTPException(
                status_code=400,
                detail="New password cannot be the same as the current one",
            )
        current_user.hashed_password = get_password_hash(new_password)
        await self.repo.update(current_user)
        await self.db.commit()

    async def get_by_email(self, email: str) -> User | None:
        return await self.repo.get_by_email(email)

    async def delete_user(self, user: User) -> None:
        await self.repo.delete(user)
        await self.db.commit()
