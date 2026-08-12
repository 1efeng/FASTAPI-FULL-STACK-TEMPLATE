import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.chat.executor import AgentExecutionError, AgentExecutor
from app.modules.chat.runtime import (
    ChatAdmissionLease,
    ChatAdmissionRejected,
    ChatRuntime,
)
from app.modules.chat.schema import AgentChatResponse
from app.modules.conversation.model import Message, MessageRole
from app.modules.conversation.repository import ConversationRepository
from app.modules.request_run.model import RequestRun, RequestRunStatus
from app.modules.request_run.repository import RequestRunRepository

ChatErrorCode = Literal[
    "CONVERSATION_NOT_FOUND",
    "DUPLICATE_REQUEST",
    "RATE_LIMITED",
    "QUOTA_EXCEEDED",
    "CONCURRENCY_LIMITED",
    "REQUEST_CANCELLED",
    "REQUEST_DEADLINE_EXCEEDED",
    "AGENT_LOOP_LIMIT_REACHED",
    "MODEL_CALL_LIMIT_REACHED",
    "MODEL_TIMEOUT",
    "MODEL_RATE_LIMITED",
    "MODEL_UNAVAILABLE",
    "INTERNAL_ERROR",
]


@dataclass(slots=True)
class ChatExecutionError(Exception):
    code: ChatErrorCode
    message: str
    retryable: bool
    status_code: int
    request_id: uuid.UUID | None = None


def remaining_seconds(
    deadline_at: datetime,
    *,
    now: datetime | None = None,
) -> float:
    current = now or datetime.now(UTC)
    return max(0.0, (deadline_at - current).total_seconds())


class RequestTerminalTransitionError(RuntimeError):
    pass


# AgentExecutionError → Product error contract 映射。错误文案不泄露 provider 细节。
_EXECUTOR_ERROR_MAP: dict[str, tuple[str, bool, int]] = {
    "AGENT_LOOP_LIMIT_REACHED": (
        "规划步骤超过安全上限，请简化问题后重试。",
        False,
        422,
    ),
    "MODEL_CALL_LIMIT_REACHED": (
        "模型调用次数超过安全上限，请简化问题后重试。",
        False,
        422,
    ),
    "MODEL_TIMEOUT": ("模型响应超时，请稍后重试。", True, 504),
    "MODEL_RATE_LIMITED": ("当前规划服务繁忙，请稍后重试。", True, 429),
    "MODEL_UNAVAILABLE": ("当前规划服务暂时不可用，请稍后重试。", True, 503),
}


