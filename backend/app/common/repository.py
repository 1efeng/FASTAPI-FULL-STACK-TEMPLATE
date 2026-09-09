from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base


class BaseRepository[ModelType: Base]:
    """通用仓储，只负责低层数据访问，不提交事务。"""

    def __init__(self, model: type[ModelType], db: AsyncSession):
        self.model = model
        self.db = db

    async def get_by_id(self, id: Any) -> ModelType | None:
        return await self.db.get(self.model, id)

    async def create(self, obj: ModelType) -> ModelType:
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def update(self, obj: ModelType) -> ModelType:
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def delete(self, obj: ModelType) -> None:
        await self.db.delete(obj)
        await self.db.flush()
