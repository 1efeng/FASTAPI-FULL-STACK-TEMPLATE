import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.errors import GraphRecursionError
from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.travel import build_travel_agent
from app.core.config import settings
from app.modules.chat.schema import AgentChatResponse
from app.modules.conversation.model import Message, MessageRole
from app.modules.conversation.repository import ConversationRepository
from app.modules.request_run.model import RequestRun, RequestRunStatus
from app.modules.request_run.repository import RequestRunRepository

ChatErrorCode = Literal[
    "CONVERSATION_NOT_FOUND",
    "REQUEST_DEADLINE_EXCEEDED",
    "AGENT_LOOP_LIMIT_REACHED",
    "MODEL_TIMEOUT",
    "MODEL_RATE_LIMITED",
    "MODEL_UNAVAILABLE",
]


@dataclass(slots=True)
class ChatExecutionError(Exception):
    code: ChatErrorCode
    message: str
    retryable: bool
    status_code: int


def _message_text(message: BaseMessage) -> str:
    if isinstance(message.content, str):
        return message.content.strip()

    parts: list[str] = []
    for block in message.content:
        if isinstance(block, str):
            parts.append(block)
        elif block.get("type") == "text" and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "\n".join(parts).strip()


class RequestTerminalTransitionError(RuntimeError):
    pass


