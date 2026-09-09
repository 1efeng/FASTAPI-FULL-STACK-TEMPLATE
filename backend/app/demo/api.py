import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.deps import CurrentUser, SessionDep
from app.core.response import Message
from app.demo.model import Demo
from app.demo.schema import DemoCreate, DemoPublic, DemosPublic, DemoUpdate
from app.demo.service import DemoService

router = APIRouter(prefix="/demos", tags=["demos"])
SkipParam = Annotated[int, Query(ge=0)]
LimitParam = Annotated[int, Query(ge=1, le=100)]


def get_demo_service(db: SessionDep) -> DemoService:
    return DemoService(db)


@router.get("/", response_model=DemosPublic)
async def read_demos(
    current_user: CurrentUser,
    skip: SkipParam = 0,
    limit: LimitParam = 100,
    svc: DemoService = Depends(get_demo_service),
) -> DemosPublic:
    demos, count = await svc.list_demos(
        current_user=current_user,
        skip=skip,
        limit=limit,
    )
    return DemosPublic(
        data=[DemoPublic.model_validate(demo) for demo in demos],
        count=count,
    )


@router.post("/", response_model=DemoPublic, status_code=status.HTTP_201_CREATED)
async def create_demo(
    demo_in: DemoCreate,
    current_user: CurrentUser,
    svc: DemoService = Depends(get_demo_service),
) -> Demo:
    return await svc.create_demo(demo_in, current_user)


@router.get("/{demo_id}", response_model=DemoPublic)
async def read_demo(
    demo_id: uuid.UUID,
    current_user: CurrentUser,
    svc: DemoService = Depends(get_demo_service),
) -> Demo:
    return await svc.get_demo(demo_id, current_user)


@router.patch("/{demo_id}", response_model=DemoPublic)
async def update_demo(
    demo_id: uuid.UUID,
    demo_in: DemoUpdate,
    current_user: CurrentUser,
    svc: DemoService = Depends(get_demo_service),
) -> Demo:
    return await svc.update_demo(demo_id, demo_in, current_user)


@router.delete("/{demo_id}", response_model=Message)
async def delete_demo(
    demo_id: uuid.UUID,
    current_user: CurrentUser,
    svc: DemoService = Depends(get_demo_service),
) -> Message:
    await svc.delete_demo(demo_id, current_user)
    return Message(message="Demo deleted successfully")
