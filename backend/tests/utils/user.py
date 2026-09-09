from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.user.model import User
from app.user.schema import UserCreate, UserUpdate
from app.user.service import UserService
from tests.utils.utils import random_email, random_lower_string


async def user_authentication_headers(
    *, client: AsyncClient, email: str, password: str
) -> dict[str, str]:
    data = {"username": email, "password": password}

    r = await client.post(f"{settings.API_V1_STR}/login/access-token", data=data)
    response = r.json()
    auth_token = response["access_token"]
    headers = {"Authorization": f"Bearer {auth_token}"}
    return headers


async def create_random_user(db: AsyncSession) -> User:
    email = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=email, password=password)
    svc = UserService(db)
    return await svc.create_user(user_in)


async def authentication_token_from_email(
    *, client: AsyncClient, email: str, db: AsyncSession
) -> dict[str, str]:
    """
    Return a valid token for the user with given email.

    If the user doesn't exist it is created first.
    """
    password = random_lower_string()
    svc = UserService(db)
    user = await svc.get_by_email(email)
    if not user:
        user_in_create = UserCreate(email=email, password=password)
        await svc.create_user(user_in_create)
    else:
        user_in_update = UserUpdate(password=password)
        await svc.update_user(user, user_in_update)

    return await user_authentication_headers(
        client=client, email=email, password=password
    )
