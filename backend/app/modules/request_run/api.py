import uuid
from typing import Any

from fastapi import APIRouter, Depends

from app.core.deps import CurrentUser, SessionDep
from app.modules.request_run.schema import RequestRunPublic
from app.modules.request_run.service import RequestRunService

router = APIRouter(prefix="/chat/requests", tags=["chat"])


def get_request_run_service(db: SessionDep) -> RequestRunService:
    return RequestRunService(db)


@router.get("/{request_id}", response_model=RequestRunPublic)
async def read_request_status(
    request_id: uuid.UUID,
    current_user: CurrentUser,
    service: RequestRunService = Depends(get_request_run_service),
) -> Any:
    return await service.get_request_status(request_id, current_user.id)
