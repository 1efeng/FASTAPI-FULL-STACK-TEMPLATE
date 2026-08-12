import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.deps import CurrentUser, SessionDep
from app.modules.chat.executor import AgentRuntimeNotConfigured, get_agent_executor
from app.modules.chat.runtime import ChatRuntime, get_chat_runtime
from app.modules.chat.schema import AgentChatError, AgentChatRequest, AgentChatResponse
from app.modules.chat.service import ChatExecutionError, ChatService
from app.modules.request_run.model import RequestRunStatus

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])

ChatRuntimeDep = Annotated[ChatRuntime, Depends(get_chat_runtime)]


def get_chat_service(db: SessionDep, runtime: ChatRuntimeDep) -> ChatService:
    try:
        executor = get_agent_executor()
    except AgentRuntimeNotConfigured as exc:
        raise HTTPException(
            status_code=503,
            detail="Agent runtime is not configured in the v8 clean baseline.",
        ) from exc
    return ChatService(db, executor=executor, runtime=runtime)


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
        202: {"model": AgentChatResponse},
        404: {"model": AgentChatError},
        409: {"model": AgentChatError},
        422: {"model": AgentChatError},
        429: {"model": AgentChatError},
        500: {"model": AgentChatError},
        503: {"model": AgentChatError},
        504: {"model": AgentChatError},
    },
)
async def chat(
    request: Request,
    payload: AgentChatRequest,
    current_user: CurrentUser,
    service: ChatServiceDep,
    idempotency_key: IdempotencyKey,
) -> AgentChatResponse | JSONResponse:
    """Run one authenticated, non-streaming chat request through AgentExecutor."""
    request_id = uuid.uuid4()
    try:
        result = await service.chat(
            request_id=request_id,
            user_id=current_user.id,
            conversation_id=payload.conversation_id,
            idempotency_key=idempotency_key.strip(),
            message=payload.message,
            client_ip=request.client.host if request.client else "unknown",
            disconnect_checker=None,
        )
        if result.status is RequestRunStatus.RUNNING:
            return JSONResponse(
                status_code=202,
                content=result.model_dump(mode="json"),
            )
        return result
    except ChatExecutionError as exc:
        response_request_id = exc.request_id or request_id
        logger.warning(
            "Agent chat failed: %s",
            exc.code,
            extra={"request_id": str(response_request_id)},
        )
        error = AgentChatError(
            code=exc.code,
            message=exc.message,
            retryable=exc.retryable,
            request_id=response_request_id,
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
