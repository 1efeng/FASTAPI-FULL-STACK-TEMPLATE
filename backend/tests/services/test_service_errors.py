import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    ConflictError,
    InvalidRequestError,
    PermissionDeniedError,
    ResourceNotFoundError,
)
from app.modules.auth.service import AuthService
from app.modules.item.schema import ItemCreate
from app.modules.item.service import ItemService
from app.modules.user.schema import UserCreate, UserUpdate, UserUpdateMe
from app.modules.user.service import UserService
from app.utils.email import generate_password_reset_token
from tests.utils.utils import random_email, random_lower_string


async def _create_user(
    db: AsyncSession, *, is_superuser: bool = False, is_active: bool = True
):
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


async def test_item_service_raises_application_errors(db: AsyncSession) -> None:
    owner, _ = await _create_user(db)
    other_user, _ = await _create_user(db)
    service = ItemService(db)

    with pytest.raises(ResourceNotFoundError, match="Item not found"):
        await service.get_item_by_id(uuid.uuid4(), owner)

    item = await service.create_item(ItemCreate(title="private item"), owner.id)

    with pytest.raises(PermissionDeniedError, match="Not enough permissions"):
        await service.get_item_by_id(item.id, other_user)


async def test_user_service_raises_application_errors(db: AsyncSession) -> None:
    service = UserService(db)
    user, password = await _create_user(db)
    other_user, _ = await _create_user(db)
    superuser, _ = await _create_user(db, is_superuser=True)

    with pytest.raises(ConflictError, match="already exists"):
        await service.create_user(UserCreate(email=user.email, password=random_lower_string()))

    with pytest.raises(PermissionDeniedError, match="enough privileges"):
        await service.get_user_by_id(uuid.uuid4(), user)

    with pytest.raises(ResourceNotFoundError, match="User not found"):
        await service.get_user_by_id(uuid.uuid4(), superuser)

    with pytest.raises(ResourceNotFoundError, match="does not exist"):
        await service.update_user_by_id(uuid.uuid4(), UserUpdate(full_name="missing"))

    with pytest.raises(ResourceNotFoundError, match="User not found"):
        await service.delete_user_by_id(uuid.uuid4(), superuser)

    with pytest.raises(PermissionDeniedError, match="delete themselves"):
        await service.delete_user_by_id(superuser.id, superuser)

    with pytest.raises(ConflictError, match="already exists"):
        await service.update_user(user, UserUpdate(email=other_user.email))

    with pytest.raises(ConflictError, match="already exists"):
        await service.update_user_me(user, UserUpdateMe(email=other_user.email))

    with pytest.raises(InvalidRequestError, match="Incorrect password"):
        await service.update_password_me(user, random_lower_string(), random_lower_string())

    with pytest.raises(InvalidRequestError, match="cannot be the same"):
        await service.update_password_me(user, password, password)


async def test_auth_service_raises_application_errors(db: AsyncSession) -> None:
    service = AuthService(db)

    with pytest.raises(InvalidRequestError, match="Invalid token"):
        await service.reset_password("invalid-token", random_lower_string())

    missing_email = random_email()
    missing_token = generate_password_reset_token(missing_email)
    with pytest.raises(InvalidRequestError, match="Invalid token"):
        await service.reset_password(missing_token, random_lower_string())

    inactive_user, _ = await _create_user(db, is_active=False)
    inactive_token = generate_password_reset_token(inactive_user.email)
    with pytest.raises(InvalidRequestError, match="Inactive user"):
        await service.reset_password(inactive_token, random_lower_string())


async def test_service_query_and_recovery_paths(db: AsyncSession) -> None:
    user, _ = await _create_user(db)
    superuser, _ = await _create_user(db, is_superuser=True)
    item_service = ItemService(db)
    user_service = UserService(db)
    auth_service = AuthService(db)

    item = await item_service.create_item(ItemCreate(title="owned item"), user.id)

    own_items, own_count = await item_service.list_items(0, 100, False, user.id)
    assert own_count == 1
    assert own_items == [item]

    all_items, all_count = await item_service.list_items(0, 100, True, superuser.id)
    assert all_count == 1
    assert all_items == [item]

    users, user_count = await user_service.list_users(0, 100)
    assert user_count >= 2
    assert user in users
    assert superuser in users

    assert await auth_service.recover_password(random_email()) is None
    assert await auth_service.recover_password(user.email) == user.email
    assert await auth_service.password_recovery_html(random_email()) is None
    assert await auth_service.password_recovery_html(user.email) is not None
