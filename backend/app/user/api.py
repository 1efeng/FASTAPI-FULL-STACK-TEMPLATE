import uuid
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from app.core.base_schema import Message
from app.core.config import settings
from app.core.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.infra.email import send_new_account_email
from app.user.schema import (
    UpdatePassword,
    UserCreate,
    UserPublic,
    UserRegister,
    UsersPublic,
    UserUpdate,
    UserUpdateMe,
)
from app.user.service import UserService

router = APIRouter(prefix="/users", tags=["users"])
SkipParam = Annotated[int, Query(ge=0)]
LimitParam = Annotated[int, Query(ge=1, le=100)]


def get_user_service(db: SessionDep) -> UserService:
    return UserService(db)


@router.get(
    "/",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=UsersPublic,
)
async def read_users(
    skip: SkipParam = 0,
    limit: LimitParam = 100,
    svc: UserService = Depends(get_user_service),
) -> Any:
    """Retrieve users."""
    users, count = await svc.list_users(skip=skip, limit=limit)
    users_public = [UserPublic.model_validate(user) for user in users]
    return UsersPublic(data=users_public, count=count)


@router.post(
    "/", dependencies=[Depends(get_current_active_superuser)], response_model=UserPublic
)
async def create_user(
    *,
    user_in: UserCreate,
    background_tasks: BackgroundTasks,
    svc: UserService = Depends(get_user_service),
) -> Any:
    """Create new user."""
    user = await svc.create_user(user_in)
    if settings.emails_enabled and user_in.email:
        background_tasks.add_task(
            send_new_account_email,
            email_to=user_in.email,
            username=user_in.email,
            password=user_in.password,
        )
    return user


@router.patch("/me", response_model=UserPublic)
async def update_user_me(
    *,
    user_in: UserUpdateMe,
    current_user: CurrentUser,
    svc: UserService = Depends(get_user_service),
) -> Any:
    """Update own user."""
    return await svc.update_user_me(current_user, user_in)


@router.patch("/me/password", response_model=Message)
async def update_password_me(
    *,
    body: UpdatePassword,
    current_user: CurrentUser,
    svc: UserService = Depends(get_user_service),
) -> Any:
    """Update own password."""
    await svc.update_password_me(current_user, body.current_password, body.new_password)
    return Message(message="Password updated successfully")


@router.get("/me", response_model=UserPublic)
async def read_user_me(current_user: CurrentUser) -> Any:
    """Get current user."""
    return current_user


@router.delete("/me", response_model=Message)
async def delete_user_me(
    current_user: CurrentUser, svc: UserService = Depends(get_user_service)
) -> Any:
    """Delete own user."""
    if current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="Super users are not allowed to delete themselves"
        )
    await svc.delete_user(current_user)
    return Message(message="User deleted successfully")


@router.post("/signup", response_model=UserPublic)
async def register_user(
    user_in: UserRegister, svc: UserService = Depends(get_user_service)
) -> Any:
    """Create new user without the need to be logged in."""
    user_create = UserCreate(**user_in.model_dump())
    return await svc.create_user(user_create)


@router.get("/{user_id}", response_model=UserPublic)
async def read_user_by_id(
    user_id: uuid.UUID,
    current_user: CurrentUser,
    svc: UserService = Depends(get_user_service),
) -> Any:
    """Get a specific user by id."""
    return await svc.get_user_by_id(user_id, current_user)


@router.patch(
    "/{user_id}",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=UserPublic,
)
async def update_user(
    *,
    user_id: uuid.UUID,
    user_in: UserUpdate,
    svc: UserService = Depends(get_user_service),
) -> Any:
    """Update a user."""
    return await svc.update_user_by_id(user_id, user_in)


@router.delete("/{user_id}", dependencies=[Depends(get_current_active_superuser)])
async def delete_user(
    current_user: CurrentUser,
    user_id: uuid.UUID,
    svc: UserService = Depends(get_user_service),
) -> Message:
    """Delete a user."""
    await svc.delete_user_by_id(user_id, current_user)
    return Message(message="User deleted successfully")
