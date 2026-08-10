from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

# 1. 创建异步引擎(连接池)
engine = create_async_engine(
    str(settings.SQLALCHEMY_DATABASE_URI),
    pool_size=10,  # 连接池大小
    max_overflow=20,  # 超过连接池大小后,最多可创建的连接数
    pool_timeout=30,  # 获取连接超时(秒)
    pool_recycle=60 * 5,  # 连接最大空闲时间(秒)
    pool_pre_ping=True,  # 取连接前先测试可用性
)

# 2. 创建异步会话工厂
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # 提交后会话不失效,便于读取属性
)


# 3. 异步获取数据库会话连接(供 FastAPI 依赖注入)
async def get_db() -> AsyncGenerator[AsyncSession]:
    """FastAPI 依赖注入: Depends(get_db)"""
    async with AsyncSessionLocal() as session:
        yield session
