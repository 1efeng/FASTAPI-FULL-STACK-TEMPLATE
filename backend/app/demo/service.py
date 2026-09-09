import uuid

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.demo.model import Demo
from app.demo.repository import DemoRepository
from app.demo.schema import DemoCreate, DemoUpdate
from app.user.model import User


class DemoService:
    """Demo 业务规则与事务边界。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = DemoRepository(Demo, db)

    async def list_demos(
        self, *, current_user: User, skip: int, limit: int
    ) -> tuple[list[Demo], int]:
        return await self.repo.list_for_user(
            owner_id=current_user.id,
            is_superuser=current_user.is_superuser,
            skip=skip,
            limit=limit,
        )

    async def get_demo(self, demo_id: uuid.UUID, current_user: User) -> Demo:
        demo = await self.repo.get_by_id(demo_id)
        if demo is None:
            raise HTTPException(status_code=404, detail="Demo not found")
        if not current_user.is_superuser and demo.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not enough permissions")
        return demo

    async def create_demo(self, demo_in: DemoCreate, current_user: User) -> Demo:
        demo = Demo(
            title=demo_in.title,
            description=demo_in.description,
            owner_id=current_user.id,
        )
        demo = await self.repo.create(demo)
        await self.db.commit()
        return demo

    async def update_demo(
        self,
        demo_id: uuid.UUID,
        demo_in: DemoUpdate,
        current_user: User,
    ) -> Demo:
        demo = await self.get_demo(demo_id, current_user)
        for field, value in demo_in.model_dump(exclude_unset=True).items():
            setattr(demo, field, value)
        demo = await self.repo.update(demo)
        await self.db.commit()
        return demo

    async def delete_demo(self, demo_id: uuid.UUID, current_user: User) -> None:
        demo = await self.get_demo(demo_id, current_user)
        await self.repo.delete(demo)
        await self.db.commit()
