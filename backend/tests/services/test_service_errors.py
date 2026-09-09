import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import AuthService
from app.integrations.email import generate_password_reset_token
from app.user.model import User
from app.user.schema import UserCreate, UserUpdate, UserUpdateMe
from app.user.service import UserService
from tests.utils.utils import random_email, random_lower_string


async def _create_user(
    db: AsyncSession, *, is_superuser: bool = False, is_active: bool = True
) -> tuple[User, str]:
    password = random_lower_string()
    user = await UserService(db).create_user(
        UserCreate(
            email=random_email(),
            password=password,
            is_superuser=is_superuser,
            is_active=is_active,
        )
    )
    return user, password


async def test_user_service_http_errors(db: AsyncSession) -> None:
    service = UserService(db)
    user, password = await _create_user(db)
    other_user, _ = await _create_user(db)
    superuser, _ = await _create_user(db, is_superuser=True)

    with pytest.raises(HTTPException) as exc_info:
        await service.create_user(UserCreate(email=user.email, password=random_lower_string()))
    assert exc_info.value.status_code == 409

    with pytest.raises(HTTPException) as exc_info:
        await service.get_user_by_id(uuid.uuid4(), user)
    assert exc_info.value.status_code == 403

    with pytest.raises(HTTPException) as exc_info:
        await service.get_user_by_id(uuid.uuid4(), superuser)
    assert exc_info.value.status_code == 404

    with pytest.raises(HTTPException) as exc_info:
        await service.update_user_by_id(uuid.uuid4(), UserUpdate(full_name="missing"))
    assert exc_info.value.status_code == 404

    with pytest.raises(HTTPException) as exc_info:
        await service.delete_user_by_id(uuid.uuid4(), superuser)
    assert exc_info.value.status_code == 404

    with pytest.raises(HTTPException) as exc_info:
        await service.delete_user_by_id(superuser.id, superuser)
    assert exc_info.value.status_code == 403

    with pytest.raises(HTTPException) as exc_info:
        await service.update_user(user, UserUpdate(email=other_user.email))
    assert exc_info.value.status_code == 409

    with pytest.raises(HTTPException) as exc_info:
        await service.update_user_me(user, UserUpdateMe(email=other_user.email))
    assert exc_info.value.status_code == 409

    with pytest.raises(HTTPException) as exc_info:
        await service.update_password_me(user, random_lower_string(), random_lower_string())
    assert exc_info.value.status_code == 400

    with pytest.raises(HTTPException) as exc_info:
        await service.update_password_me(user, password, password)
    assert exc_info.value.status_code == 400


async def test_auth_service_http_errors(db: AsyncSession) -> None:
    service = AuthService(db)

    with pytest.raises(HTTPException) as exc_info:
        await service.reset_password("invalid-token", random_lower_string())
    assert exc_info.value.status_code == 400

    missing_email = random_email()
    missing_token = generate_password_reset_token(missing_email)
    with pytest.raises(HTTPException) as exc_info:
        await service.reset_password(missing_token, random_lower_string())
    assert exc_info.value.status_code == 400

    inactive_user, _ = await _create_user(db, is_active=False)
    inactive_token = generate_password_reset_token(inactive_user.email)
    with pytest.raises(HTTPException) as exc_info:
        await service.reset_password(inactive_token, random_lower_string())
    assert exc_info.value.status_code == 400


async def test_service_query_and_recovery_paths(db: AsyncSession) -> None:
    user, _ = await _create_user(db)
    superuser, _ = await _create_user(db, is_superuser=True)
    user_service = UserService(db)
    auth_service = AuthService(db)

    users, user_count = await user_service.list_users(0, 100)
    assert user_count >= 2
    assert user in users
    assert superuser in users

    assert await auth_service.recover_password(random_email()) is None
    assert await auth_service.recover_password(user.email) == user.email
    assert await auth_service.password_recovery_html(random_email()) is None
    assert await auth_service.password_recovery_html(user.email) is not None
