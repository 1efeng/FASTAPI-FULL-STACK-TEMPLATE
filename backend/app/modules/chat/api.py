import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse

from app.core.deps import CurrentUser, SessionDep
from app.modules.chat.schema import AgentChatError, AgentChatRequest, AgentChatResponse
from app.modules.chat.service import ChatExecutionError, ChatService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


def get_chat_service(db: SessionDep) -> ChatService:
    return ChatService(db)


ChatServiceDep = Annotated[ChatService, Depends(get_chat_service)]
IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=255,
        pattern=r".*\S.*",
    ),
]


@router.post(
    "/chat",
    response_model=AgentChatResponse,
    responses={
        422: {"model": AgentChatError},
        404: {"model": AgentChatError},
        429: {"model": AgentChatError},
        500: {"model": AgentChatError},
        503: {"model": AgentChatError},
        504: {"model": AgentChatError},
    },
)
async def chat(
    payload: AgentChatRequest,
    current_user: CurrentUser,
    service: ChatServiceDep,
    idempotency_key: IdempotencyKey,
) -> AgentChatResponse | JSONResponse:
    """Run one authenticated, non-streaming Travel Agent request."""
    request_id = uuid.uuid4()
    try:
        return await service.chat(
            request_id=request_id,
            user_id=current_user.id,
            conversation_id=payload.conversation_id,
            idempotency_key=idempotency_key.strip(),
            message=payload.message,
        )
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
