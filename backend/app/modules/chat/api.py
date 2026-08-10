import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.core.deps import CurrentUser
from app.modules.chat.schema import AgentChatError, AgentChatRequest, AgentChatResponse
from app.modules.chat.service import ChatExecutionError, ChatService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


def get_chat_service() -> ChatService:
    return ChatService()


ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]


@router.post(
    "/chat",
    response_model=AgentChatResponse,
    responses={
        422: {"model": AgentChatError},
        429: {"model": AgentChatError},
        500: {"model": AgentChatError},
        503: {"model": AgentChatError},
        504: {"model": AgentChatError},
    },
)
async def chat(
    payload: AgentChatRequest,
    _current_user: CurrentUser,
    service: ChatServiceDep,
) -> AgentChatResponse | JSONResponse:
    """Run one authenticated, non-streaming Travel Agent request."""
    request_id = uuid.uuid4()
    try:
        return await service.chat(request_id=request_id, message=payload.message)
    except ChatExecutionError as exc:
        logger.warning(
            "Agent chat failed: %s",
            exc.code,
            extra={"request_id": str(request_id)},
        )
        error = AgentChatError(
            code=exc.code,
            message=exc.message,
            retryable=exc.retryable,
            request_id=request_id,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=error.model_dump(mode="json"),
        )
    except Exception:
        logger.exception(
            "Unexpected agent chat failure",
            extra={"request_id": str(request_id)},
        )
        error = AgentChatError(
            code="INTERNAL_ERROR",
            message="请求处理失败，请稍后重试。",
            retryable=True,
            request_id=request_id,
        )
        return JSONResponse(status_code=500, content=error.model_dump(mode="json"))
