from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.item.model import Item
from app.modules.item.schema import ItemCreate
from app.modules.item.service import ItemService
from tests.utils.user import create_random_user
from tests.utils.utils import random_lower_string


async def create_random_item(db: AsyncSession) -> Item:
    user = await create_random_user(db)
    owner_id = user.id
    assert owner_id is not None
    title = random_lower_string()
    description = random_lower_string()
    item_in = ItemCreate(title=title, description=description)
    svc = ItemService(db)
    return await svc.create_item(item_in, owner_id=owner_id)
