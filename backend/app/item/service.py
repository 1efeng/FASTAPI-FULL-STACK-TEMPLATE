import uuid

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.item.model import Item
from app.item.repository import ItemRepository
from app.item.schema import ItemCreate, ItemUpdate
from app.user.model import User


class ItemService:
    """Item 业务规则与事务边界。"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ItemRepository(Item, db)

    async def list_items(
        self, *, current_user: User, skip: int, limit: int
    ) -> tuple[list[Item], int]:
        return await self.repo.list_for_user(
            owner_id=current_user.id,
            is_superuser=current_user.is_superuser,
            skip=skip,
            limit=limit,
        )

    async def get_item(self, item_id: uuid.UUID, current_user: User) -> Item:
        item = await self.repo.get_by_id(item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Item not found")
        if not current_user.is_superuser and item.owner_id != current_user.id:
            raise HTTPException(status_code=403, detail="Not enough permissions")
        return item

    async def create_item(self, item_in: ItemCreate, current_user: User) -> Item:
        item = Item(
            title=item_in.title,
            description=item_in.description,
            owner_id=current_user.id,
        )
        item = await self.repo.create(item)
        await self.db.commit()
        return item

    async def update_item(
        self,
        item_id: uuid.UUID,
        item_in: ItemUpdate,
        current_user: User,
    ) -> Item:
        item = await self.get_item(item_id, current_user)
        for field, value in item_in.model_dump(exclude_unset=True).items():
            setattr(item, field, value)
        item = await self.repo.update(item)
        await self.db.commit()
        return item

    async def delete_item(self, item_id: uuid.UUID, current_user: User) -> None:
        item = await self.get_item(item_id, current_user)
        await self.repo.delete(item)
        await self.db.commit()
