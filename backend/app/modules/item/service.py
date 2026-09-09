import uuid

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.item.model import Item
from app.modules.item.repository import ItemRepository
from app.modules.item.schema import ItemCreate, ItemUpdate
from app.modules.user.model import User


class ItemService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ItemRepository(Item, db)

    async def list_items(
        self, skip: int, limit: int, is_superuser: bool, user_id: uuid.UUID
    ) -> tuple[list[Item], int]:
        """分页查询 items,普通用户只能看自己的,超管看全部"""
        if is_superuser:
            count_statement = select(func.count()).select_from(Item)
            statement = (
                select(Item).order_by(Item.created_at.desc()).offset(skip).limit(limit)
            )
        else:
            count_statement = (
                select(func.count()).select_from(Item).where(Item.owner_id == user_id)
            )
            statement = (
                select(Item)
                .where(Item.owner_id == user_id)
                .order_by(Item.created_at.desc())
                .offset(skip)
                .limit(limit)
            )
        count = (await self.db.execute(count_statement)).scalar_one()
        items = (await self.db.execute(statement)).scalars().all()
        return list(items), count

    async def get_item_by_id(self, item_id: uuid.UUID, current_user: User) -> Item:
        """读取指定 item,普通用户只能看自己的,超管看任意;不存在 404,无权限 403"""
        item = await self.repo.get_by_id(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Item not found")
        if not current_user.is_superuser and (item.owner_id != current_user.id):
            raise HTTPException(status_code=403, detail="Not enough permissions")
        return item

    async def create_item(self, item_in: ItemCreate, owner_id: uuid.UUID) -> Item:
        item = Item(
            title=item_in.title,
            description=item_in.description,
            owner_id=owner_id,
        )
        item = await self.repo.create(item)
        await self.db.commit()
        return item

    async def update_item(self, item: Item, item_in: ItemUpdate) -> Item:
        update_dict = item_in.model_dump(exclude_unset=True)
        for field, value in update_dict.items():
            setattr(item, field, value)
        updated = await self.repo.update(item)
        await self.db.commit()
        return updated

    async def update_item_by_id(
        self, item_id: uuid.UUID, item_in: ItemUpdate, current_user: User
    ) -> Item:
        item = await self.get_item_by_id(item_id, current_user)
        return await self.update_item(item, item_in)

    async def delete_item(self, item: Item) -> None:
        await self.repo.delete(item)
        await self.db.commit()

    async def delete_item_by_id(self, item_id: uuid.UUID, current_user: User) -> None:
        item = await self.get_item_by_id(item_id, current_user)
        await self.delete_item(item)
