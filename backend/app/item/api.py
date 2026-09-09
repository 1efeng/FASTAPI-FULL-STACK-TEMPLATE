import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.deps import CurrentUser, SessionDep
from app.core.response import Message
from app.item.model import Item
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
) -> ItemsPublic:
    items, count = await svc.list_items(
        current_user=current_user,
        skip=skip,
        limit=limit,
    )
    return ItemsPublic(
        data=[ItemPublic.model_validate(item) for item in items],
        count=count,
    )


@router.post("/", response_model=ItemPublic, status_code=status.HTTP_201_CREATED)
async def create_item(
    item_in: ItemCreate,
    current_user: CurrentUser,
    svc: ItemService = Depends(get_item_service),
) -> Item:
    return await svc.create_item(item_in, current_user)


@router.get("/{item_id}", response_model=ItemPublic)
async def read_item(
    item_id: uuid.UUID,
    current_user: CurrentUser,
    svc: ItemService = Depends(get_item_service),
) -> Item:
    return await svc.get_item(item_id, current_user)


@router.patch("/{item_id}", response_model=ItemPublic)
async def update_item(
    item_id: uuid.UUID,
    item_in: ItemUpdate,
    current_user: CurrentUser,
    svc: ItemService = Depends(get_item_service),
) -> Item:
    return await svc.update_item(item_id, item_in, current_user)


@router.delete("/{item_id}", response_model=Message)
async def delete_item(
    item_id: uuid.UUID,
    current_user: CurrentUser,
    svc: ItemService = Depends(get_item_service),
) -> Message:
    await svc.delete_item(item_id, current_user)
    return Message(message="Item deleted successfully")
