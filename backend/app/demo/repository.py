import uuid

from sqlalchemy import func, select

from app.db.repository import BaseRepository
from app.demo.model import Demo


class DemoRepository(BaseRepository[Demo]):
    """Demo 数据访问；只查询/写入，不负责 commit。"""

    async def list_for_user(
        self,
        *,
        owner_id: uuid.UUID,
        is_superuser: bool,
        skip: int,
        limit: int,
    ) -> tuple[list[Demo], int]:
        count_statement = select(func.count()).select_from(Demo)
        statement = select(Demo)

        if not is_superuser:
            condition = Demo.owner_id == owner_id
            count_statement = count_statement.where(condition)
            statement = statement.where(condition)

        statement = (
            statement.order_by(Demo.created_at.desc()).offset(skip).limit(limit)
        )
        count = (await self.db.execute(count_statement)).scalar_one()
        demos = (await self.db.execute(statement)).scalars().all()
        return list(demos), count
