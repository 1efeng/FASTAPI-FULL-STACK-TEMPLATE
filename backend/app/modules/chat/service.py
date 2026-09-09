import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.context.deadline import remaining_deadline_seconds
from app.agent.debug_logging import debug_runtime_log
from app.agent.executor import (
    AgentExecutionError,
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentExecutor,
    AgentMessage,
    AgentRunObservation,
    AgentStreamTerminalKind,
    stream_vercel_events,
)
from app.agent.usage import AgentUsage
from app.core.config import settings
from app.infra.database import AsyncSessionLocal
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
from app.modules.conversation.model import Conversation, Message, MessageRole
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


@dataclass(slots=True)
class PreparedTurn:
    """Committed Product state handed to execution and transport layers."""

    request_id: uuid.UUID
    user_id: uuid.UUID
    conversation_id: uuid.UUID
    message: str
    deadline_at: datetime | None
    history: tuple[AgentMessage, ...]
    enable_web_search: bool = True
    enable_thinking: bool = True
    admission_lease: ChatAdmissionLease | None = None
    existing_request: RequestRun | None = None
    replayed_response: AgentChatResponse | None = None


class RequestTerminalTransitionError(RuntimeError):
    pass


async def _finalize_stream_terminal(
    producer_service: ChatService,
    *,
    request_id: uuid.UUID,
    kind: AgentStreamTerminalKind,
    reason: str | None = None,
) -> str:
    """Persist the Product terminal and return the matching UI terminal chunk."""
    if kind == "abort":
        await producer_service._persist_request_terminal(
            request_id=request_id,
            status=RequestRunStatus.CANCELLED,
            error_code=None,
        )
        return sse.abort_part("请求已取消。")

    if reason in _EXECUTOR_ERROR_MAP:
        error_code = reason
        error_message = _EXECUTOR_ERROR_MAP[error_code][0]
    elif reason == "REQUEST_DEADLINE_EXCEEDED":
        error_code = "REQUEST_DEADLINE_EXCEEDED"
        error_message = "请求处理超时，请稍后重试。"
    else:
        error_code = "INTERNAL_ERROR"
        error_message = "请求处理失败，请稍后重试。"
    await producer_service._persist_request_terminal(
        request_id=request_id,
        status=RequestRunStatus.FAILED,
        error_code=error_code,
    )
    return sse.error_part(error_message)


class _StreamingCancellation(Exception):
    """Internal signal used to gate a Product cancellation terminal."""


class _StreamingDeadlineExceeded(Exception):
    """Internal signal used to gate a streaming deadline terminal."""


_TITLE_MAX_CHARS = 30


def _derive_conversation_title(message: str) -> str | None:
    """Derive a conversation title from its first user message."""
    normalized = " ".join(message.split())
    if not normalized:
        return None
    if len(normalized) <= _TITLE_MAX_CHARS:
        return normalized
    return f"{normalized[:_TITLE_MAX_CHARS]}…"


def _request_run_metrics(
    *,
    usage: AgentUsage | None,
    observation: AgentRunObservation | None = None,
    enable_web_search: bool | None,
    enable_thinking: bool | None,
) -> dict[str, int | bool | str]:
    """Map an Agent run's usage into durable RequestRun metric columns.

    Token counters stay ``None`` when the provider did not report usage; unknown
    must never be rewritten as zero (see ``AgentUsage`` contract).
    """
    metrics: dict[str, int | bool | str] = {}
    if usage is not None:
        metrics["model_requests"] = usage.model_requests
        metrics["tool_calls"] = usage.tool_calls
        metrics["research_runs"] = usage.research_runs
        if usage.input_tokens is not None:
            metrics["input_tokens"] = usage.input_tokens
        if usage.output_tokens is not None:
            metrics["output_tokens"] = usage.output_tokens
        if usage.total_tokens is not None:
            metrics["total_tokens"] = usage.total_tokens
        if usage.cache_read_tokens is not None:
            metrics["cache_read_tokens"] = usage.cache_read_tokens
        if usage.cache_write_tokens is not None:
            metrics["cache_write_tokens"] = usage.cache_write_tokens
    if enable_web_search is not None:
        metrics["enable_web_search"] = enable_web_search
    if enable_thinking is not None:
        metrics["enable_thinking"] = enable_thinking
    if observation is not None:
        metrics.update(
            {
                "context_chars": observation.context_chars,
                "output_chars": observation.output_chars,
                "source_url_count": observation.source_url_count,
                "elapsed_ms": observation.elapsed_ms,
                "tool_names": ",".join(observation.tool_names)[:1024],
            }
        )
    return metrics


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


