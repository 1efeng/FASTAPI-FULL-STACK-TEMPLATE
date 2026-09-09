from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

engine = create_async_engine(
    str(settings.SQLALCHEMY_DATABASE_URI),
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=60 * 5,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession]:
    """FastAPI database-session dependency."""
    async with AsyncSessionLocal() as session:
        yield session