class ChatService:
    """Product-owned chat orchestration.

    Product Runtime 拥有 Request lifecycle（幂等 / 持久化 / deadline / cancel /
    error contract）；Agent Framework 只能通过 AgentExecutor 被调用。
    """

    def __init__(
        self,
        db: AsyncSession,
        executor: AgentExecutor,
        runtime: ChatRuntime | None = None,
    ) -> None:
        self.db = db
        self.executor = executor
        self.runtime = runtime
        self.conversation_repo = ConversationRepository(db)
        self.request_run_repo = RequestRunRepository(db)

    async def _replay_existing(
        self,
        request_run: RequestRun,
        *,
        conversation_id: uuid.UUID,
        message: str,
    ) -> AgentChatResponse:
        user_message = await self.request_run_repo.get_message(
            request_run.id,
            MessageRole.USER,
        )
        if (
            request_run.conversation_id != conversation_id
            or user_message is None
            or user_message.content != message
        ):
            raise ChatExecutionError(
                code="DUPLICATE_REQUEST",
                message="该幂等键已用于其他请求。",
                retryable=False,
                status_code=409,
                request_id=request_run.id,
            )

        content: str | None = None
        if request_run.status is RequestRunStatus.COMPLETED:
            assistant_message = await self.request_run_repo.get_message(
                request_run.id,
                MessageRole.ASSISTANT,
            )
            if assistant_message is None:
                raise ChatExecutionError(
                    code="INTERNAL_ERROR",
                    message="请求结果暂时不可用，请稍后重试。",
                    retryable=True,
                    status_code=500,
                    request_id=request_run.id,
                )
            content = assistant_message.content

        return AgentChatResponse(
            request_id=request_run.id,
            content=content,
            status=request_run.status,
            error_code=request_run.error_code,
            replayed=True,
        )

    async def _persist_request_start(
        self,
        *,
        request_id: uuid.UUID,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        idempotency_key: str,
        message: str,
    ) -> datetime:
        started_at = datetime.now(UTC)
        deadline_at = started_at + timedelta(seconds=settings.REQUEST_DEADLINE_SECONDS)
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
                deadline_at=deadline_at,
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
            return deadline_at
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
        except RequestTerminalTransitionError as exc:
            await self.db.rollback()
            request_run = await self.request_run_repo.get_by_id(request_id)
            if (
                request_run is not None
                and request_run.status is RequestRunStatus.CANCELLED
            ):
                raise ChatExecutionError(
                    code="REQUEST_CANCELLED",
                    message="请求已取消。",
                    retryable=False,
                    status_code=409,
                    request_id=request_id,
                ) from exc
            raise
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

    @staticmethod
    async def _wait_for_disconnect(
        checker: Callable[[], Awaitable[bool]],
    ) -> None:
        while True:
            if await checker():
                return
            await asyncio.sleep(0.25)

    async def _execute_agent(
        self,
        *,
        request_id: uuid.UUID,
        conversation_id: uuid.UUID,
        deadline_at: datetime,
        message: str,
        disconnect_checker: Callable[[], Awaitable[bool]] | None,
    ) -> str:
        execute_task = asyncio.create_task(
            self.executor.execute(
                request_id=request_id,
                conversation_id=conversation_id,
                message=message,
                deadline_at=deadline_at,
            )
        )
        watchers: list[asyncio.Task[None]] = []
        if self.runtime is not None:
            watchers.append(
                asyncio.create_task(self.runtime.wait_for_cancel(request_id))
            )
        if disconnect_checker is not None:
            watchers.append(
                asyncio.create_task(self._wait_for_disconnect(disconnect_checker))
            )

        try:
            timeout = remaining_seconds(deadline_at)
            if timeout <= 0:
                raise TimeoutError
            async with asyncio.timeout(timeout):
                if watchers:
                    done, _ = await asyncio.wait(
                        [execute_task, *watchers],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if execute_task not in done:
                        execute_task.cancel()
                        await asyncio.gather(execute_task, return_exceptions=True)
                        raise ChatExecutionError(
                            code="REQUEST_CANCELLED",
                            message="请求已取消。",
                            retryable=False,
                            status_code=409,
                            request_id=request_id,
                        )
                result = await execute_task
        except TimeoutError as exc:
            raise ChatExecutionError(
                code="REQUEST_DEADLINE_EXCEEDED",
                message="请求处理超时，请稍后重试。",
                retryable=True,
                status_code=504,
                request_id=request_id,
            ) from exc
        except AgentExecutionError as exc:
            message_text, retryable, status_code = _EXECUTOR_ERROR_MAP[exc.code]
            raise ChatExecutionError(
                code=exc.code,
                message=message_text,
                retryable=retryable,
                status_code=status_code,
                request_id=request_id,
            ) from exc
        finally:
            if not execute_task.done():
                execute_task.cancel()
            for watcher in watchers:
                watcher.cancel()
            await asyncio.gather(execute_task, *watchers, return_exceptions=True)

        content = result.content
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
        client_ip: str = "unknown",
        disconnect_checker: Callable[[], Awaitable[bool]] | None = None,
    ) -> AgentChatResponse:
        existing = await self.request_run_repo.get_by_user_idempotency(
            user_id,
            idempotency_key,
        )
        if existing is not None:
            return await self._replay_existing(
                existing,
                conversation_id=conversation_id,
                message=message,
            )

        lease = ChatAdmissionLease()
        if self.runtime is not None:
            try:
                lease = await self.runtime.admit(
                    client_ip=client_ip,
                    user_id=user_id,
                )
            except ChatAdmissionRejected as exc:
                raise ChatExecutionError(
                    code=exc.code,
                    message=exc.message,
                    retryable=exc.retryable,
                    status_code=503 if exc.code == "INTERNAL_ERROR" else 429,
                    request_id=request_id,
                ) from exc

        started = False
        try:
            try:
                deadline_at = await self._persist_request_start(
                    request_id=request_id,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    idempotency_key=idempotency_key,
                    message=message,
                )
                started = True
            except IntegrityError as exc:
                existing = await self.request_run_repo.get_by_user_idempotency(
                    user_id,
                    idempotency_key,
                )
                if existing is not None:
                    return await self._replay_existing(
                        existing,
                        conversation_id=conversation_id,
                        message=message,
                    )
                running = await self.request_run_repo.get_running_for_conversation(
                    conversation_id
                )
                if running is not None:
                    raise ChatExecutionError(
                        code="CONCURRENCY_LIMITED",
                        message="该会话已有请求正在运行，请稍后重试。",
                        retryable=True,
                        status_code=429,
                        request_id=request_id,
                    ) from exc
                raise

            try:
                content = await self._execute_agent(
                    request_id=request_id,
                    conversation_id=conversation_id,
                    deadline_at=deadline_at,
                    message=message,
                    disconnect_checker=disconnect_checker,
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
                terminal_status = (
                    RequestRunStatus.CANCELLED
                    if exc.code == "REQUEST_CANCELLED"
                    else RequestRunStatus.FAILED
                )
                await self._persist_request_terminal(
                    request_id=request_id,
                    status=terminal_status,
                    error_code=None
                    if terminal_status is RequestRunStatus.CANCELLED
                    else exc.code,
                )
                raise
            except Exception:
                await self._persist_request_terminal(
                    request_id=request_id,
                    status=RequestRunStatus.FAILED,
                    error_code="INTERNAL_ERROR",
                )
                raise

            return AgentChatResponse(
                request_id=request_id,
                content=content,
                status=RequestRunStatus.COMPLETED,
            )
        finally:
            if self.runtime is not None:
                await self.runtime.release(lease)
                if started:
                    await self.runtime.finish_request(request_id)