@asynccontextmanager
async def _execution_timeout(deadline_at: datetime) -> AsyncIterator[None]:
    """Enforce the Product RequestRun emergency wall-clock safety cap.

    Normal long-running research is governed by per-model/per-tool timeouts,
    usage limits, and explicit Product cancellation. This outer bound exists only
    to stop runaway/zombie execution and remains Product-owned.
    """
    timeout = remaining_deadline_seconds(deadline_at)
    if timeout <= 0:
        raise TimeoutError
    async with asyncio.timeout(timeout):
        yield


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
        conversation_id: uuid.UUID | None,
        idempotency_key: str,
        message: str,
    ) -> tuple[uuid.UUID, datetime]:
        started_at = datetime.now(UTC)
        deadline_at = started_at + timedelta(seconds=settings.REQUEST_DEADLINE_SECONDS)
        conversation: Conversation | None
        try:
            if conversation_id is None:
                conversation = Conversation(
                    user_id=user_id,
                    title=_derive_conversation_title(message),
                )
                conversation = await self.conversation_repo.create(conversation)
            else:
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
            return conversation.id, deadline_at
        except Exception:
            await self.db.rollback()
            raise

    async def _admit(
        self,
        *,
        request_id: uuid.UUID,
        user_id: uuid.UUID,
        client_ip: str,
    ) -> ChatAdmissionLease:
        if self.runtime is None:
            return ChatAdmissionLease()
        try:
            return await self.runtime.admit(client_ip=client_ip, user_id=user_id)
        except ChatAdmissionRejected as exc:
            raise ChatExecutionError(
                code=exc.code,
                message=exc.message,
                retryable=exc.retryable,
                status_code=503 if exc.code == "INTERNAL_ERROR" else 429,
                request_id=request_id,
            ) from exc

    async def prepare_turn(
        self,
        *,
        request_id: uuid.UUID,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID | None,
        idempotency_key: str,
        message: str,
        enable_web_search: bool = True,
        enable_thinking: bool = True,
        client_ip: str = "unknown",
    ) -> PreparedTurn:
        """Own the Product start gate before any stream transport is opened."""
        existing = await self.request_run_repo.get_by_user_idempotency(
            user_id, idempotency_key
        )
        if existing is not None:
            resolved_conversation_id = conversation_id or existing.conversation_id
            await self.assert_conversation_available(
                conversation_id=resolved_conversation_id,
                user_id=user_id,
            )
            replayed_response = await self._replay_existing(
                existing,
                conversation_id=resolved_conversation_id,
                message=message,
            )
            return PreparedTurn(
                request_id=existing.id,
                user_id=user_id,
                conversation_id=resolved_conversation_id,
                message=message,
                deadline_at=existing.deadline_at,
                history=(),
                enable_web_search=enable_web_search,
                enable_thinking=enable_thinking,
                existing_request=existing,
                replayed_response=replayed_response,
            )

        lease = await self._admit(
            request_id=request_id,
            user_id=user_id,
            client_ip=client_ip,
        )
        try:
            try:
                resolved_conversation_id, deadline_at = await self._persist_request_start(
                    request_id=request_id,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    idempotency_key=idempotency_key,
                    message=message,
                )
            except IntegrityError as exc:
                existing = await self.request_run_repo.get_by_user_idempotency(
                    user_id, idempotency_key
                )
                if existing is not None:
                    resolved_conversation_id = existing.conversation_id
                    replayed_response = await self._replay_existing(
                        existing,
                        conversation_id=resolved_conversation_id,
                        message=message,
                    )
                    if self.runtime is not None:
                        await self.runtime.release(lease)
                    return PreparedTurn(
                        request_id=existing.id,
                        user_id=user_id,
                        conversation_id=resolved_conversation_id,
                        message=message,
                        deadline_at=existing.deadline_at,
                        history=(),
                        enable_web_search=enable_web_search,
                        enable_thinking=enable_thinking,
                        existing_request=existing,
                        replayed_response=replayed_response,
                    )
                if conversation_id is not None:
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

            history = await self._project_history(
                conversation_id=resolved_conversation_id,
                current_request_id=request_id,
            )
            return PreparedTurn(
                request_id=request_id,
                user_id=user_id,
                conversation_id=resolved_conversation_id,
                message=message,
                deadline_at=deadline_at,
                history=history,
                enable_web_search=enable_web_search,
                enable_thinking=enable_thinking,
                admission_lease=lease,
            )
        except Exception:
            if self.runtime is not None:
                await self.runtime.release(lease)
            raise

    async def _finish_prepared_turn(self, turn: PreparedTurn) -> None:
        if self.runtime is not None and turn.admission_lease is not None:
            await self.runtime.release(turn.admission_lease)
            if turn.existing_request is None:
                await self.runtime.finish_request(turn.request_id)

    async def _persist_request_success(
        self,
        *,
        request_id: uuid.UUID,
        conversation_id: uuid.UUID,
        content: str,
        reasoning_summary: str | None = None,
        source_urls: tuple[str, ...] = (),
        usage: AgentUsage | None = None,
        observation: AgentRunObservation | None = None,
        enable_web_search: bool | None = None,
        enable_thinking: bool | None = None,
    ) -> None:
        finished_at = datetime.now(UTC)
        try:
            assistant_message = Message(
                conversation_id=conversation_id,
                request_id=request_id,
                role=MessageRole.ASSISTANT,
                content=content,
                reasoning_summary=reasoning_summary,
                source_urls=list(source_urls),
            )
            await self.conversation_repo.create_message(assistant_message)
            transitioned = await self.request_run_repo.transition_from_running(
                request_id,
                status=RequestRunStatus.COMPLETED,
                finished_at=finished_at,
                error_code=None,
                metrics=_request_run_metrics(
                    usage=usage,
                    observation=observation,
                    enable_web_search=enable_web_search,
                    enable_thinking=enable_thinking,
                ),
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
        enable_web_search: bool,
        enable_thinking: bool,
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
                    enable_web_search=enable_web_search,
                    enable_thinking=enable_thinking,
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
            async with _execution_timeout(deadline_at):
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
        conversation_id: uuid.UUID | None,
        idempotency_key: str,
        message: str,
        enable_web_search: bool = True,
        enable_thinking: bool = True,
        client_ip: str = "unknown",
    ) -> AgentChatResponse:
        turn = await self.prepare_turn(
            request_id=request_id,
            user_id=user_id,
            conversation_id=conversation_id,
            idempotency_key=idempotency_key,
            message=message,
            enable_web_search=enable_web_search,
            enable_thinking=enable_thinking,
            client_ip=client_ip,
        )
        if turn.existing_request is not None:
            assert turn.replayed_response is not None
            return turn.replayed_response

        assert turn.deadline_at is not None
        try:
            try:
                result = await self._execute_agent(
                    request_id=turn.request_id,
                    conversation_id=turn.conversation_id,
                    deadline_at=turn.deadline_at,
                    message=turn.message,
                    history=turn.history,
                    enable_web_search=turn.enable_web_search,
                    enable_thinking=turn.enable_thinking,
                )
                await self._persist_request_success(
                    request_id=turn.request_id,
                    conversation_id=turn.conversation_id,
                    content=result.content,
                    reasoning_summary=result.reasoning_summary,
                    source_urls=result.source_urls,
                    usage=result.usage,
                    observation=result.observation,
                    enable_web_search=turn.enable_web_search,
                    enable_thinking=turn.enable_thinking,
                )
            except asyncio.CancelledError:
                await asyncio.shield(
                    self._persist_request_terminal(
                        request_id=turn.request_id,
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
                    request_id=turn.request_id,
                    status=terminal_status,
                    error_code=None
                    if terminal_status is RequestRunStatus.CANCELLED
                    else exc.code,
                )
                raise
            except Exception:
                await self._persist_request_terminal(
                    request_id=turn.request_id,
                    status=RequestRunStatus.FAILED,
                    error_code="INTERNAL_ERROR",
                )
                raise

            return AgentChatResponse(
                request_id=turn.request_id,
                content=result.content,
                status=RequestRunStatus.COMPLETED,
            )
        finally:
            await self._finish_prepared_turn(turn)

    async def _stream_replay_chunks(
        self,
        producer_service: ChatService,
        turn: PreparedTurn,
    ) -> AsyncIterator[str]:
        """Replay an already-persisted assistant reply as a one-shot stream."""
        assistant = await producer_service.request_run_repo.get_message(
            turn.request_id, MessageRole.ASSISTANT
        )
        if assistant is None:
            return
        text_id = uuid.uuid4().hex
        yield sse.start_part(str(turn.request_id))
        yield sse.text_start_part(text_id)
        yield sse.text_delta_part(text_id, assistant.content)
        yield sse.text_end_part(text_id)
        for url in assistant.source_urls:
            yield sse.source_url_part(url)
        yield sse.finish_part()
        yield sse.done_marker()

    async def _stream_execution_chunks(
        self,
        producer_service: ChatService,
        turn: PreparedTurn,
    ) -> AsyncIterator[str]:
        """Run one Agent turn and drain its stream events to UI chunks."""
        request_id = turn.request_id
        conversation_id = turn.conversation_id
        message = turn.message
        deadline_at = turn.deadline_at
        history = turn.history
        assert deadline_at is not None

        try:
            # Terminal gate: COMMIT the durable assistant final *before* the
            # adapter emits its finish chunk (on_complete runs upstream of
            # after_stream's FinishChunk in VercelAIAdapter.transform_stream).
            async def commit_final(result: AgentExecutionResult) -> None:
                # #region agent log
                debug_runtime_log(
                    hypothesis_id="H5",
                    location="chat/service.py:commit_final.before",
                    message="stream final commit started",
                    data={"request_id": str(request_id)},
                    run_id=str(request_id),
                )
                # #endregion agent log
                await producer_service._persist_request_success(
                    request_id=request_id,
                    conversation_id=conversation_id,
                    content=result.content,
                    reasoning_summary=result.reasoning_summary,
                    source_urls=result.source_urls,
                    usage=result.usage,
                    observation=result.observation,
                    enable_web_search=turn.enable_web_search,
                    enable_thinking=turn.enable_thinking,
                )
                # #region agent log
                debug_runtime_log(
                    hypothesis_id="H5",
                    location="chat/service.py:commit_final.after",
                    message="stream final commit finished",
                    data={"request_id": str(request_id)},
                    run_id=str(request_id),
                )
                # #endregion agent log

            async def commit_stream_terminal(
                kind: AgentStreamTerminalKind,
                _reason: str | None,
            ) -> str:
                return await _finalize_stream_terminal(
                    producer_service,
                    request_id=request_id,
                    kind=kind,
                    reason=_reason,
                )

            # The supervisor owns the Agent/adapter execution. The
            # StreamResumeStore producer only drains this channel and may
            # be detached/re-attached independently of the execution task.
            events: asyncio.Queue[str | BaseException | None] = asyncio.Queue()

            async def run_execution() -> None:
                # #region agent log
                debug_runtime_log(
                    hypothesis_id="H4",
                    location="chat/service.py:run_execution.entry",
                    message="stream agent execution started",
                    data={"request_id": str(request_id)},
                    run_id=str(request_id),
                )
                # #endregion agent log
                try:
                    async with _execution_timeout(deadline_at):
                        async for chunk in stream_vercel_events(
                            AgentExecutionRequest(
                                request_id=request_id,
                                conversation_id=conversation_id,
                                message=message,
                                history=history,
                                deadline_at=deadline_at,
                                enable_web_search=turn.enable_web_search,
                                enable_thinking=turn.enable_thinking,
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
                    # #region agent log
                    debug_runtime_log(
                        hypothesis_id="H4",
                        location="chat/service.py:run_execution.exit",
                        message="stream agent execution ended",
                        data={"request_id": str(request_id)},
                        run_id=str(request_id),
                    )
                    # #endregion agent log
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
                            yield await _finalize_stream_terminal(
                                producer_service,
                                request_id=request_id,
                                kind="abort",
                            )
                        elif isinstance(chunk, _StreamingDeadlineExceeded):
                            yield await _finalize_stream_terminal(
                                producer_service,
                                request_id=request_id,
                                kind="error",
                                reason="REQUEST_DEADLINE_EXCEEDED",
                            )
                        else:
                            yield await _finalize_stream_terminal(
                                producer_service,
                                request_id=request_id,
                                kind="error",
                            )
                        yield sse.done_marker()
                        break
                    yield chunk
                await execution_task
            except Exception:
                if not self.supervisor.cancellation_requested(request_id):
                    await producer_service._persist_request_terminal(
                        request_id=request_id,
                        status=RequestRunStatus.FAILED,
                        error_code="INTERNAL_ERROR",
                    )
                raise
        finally:
            await producer_service._finish_prepared_turn(turn)

    async def stream_factory(
        self,
        *,
        prepared: PreparedTurn,
    ) -> StreamFactory:
        """Build transport chunks from an already-prepared Product turn."""
        turn = prepared

        async def producer() -> AsyncIterator[str]:
            producer_db = AsyncSessionLocal()
            producer_service = ChatService(
                producer_db,
                executor=self.executor,
                runtime=self.runtime,
                supervisor=self.supervisor,
            )
            try:
                if turn.existing_request is not None:
                    async for chunk in self._stream_replay_chunks(
                        producer_service, turn
                    ):
                        yield chunk
                    return
                async for chunk in self._stream_execution_chunks(
                    producer_service, turn
                ):
                    yield chunk
            finally:
                await producer_db.close()

        return producer
