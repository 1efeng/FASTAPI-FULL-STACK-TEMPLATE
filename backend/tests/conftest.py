from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.infra.database import AsyncSessionLocal, engine
from app.main import app
from app.modules.item.model import Item
from app.modules.user.model import User
from app.modules.user.schema import UserCreate
from app.modules.user.service import UserService
from tests.utils.user import authentication_token_from_email
from tests.utils.utils import get_superuser_token_headers


@pytest.fixture(scope="function", autouse=True)
async def db() -> AsyncGenerator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        # 确保首个超级用户存在
        svc = UserService(session)
        existing = await svc.get_by_email(settings.FIRST_SUPERUSER)
        if not existing:
            await svc.create_user(
                UserCreate(
                    email=settings.FIRST_SUPERUSER,
                    password=settings.FIRST_SUPERUSER_PASSWORD,
                    is_superuser=True,
                )
            )
        yield session
        await session.execute(delete(Item))
        await session.execute(delete(User))
        await session.commit()


@pytest.fixture(scope="function")
async def client() -> AsyncGenerator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture(scope="function")
async def superuser_token_headers(client: AsyncClient) -> dict[str, str]:
    return await get_superuser_token_headers(client)


@pytest.fixture(scope="function")
async def normal_user_token_headers(
    client: AsyncClient, db: AsyncSession
) -> dict[str, str]:
    return await authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )


@pytest.fixture(autouse=True)
async def _dispose_engine() -> AsyncGenerator[None]:
    """每个测试结束后释放连接池,避免 asyncpg 连接跨事件循环复用"""
    yield
    await engine.dispose()
