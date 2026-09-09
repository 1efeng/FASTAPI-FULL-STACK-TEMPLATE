from unittest.mock import patch

from httpx import AsyncClient
from pwdlib.hashers.bcrypt import BcryptHasher
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import get_password_hash, verify_password
from app.integrations.email import generate_password_reset_token
from app.user.model import User
from app.user.schema import UserCreate
from app.user.service import UserService
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


async def test_get_access_token(client: AsyncClient) -> None:
    login_data = {"username": settings.FIRST_SUPERUSER, "password": settings.FIRST_SUPERUSER_PASSWORD}
    r = await client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    tokens = r.json()
    assert r.status_code == 200
    assert tokens["access_token"]


async def test_get_access_token_incorrect_password(client: AsyncClient) -> None:
    login_data = {"username": settings.FIRST_SUPERUSER, "password": "incorrect"}
    r = await client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    assert r.status_code == 400


async def test_use_access_token(client: AsyncClient, superuser_token_headers: dict[str, str]) -> None:
    r = await client.post(f"{settings.API_V1_STR}/login/test-token", headers=superuser_token_headers)
    assert r.status_code == 200
    assert "email" in r.json()


async def test_recovery_password(client: AsyncClient, normal_user_token_headers: dict[str, str]) -> None:
    with (
        patch("app.auth.api.send_password_recovery_email", return_value=None),
        patch("app.core.config.settings.SMTP_HOST", "smtp.example.com"),
        patch("app.core.config.settings.SMTP_USER", "admin@example.com"),
    ):
        email = "test@example.com"
        r = await client.post(f"{settings.API_V1_STR}/password-recovery/{email}", headers=normal_user_token_headers)
        assert r.status_code == 200
        assert r.json() == {"message": "If that email is registered, we sent a password recovery link"}


async def test_recovery_password_user_not_exits(client: AsyncClient, normal_user_token_headers: dict[str, str]) -> None:
    email = "jVgQr@example.com"
    r = await client.post(f"{settings.API_V1_STR}/password-recovery/{email}", headers=normal_user_token_headers)
    assert r.status_code == 200
    assert r.json() == {"message": "If that email is registered, we sent a password recovery link"}


async def test_reset_password(client: AsyncClient, db: AsyncSession) -> None:
    email = random_email()
    password = random_lower_string()
    new_password = random_lower_string()
    user_create = UserCreate(email=email, full_name="Test User", password=password, is_active=True, is_superuser=False)
    user = await UserService(db).create_user(user_create)
    token = generate_password_reset_token(email=email)
    headers = await user_authentication_headers(client=client, email=email, password=password)
    data = {"new_password": new_password, "token": token}
    r = await client.post(f"{settings.API_V1_STR}/reset-password/", headers=headers, json=data)
    assert r.status_code == 200
    assert r.json() == {"message": "Password updated successfully"}
    await db.refresh(user)
    verified, _ = verify_password(new_password, user.hashed_password)
    assert verified


async def test_reset_password_invalid_token(client: AsyncClient, superuser_token_headers: dict[str, str]) -> None:
    data = {"new_password": "changethis", "token": "invalid"}
    r = await client.post(f"{settings.API_V1_STR}/reset-password/", headers=superuser_token_headers, json=data)
    assert r.status_code == 400
    assert r.json()["detail"] == "Invalid token"


async def test_login_with_bcrypt_password_upgrades_to_argon2(client: AsyncClient, db: AsyncSession) -> None:
    email = random_email()
    password = random_lower_string()
    bcrypt_hash = BcryptHasher().hash(password)
    user = User(email=email, hashed_password=bcrypt_hash, is_active=True)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    r = await client.post(f"{settings.API_V1_STR}/login/access-token", data={"username": email, "password": password})
    assert r.status_code == 200
    await db.refresh(user)
    assert user.hashed_password.startswith("$argon2")
    verified, updated_hash = verify_password(password, user.hashed_password)
    assert verified
    assert updated_hash is None


async def test_login_with_argon2_password_keeps_hash(client: AsyncClient, db: AsyncSession) -> None:
    email = random_email()
    password = random_lower_string()
    argon2_hash = get_password_hash(password)
    user = User(email=email, hashed_password=argon2_hash, is_active=True)
    db.add(user)
    await db.commit()
    await db.refresh(user)
    original_hash = user.hashed_password
    r = await client.post(f"{settings.API_V1_STR}/login/access-token", data={"username": email, "password": password})
    assert r.status_code == 200
    await db.refresh(user)
    assert user.hashed_password == original_hash