class ChatService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.conversation_repo = ConversationRepository(db)
        self.request_run_repo = RequestRunRepository(db)

    async def _persist_request_start(
        self,
        *,
        request_id: uuid.UUID,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        idempotency_key: str,
        message: str,
    ) -> uuid.UUID:
        started_at = datetime.now(UTC)
        try:
            conversation = await self.conversation_repo.get_owned_active(
                conversation_id, user_id
            )
            if conversation is None:
                raise ChatExecutionError(
                    code="CONVERSATION_NOT_FOUND",
                    message="会话不存在或已删除。",
                    retryable=False,
                    status_code=404,
                )

            request_run = RequestRun(
                id=request_id,
                user_id=user_id,
                conversation_id=conversation.id,
                idempotency_key=idempotency_key,
                status=RequestRunStatus.RUNNING,
                started_at=started_at,
                deadline_at=started_at
                + timedelta(seconds=settings.REQUEST_DEADLINE_SECONDS),
            )
            user_message = Message(
                conversation_id=conversation.id,
                request_id=request_id,
                role=MessageRole.USER,
                content=message,
            )

            await self.request_run_repo.create(request_run)
            await self.conversation_repo.create_message(user_message)
            conversation.last_message_at = started_at
            await self.conversation_repo.update(conversation)
            await self.db.commit()
            return conversation.langgraph_thread_id
        except Exception:
            await self.db.rollback()
            raise

    async def _persist_request_success(
        self,
        *,
        request_id: uuid.UUID,
        conversation_id: uuid.UUID,
        content: str,
    ) -> None:
        finished_at = datetime.now(UTC)
        try:
            assistant_message = Message(
                conversation_id=conversation_id,
                request_id=request_id,
                role=MessageRole.ASSISTANT,
                content=content,
            )
            await self.conversation_repo.create_message(assistant_message)
            transitioned = await self.request_run_repo.transition_from_running(
                request_id,
                status=RequestRunStatus.COMPLETED,
                finished_at=finished_at,
                error_code=None,
            )
            if not transitioned:
                raise RequestTerminalTransitionError("RequestRun is no longer running")

            conversation = await self.conversation_repo.get_by_id(conversation_id)
            if conversation is None:
                raise RuntimeError(
                    "Conversation disappeared during request finalization"
                )
            conversation.last_message_at = finished_at
            await self.conversation_repo.update(conversation)
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise

    async def _persist_request_terminal(
        self,
        *,
        request_id: uuid.UUID,
        status: RequestRunStatus,
        error_code: str | None,
    ) -> bool:
        finished_at = datetime.now(UTC)
        try:
            transitioned = await self.request_run_repo.transition_from_running(
                request_id,
                status=status,
                finished_at=finished_at,
                error_code=error_code,
            )
            if transitioned:
                await self.db.commit()
            else:
                await self.db.rollback()
            return transitioned
        except Exception:
            await self.db.rollback()
            raise

    async def _invoke_agent(
        self,
        *,
        request_id: uuid.UUID,
        conversation_id: uuid.UUID,
        langgraph_thread_id: uuid.UUID,
        message: str,
    ) -> str:
        agent = build_travel_agent(
            request_id=str(request_id),
            metadata={
                "endpoint": "chat",
                "conversation_id": str(conversation_id),
            },
        )

        config: RunnableConfig = {
            "recursion_limit": settings.AGENT_RECURSION_LIMIT,
            "configurable": {"thread_id": str(langgraph_thread_id)},
        }

        try:
            async with asyncio.timeout(settings.REQUEST_DEADLINE_SECONDS):
                result = await agent.ainvoke(
                    {"messages": [{"role": "user", "content": message}]},
                    config=config,
                )
        except TimeoutError as exc:
            raise ChatExecutionError(
                code="REQUEST_DEADLINE_EXCEEDED",
                message="请求处理超时，请稍后重试。",
                retryable=True,
                status_code=504,
            ) from exc
        except GraphRecursionError as exc:
            raise ChatExecutionError(
                code="AGENT_LOOP_LIMIT_REACHED",
                message="规划步骤超过安全上限，请简化问题后重试。",
                retryable=False,
                status_code=422,
            ) from exc
        except APITimeoutError as exc:
            raise ChatExecutionError(
                code="MODEL_TIMEOUT",
                message="模型响应超时，请稍后重试。",
                retryable=True,
                status_code=504,
            ) from exc
        except RateLimitError as exc:
            raise ChatExecutionError(
                code="MODEL_RATE_LIMITED",
                message="当前规划服务繁忙，请稍后重试。",
                retryable=True,
                status_code=429,
            ) from exc
        except (APIConnectionError, APIStatusError) as exc:
            raise ChatExecutionError(
                code="MODEL_UNAVAILABLE",
                message="当前规划服务暂时不可用，请稍后重试。",
                retryable=True,
                status_code=503,
            ) from exc

        messages = result.get("messages")
        if not messages or not isinstance(messages[-1], BaseMessage):
            raise RuntimeError("Agent returned no final message")
        content = _message_text(messages[-1])
        if not content:
            raise RuntimeError("Agent returned an empty final message")
        return content

    async def chat(
        self,
        *,
        request_id: uuid.UUID,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        idempotency_key: str,
        message: str,
    ) -> AgentChatResponse:
        langgraph_thread_id = await self._persist_request_start(
            request_id=request_id,
            user_id=user_id,
            conversation_id=conversation_id,
            idempotency_key=idempotency_key,
            message=message,
        )

        try:
            content = await self._invoke_agent(
                request_id=request_id,
                conversation_id=conversation_id,
                langgraph_thread_id=langgraph_thread_id,
                message=message,
            )
            await self._persist_request_success(
                request_id=request_id,
                conversation_id=conversation_id,
                content=content,
            )
        except asyncio.CancelledError:
            await asyncio.shield(
                self._persist_request_terminal(
                    request_id=request_id,
                    status=RequestRunStatus.CANCELLED,
                    error_code=None,
                )
            )
            raise
        except ChatExecutionError as exc:
            await self._persist_request_terminal(
                request_id=request_id,
                status=RequestRunStatus.FAILED,
                error_code=exc.code,
            )
            raise
        except Exception:
            await self._persist_request_terminal(
                request_id=request_id,
                status=RequestRunStatus.FAILED,
                error_code="INTERNAL_ERROR",
            )
            raise

        return AgentChatResponse(request_id=request_id, content=content)
