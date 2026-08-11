import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.core.deps import CurrentUser, SessionDep
from app.modules.chat.runtime import ChatRuntime, get_chat_runtime
from app.modules.request_run.schema import RequestRunPublic
from app.modules.request_run.service import RequestRunService

router = APIRouter(prefix="/chat/requests", tags=["chat"])
ChatRuntimeDep = Annotated[ChatRuntime, Depends(get_chat_runtime)]


def get_request_run_service(
    db: SessionDep,
    runtime: ChatRuntimeDep,
) -> RequestRunService:
    return RequestRunService(db, runtime)


@router.get("/{request_id}", response_model=RequestRunPublic)
async def read_request_status(
    request_id: uuid.UUID,
    current_user: CurrentUser,
    service: RequestRunService = Depends(get_request_run_service),
) -> Any:
    return await service.get_request_status(request_id, current_user.id)


@router.post("/{request_id}/cancel", response_model=RequestRunPublic)
async def cancel_request(
    request_id: uuid.UUID,
    current_user: CurrentUser,
    service: RequestRunService = Depends(get_request_run_service),
) -> Any:
    return await service.cancel_request(request_id, current_user.id)
