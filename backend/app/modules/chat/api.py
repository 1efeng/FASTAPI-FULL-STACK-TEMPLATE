import logging
import re
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from app.agent.executor import (
    AgentRuntimeNotConfigured,
    get_agent_executor,
)
from app.core.deps import CurrentUser, SessionDep
from app.infra.stream_resume.fastapi import sse_response
from app.infra.stream_resume.provider import get_stream_resume_store
from app.modules.chat.runtime import ChatRuntime, get_chat_runtime
from app.modules.chat.schema import AgentChatError, AgentChatRequest, AgentChatResponse
from app.modules.chat.service import ChatExecutionError, ChatService
from app.modules.request_run.model import RequestRunStatus
from app.modules.request_run.repository import RequestRunRepository

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])
_SIMPLE_GREETING_RE = re.compile(
    r"^(?:你好|您好|嗨|哈喽|早上好|下午好|晚上好|早安|晚安|hello|hi|hey)[!！,，。?？\s]*$",
    re.IGNORECASE,
)

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
            enable_web_search=payload.enable_web_search,
            enable_thinking=payload.enable_thinking,
            client_ip=request.client.host if request.client else "unknown",
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


def _extract_user_text(body: dict[str, Any]) -> str:
    """Extract the current user text from an AI SDK ChatRequest body."""
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise HTTPException(status_code=422, detail="messages must not be empty")
    last = messages[-1]
    if not isinstance(last, dict) or last.get("role") != "user":
        raise HTTPException(status_code=422, detail="last message must be user")
    parts = last.get("parts")
    if not isinstance(parts, list):
        raise HTTPException(status_code=422, detail="message parts missing")
    text = "".join(
        part.get("text", "") for part in parts if isinstance(part, dict) and part.get("type") == "text"
    ).strip()
    if not text:
        raise HTTPException(status_code=422, detail="message text must not be empty")
    return text


def _parse_conversation_id(body: dict[str, Any]) -> uuid.UUID | None:
    raw = body.get("conversation_id")
    if raw is None or raw == "":
        return None
    try:
        return uuid.UUID(str(raw))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid conversation_id") from exc


def _parse_bool_field(
    body: dict[str, Any], field: str, default: bool = True
) -> bool:
    raw = body.get(field, default)
    if not isinstance(raw, bool):
        raise HTTPException(status_code=422, detail=f"{field} must be boolean")
    return raw


def _effective_web_search(message: str, requested: bool) -> bool:
    """Avoid loading web-search capabilities for pure greetings."""
    return requested and not _SIMPLE_GREETING_RE.fullmatch(message)


@router.post("/chat/stream")
async def chat_stream(
    request: Request,
    current_user: CurrentUser,
    db: SessionDep,
    runtime: ChatRuntimeDep,
    idempotency_key: IdempotencyKey,
) -> Response:
    """Stream one authenticated chat turn through the Product lifecycle.

    Extracts the current user text from the AI SDK ChatRequest body, runs the
    Product lifecycle (admission → idempotency → Start TX → authoritative history),
    streams PydanticAI text deltas through StreamResumeStore, and emits the
    ``finish`` terminal only after the Product Success TX COMMITs.
    """
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=422, detail="invalid JSON body") from exc

    message = _extract_user_text(body)
    conversation_id = _parse_conversation_id(body)
    enable_web_search = _effective_web_search(
        message,
        _parse_bool_field(body, "enable_web_search"),
    )
    enable_thinking = _parse_bool_field(body, "enable_thinking")

    request_id = uuid.uuid4()
    service = ChatService(db, executor=get_agent_executor(), runtime=runtime)

    try:
        prepared = await service.prepare_turn(
            request_id=request_id,
            user_id=current_user.id,
            conversation_id=conversation_id,
            idempotency_key=idempotency_key.strip(),
            message=message,
            enable_web_search=enable_web_search,
            enable_thinking=enable_thinking,
            client_ip=request.client.host if request.client else "unknown",
        )
        factory = await service.stream_factory(prepared=prepared)
    except ChatExecutionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    store = get_stream_resume_store()
    stream = await store.start_or_resume(str(prepared.request_id), factory)
    if stream is None:
        return JSONResponse(status_code=204, content=None)

    return sse_response(
        stream,
        headers={
            "x-vercel-ai-ui-message-stream": "v1",
            "X-Request-Id": str(prepared.request_id),
            "X-Conversation-Id": str(prepared.conversation_id),
        },
    )


@router.get("/chat/requests/{request_id}/stream")
async def reconnect_stream(
    request_id: uuid.UUID,
    current_user: CurrentUser,
    db: SessionDep,
) -> Response:
    """Reconnect to an active assistant stream (F5 / network resume).

    Ownership check against Product RequestRun; then resume the transport stream
    via StreamResumeStore. Returns 204 when no active transport exists (client
    reconciles via durable status/history).
    """
    request_run = await RequestRunRepository(db).get_owned(request_id, current_user.id)
    if request_run is None:
        raise HTTPException(status_code=404, detail="Request not found")

    store = get_stream_resume_store()
    stream = await store.resume(str(request_id))
    if stream is None:
        return JSONResponse(status_code=204, content=None)
    return sse_response(stream, headers={"x-vercel-ai-ui-message-stream": "v1"})
