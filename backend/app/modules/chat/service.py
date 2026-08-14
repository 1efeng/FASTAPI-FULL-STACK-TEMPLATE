import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.context.deadline import remaining_deadline_seconds
from app.agent.executor import (
    AgentExecutionError,
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentExecutor,
    AgentMessage,
    AgentStreamTerminalKind,
    stream_vercel_events,
)
from app.core.config import settings
from app.infra.stream_resume import StreamFactory
from app.modules.chat import streaming as sse
from app.modules.chat.execution import (
    ExecutionSupervisor,
    get_execution_supervisor,
)
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


class RequestTerminalTransitionError(RuntimeError):
    pass


class _StreamingCancellation(Exception):
    """Internal signal used to gate a Product cancellation terminal."""


class _StreamingDeadlineExceeded(Exception):
    """Internal signal used to gate a streaming deadline terminal."""


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
        supervisor: ExecutionSupervisor | None = None,
    ) -> None:
        self.db = db
        self.executor = executor
        self.runtime = runtime
        self.supervisor = supervisor or get_execution_supervisor()
        self.conversation_repo = ConversationRepository(db)
        self.request_run_repo = RequestRunRepository(db)

    async def assert_conversation_available(
        self,
        *,
        conversation_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        """Fail before opening an SSE response when the conversation is not owned.

        The streaming producer is intentionally started in the background by
        ``StreamResumeStore``.  Deferring this check until the producer runs
        means FastAPI has already sent ``200 text/event-stream``; a subsequent
        ``CONVERSATION_NOT_FOUND`` then looks like a browser ``network error``.
        Keep the check in Product Runtime and retain the identical check in the
        start transaction as the race-safe final guard.
        """
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
        reasoning_summary: str | None = None,
        reasoning_duration_ms: int | None = None,
    ) -> None:
        finished_at = datetime.now(UTC)
        try:
            assistant_message = Message(
                conversation_id=conversation_id,
                request_id=request_id,
                role=MessageRole.ASSISTANT,
                content=content,
                reasoning_summary=reasoning_summary,
                reasoning_duration_ms=reasoning_duration_ms,
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


    async def _project_history(
        self,
        *,
        conversation_id: uuid.UUID,
        current_request_id: uuid.UUID,
    ) -> tuple[AgentMessage, ...]:
        """Project durable product history *before* the current request.

        Excludes the current request's user message (P0-4): Product lifecycle
        already INSERTs the current user message before execution, so including it
        here would send the current turn twice. Tool scratchpad / private reasoning
        / system prompt are never durable Message rows, so they cannot appear.
        """
        messages = await self.conversation_repo.list_messages(conversation_id)
        return tuple(
            AgentMessage(role=message.role.value, content=message.content)
            for message in messages
            if message.request_id != current_request_id
        )

    async def _execute_agent(
        self,
        *,
        request_id: uuid.UUID,
        conversation_id: uuid.UUID,
        deadline_at: datetime,
        message: str,
        history: tuple[AgentMessage, ...],
    ) -> AgentExecutionResult:
        execute_task = self.supervisor.start(
            request_id,
            self.executor.execute(
                AgentExecutionRequest(
                    request_id=request_id,
                    conversation_id=conversation_id,
                    message=message,
                    history=history,
                    deadline_at=deadline_at,
                )
            )
        )
        watchers: list[asyncio.Task[None]] = []
        if self.runtime is not None:
            watchers.append(
                asyncio.create_task(self.runtime.wait_for_cancel(request_id))
            )
        result: AgentExecutionResult | None = None
        try:
            timeout = remaining_deadline_seconds(deadline_at)
            if timeout <= 0:
                raise TimeoutError
            async with asyncio.timeout(timeout):
                if watchers:
                    done, _ = await asyncio.wait(
                        [execute_task, *watchers],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if execute_task not in done:
                        self.supervisor.request_cancel(request_id)
                        await asyncio.gather(execute_task, return_exceptions=True)
                        raise ChatExecutionError(
                            code="REQUEST_CANCELLED",
                            message="请求已取消。",
                            retryable=False,
                            status_code=409,
                            request_id=request_id,
                        )
                    if execute_task.cancelled() and any(
                        watcher in done for watcher in watchers
                    ):
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

        assert result is not None
        if not result.content:
            raise RuntimeError("Agent returned an empty final message")
        return result

    async def chat(
        self,
        *,
        request_id: uuid.UUID,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        idempotency_key: str,
        message: str,
        client_ip: str = "unknown",
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
                history = await self._project_history(
                    conversation_id=conversation_id,
                    current_request_id=request_id,
                )
                result = await self._execute_agent(
                    request_id=request_id,
                    conversation_id=conversation_id,
                    deadline_at=deadline_at,
                    message=message,
                    history=history,
                )
                await self._persist_request_success(
                    request_id=request_id,
                    conversation_id=conversation_id,
                    content=result.content,
                    reasoning_summary=result.reasoning_summary,
                    reasoning_duration_ms=result.reasoning_duration_ms,
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
                content=result.content,
                status=RequestRunStatus.COMPLETED,
            )
        finally:
            if self.runtime is not None:
                await self.runtime.release(lease)
                if started:
                    await self.runtime.finish_request(request_id)

    async def stream_factory(
        self,
        *,
        request_id: uuid.UUID,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        idempotency_key: str,
        message: str,
        client_ip: str = "unknown",
    ) -> StreamFactory:
        """Build the stream producer for one Product chat request.

        Product lifecycle (admission → idempotency → Start TX → history) runs when
        the returned factory is first iterated (inside StreamResumeStore's producer
        task). Text deltas stream live; the ``finish`` terminal is emitted only
        after ``_persist_request_success`` COMMITs (P0-5 terminal gate).
        """

        async def producer() -> AsyncIterator[str]:

            # Admission
            lease = ChatAdmissionLease()
            started = False
            if self.runtime is not None:
                try:
                    lease = await self.runtime.admit(
                        client_ip=client_ip, user_id=user_id
                    )
                except ChatAdmissionRejected as exc:
                    raise ChatExecutionError(
                        code=exc.code,
                        message=exc.message,
                        retryable=exc.retryable,
                        status_code=503 if exc.code == "INTERNAL_ERROR" else 429,
                        request_id=request_id,
                    ) from exc

            try:
                # Idempotency
                existing = await self.request_run_repo.get_by_user_idempotency(
                    user_id, idempotency_key
                )
                if existing is not None and existing.status is RequestRunStatus.COMPLETED:
                    # Replay the durable final as a single finished stream.
                    yield sse.start_part(str(existing.id))
                    text_id = uuid.uuid4().hex
                    assistant = await self.request_run_repo.get_message(
                        existing.id, MessageRole.ASSISTANT
                    )
                    content = assistant.content if assistant else ""
                    if assistant and assistant.reasoning_summary:
                        reasoning_id = uuid.uuid4().hex
                        yield sse.reasoning_start_part(reasoning_id)
                        yield sse.reasoning_delta_part(
                            reasoning_id, assistant.reasoning_summary
                        )
                        yield sse.reasoning_end_part(reasoning_id)
                    yield sse.text_start_part(text_id)
                    yield sse.text_delta_part(text_id, content)
                    yield sse.text_end_part(text_id)
                    yield sse.finish_part()
                    yield sse.done_marker()
                    return

                # Start TX
                try:
                    deadline_at = await self._persist_request_start(
                        request_id=request_id,
                        user_id=user_id,
                        conversation_id=conversation_id,
                        idempotency_key=idempotency_key,
                        message=message,
                    )
                    started = True
                except IntegrityError:
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
                        )
                    raise

                history = await self._project_history(
                    conversation_id=conversation_id,
                    current_request_id=request_id,
                )

                # Terminal gate: COMMIT the durable assistant final *before* the
                # adapter emits its finish chunk (on_complete runs upstream of
                # after_stream's FinishChunk in VercelAIAdapter.transform_stream).
                async def commit_final(result: AgentExecutionResult) -> None:
                    await self._persist_request_success(
                        request_id=request_id,
                        conversation_id=conversation_id,
                        content=result.content,
                        reasoning_summary=result.reasoning_summary,
                        reasoning_duration_ms=result.reasoning_duration_ms,
                    )

                async def commit_stream_terminal(
                    kind: AgentStreamTerminalKind,
                    _reason: str | None,
                ) -> str:
                    if kind == "abort":
                        await self._persist_request_terminal(
                            request_id=request_id,
                            status=RequestRunStatus.CANCELLED,
                            error_code=None,
                        )
                        return sse.abort_part("请求已取消。")

                    await self._persist_request_terminal(
                        request_id=request_id,
                        status=RequestRunStatus.FAILED,
                        error_code="INTERNAL_ERROR",
                    )
                    return sse.error_part("请求处理失败，请稍后重试。")

                # The supervisor owns the Agent/adapter execution. The
                # StreamResumeStore producer only drains this channel and may
                # be detached/re-attached independently of the execution task.
                events: asyncio.Queue[str | BaseException | None] = asyncio.Queue()

                async def run_execution() -> None:
                    try:
                        timeout = remaining_deadline_seconds(deadline_at)
                        if timeout <= 0:
                            raise _StreamingDeadlineExceeded
                        async with asyncio.timeout(timeout):
                            async for chunk in stream_vercel_events(
                                AgentExecutionRequest(
                                    request_id=request_id,
                                    conversation_id=conversation_id,
                                    message=message,
                                    history=history,
                                    deadline_at=deadline_at,
                                ),
                                on_complete=commit_final,
                                on_terminal=commit_stream_terminal,
                            ):
                                await events.put(chunk)
                    except asyncio.CancelledError:
                        if self.supervisor.cancellation_requested(request_id):
                            await events.put(_StreamingCancellation())
                        else:
                            raise
                    except TimeoutError:
                        await events.put(_StreamingDeadlineExceeded())
                    except BaseException as exc:
                        await events.put(exc)
                    finally:
                        await events.put(None)

                execution_task = self.supervisor.start(request_id, run_execution())
                try:
                    while True:
                        chunk = await events.get()
                        if chunk is None:
                            break
                        if isinstance(chunk, BaseException):
                            if isinstance(chunk, _StreamingCancellation) or self.supervisor.cancellation_requested(
                                request_id
                            ):
                                await self._persist_request_terminal(
                                    request_id=request_id,
                                    status=RequestRunStatus.CANCELLED,
                                    error_code=None,
                                )
                                yield sse.abort_part("请求已取消。")
                            elif isinstance(chunk, _StreamingDeadlineExceeded):
                                await self._persist_request_terminal(
                                    request_id=request_id,
                                    status=RequestRunStatus.FAILED,
                                    error_code="REQUEST_DEADLINE_EXCEEDED",
                                )
                                yield sse.error_part("请求处理超时，请稍后重试。")
                            else:
                                await self._persist_request_terminal(
                                    request_id=request_id,
                                    status=RequestRunStatus.FAILED,
                                    error_code="INTERNAL_ERROR",
                                )
                                yield sse.error_part("请求处理失败，请稍后重试。")
                            yield sse.done_marker()
                            break
                        yield chunk
                    await execution_task
                except Exception:
                    if not self.supervisor.cancellation_requested(request_id):
                        await self._persist_request_terminal(
                            request_id=request_id,
                            status=RequestRunStatus.FAILED,
                            error_code="INTERNAL_ERROR",
                        )
                    raise
            finally:
                if self.runtime is not None:
                    await self.runtime.release(lease)
                    if started:
                        await self.runtime.finish_request(request_id)

        return producer
