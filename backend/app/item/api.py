import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.core.deps import CurrentUser, SessionDep
from app.core.response import Message
from app.item.schema import ItemCreate, ItemPublic, ItemsPublic, ItemUpdate
from app.item.service import ItemService

router = APIRouter(prefix="/items", tags=["items"])
SkipParam = Annotated[int, Query(ge=0)]
LimitParam = Annotated[int, Query(ge=1, le=100)]


def get_item_service(db: SessionDep) -> ItemService:
    return ItemService(db)


@router.get("/", response_model=ItemsPublic)
async def read_items(
    current_user: CurrentUser,
    skip: SkipParam = 0,
    limit: LimitParam = 100,
    svc: ItemService = Depends(get_item_service),
) -> Any:
    """Retrieve items."""
    items, count = await svc.list_items(
        skip=skip,
        limit=limit,
        is_superuser=current_user.is_superuser,
        user_id=current_user.id,
    )
    items_public = [ItemPublic.model_validate(item) for item in items]
    return ItemsPublic(data=items_public, count=count)


@router.get("/{id}", response_model=ItemPublic)
async def read_item(
    current_user: CurrentUser,
    id: uuid.UUID,
    svc: ItemService = Depends(get_item_service),
) -> Any:
    """Get item by ID."""
    return await svc.get_item_by_id(id, current_user)


@router.post("/", response_model=ItemPublic)
async def create_item(
    *,
    current_user: CurrentUser,
    item_in: ItemCreate,
    svc: ItemService = Depends(get_item_service),
) -> Any:
    """Create new item."""
    return await svc.create_item(item_in, owner_id=current_user.id)


@router.put("/{id}", response_model=ItemPublic)
async def update_item(
    *,
    current_user: CurrentUser,
    id: uuid.UUID,
    item_in: ItemUpdate,
    svc: ItemService = Depends(get_item_service),
) -> Any:
    """Update an item."""
    return await svc.update_item_by_id(id, item_in, current_user)


@router.delete("/{id}")
async def delete_item(
    current_user: CurrentUser,
    id: uuid.UUID,
    svc: ItemService = Depends(get_item_service),
) -> Message:
    """Delete an item."""
    await svc.delete_item_by_id(id, current_user)
    return Message(message="Item deleted successfully")
