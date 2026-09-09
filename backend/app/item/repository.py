import uuid

from sqlalchemy import func, select

from app.common.repository import BaseRepository
from app.item.model import Item


class ItemRepository(BaseRepository[Item]):
    """Item 数据访问；只查询/写入，不负责 commit。"""

    async def list_for_user(
        self,
        *,
        owner_id: uuid.UUID,
        is_superuser: bool,
        skip: int,
        limit: int,
    ) -> tuple[list[Item], int]:
        count_statement = select(func.count()).select_from(Item)
        statement = select(Item)

        if not is_superuser:
            condition = Item.owner_id == owner_id
            count_statement = count_statement.where(condition)
            statement = statement.where(condition)

        statement = (
            statement.order_by(Item.created_at.desc()).offset(skip).limit(limit)
        )
        count = (await self.db.execute(count_statement)).scalar_one()
        items = (await self.db.execute(statement)).scalars().all()
        return list(items), count
