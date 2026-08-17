import asyncio
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.executor import AgentExecutionRequest, AgentExecutionResult
from app.core.config import settings
from app.infra.database import AsyncSessionLocal
from app.modules.chat import api as api_module
from app.modules.chat import service as service_module
from app.modules.chat.execution import ExecutionSupervisor
from app.modules.chat.service import ChatService
from app.modules.conversation.model import Message, MessageRole
from app.modules.request_run.model import RequestRun, RequestRunStatus
from app.modules.user.service import UserService


class LateFinalExecutor:
    """Return a final even after task cancellation to exercise the Product CAS."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.returned_after_cancel = asyncio.Event()

    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        del request
        self.entered.set()
        try:
            await asyncio.Future[None]()
            raise AssertionError("executor wait unexpectedly completed")
        except asyncio.CancelledError:
            # A provider may finish at the same instant that cancellation wins.
            # Deliberately suppress task cancellation and return that late final.
            self.returned_after_cancel.set()
            return AgentExecutionResult(content="late final must be discarded")


class ImmediateExecutor:
    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        del request
        return AgentExecutionResult(content="durable before response")


async def _create_conversation(
    client: AsyncClient,
    headers: dict[str, str],
    title: str,
) -> uuid.UUID:
    response = await client.post(
        f"{settings.API_V1_STR}/conversations/",
        headers=headers,
        json={"title": title},
    )
    assert response.status_code == 200
    return uuid.UUID(response.json()["id"])


async def _request_run_for_key(idempotency_key: str) -> RequestRun:
    async with AsyncSessionLocal() as session:
        request_run = (
            await session.execute(
                select(RequestRun).where(
                    RequestRun.idempotency_key == idempotency_key
                )
            )
        ).scalar_one()
        session.expunge(request_run)
        return request_run


async def _messages_for_request(request_id: uuid.UUID) -> list[Message]:
    async with AsyncSessionLocal() as session:
        messages = list(
            (
                await session.execute(
                    select(Message)
                    .where(Message.request_id == request_id)
                    .order_by(Message.seq)
                )
            )
            .scalars()
            .all()
        )
        for message in messages:
            session.expunge(message)
        return messages


async def test_product_cancel_discards_executor_final_returned_after_cancellation(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = await _create_conversation(
        client,
        normal_user_token_headers,
        "Gate A cancel versus late final",
    )
    executor = LateFinalExecutor()
    monkeypatch.setattr(api_module, "get_agent_executor", lambda: executor)

    chat_task = asyncio.create_task(
        client.post(
            f"{settings.API_V1_STR}/chat",
            headers={
                **normal_user_token_headers,
                "Idempotency-Key": "gate-a-cancel-late-final",
            },
            json={
                "conversation_id": str(conversation_id),
                "message": "cancel while the model is finishing",
            },
        )
    )
    await asyncio.wait_for(executor.entered.wait(), timeout=2)
    request_run = await _request_run_for_key("gate-a-cancel-late-final")

    cancel_response = await client.post(
        f"{settings.API_V1_STR}/chat/requests/{request_run.id}/cancel",
        headers=normal_user_token_headers,
    )
    chat_response = await asyncio.wait_for(chat_task, timeout=2)

    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == "cancelled"
    assert executor.returned_after_cancel.is_set()
    assert chat_response.status_code == 409
    assert chat_response.json()["code"] == "REQUEST_CANCELLED"

    durable_request = await _request_run_for_key("gate-a-cancel-late-final")
    assert durable_request.status is RequestRunStatus.CANCELLED
    assert durable_request.finished_at is not None
    assert durable_request.error_code is None
    messages = await _messages_for_request(durable_request.id)
    assert [(message.role, message.content) for message in messages] == [
        (MessageRole.USER, "cancel while the model is finishing")
    ]


async def test_completed_response_waits_for_durable_assistant_and_request_commit(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = await _create_conversation(
        client,
        normal_user_token_headers,
        "Gate A durable before response",
    )
    monkeypatch.setattr(api_module, "get_agent_executor", ImmediateExecutor)

    original_commit = AsyncSession.commit
    commit_counts: dict[int, int] = {}
    success_commit_completed = asyncio.Event()
    allow_response = asyncio.Event()

    async def hold_after_success_commit(session: AsyncSession) -> None:
        await original_commit(session)
        session_id = id(session)
        commit_counts[session_id] = commit_counts.get(session_id, 0) + 1
        if commit_counts[session_id] == 2:
            success_commit_completed.set()
            await allow_response.wait()

    monkeypatch.setattr(AsyncSession, "commit", hold_after_success_commit)
    chat_task = asyncio.create_task(
        client.post(
            f"{settings.API_V1_STR}/chat",
            headers={
                **normal_user_token_headers,
                "Idempotency-Key": "gate-a-durable-before-response",
            },
            json={
                "conversation_id": str(conversation_id),
                "message": "prove the transaction boundary",
            },
        )
    )

    try:
        await asyncio.wait_for(success_commit_completed.wait(), timeout=2)
        assert not chat_task.done()

        request_run = await _request_run_for_key("gate-a-durable-before-response")
        assert request_run.status is RequestRunStatus.COMPLETED
        assert request_run.finished_at is not None
        assert request_run.error_code is None
        messages = await _messages_for_request(request_run.id)
        assert [(message.role, message.content) for message in messages] == [
            (MessageRole.USER, "prove the transaction boundary"),
            (MessageRole.ASSISTANT, "durable before response"),
        ]
    finally:
        allow_response.set()

    response = await asyncio.wait_for(chat_task, timeout=2)
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["content"] == "durable before response"


async def test_stream_agent_task_is_supervised_outside_store_producer(
    db: AsyncSession,
    normal_user_token_headers: dict[str, str],
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = await _create_conversation(
        client,
        normal_user_token_headers,
        "Supervisor stream topology",
    )
    user = await UserService(db).get_by_email(settings.EMAIL_TEST_USER)
    assert user is not None
    supervisor = ExecutionSupervisor()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def fake_stream(request, *, on_complete=None, on_terminal=None):
        del request
        del on_terminal
        entered.set()
        await release.wait()
        if on_complete is not None:
            await on_complete(
                AgentExecutionResult(
                    content="supervised stream final",
                    reasoning_summary="公开的规划思路摘要",
                )
            )
        yield "chunk-1"
        yield "chunk-2"

    monkeypatch.setattr(service_module, "stream_vercel_events", fake_stream)
    service = ChatService(
        db,
        executor=ImmediateExecutor(),
        supervisor=supervisor,
    )
    request_id = uuid.uuid4()
    prepared = await service.prepare_turn(
        request_id=request_id,
        user_id=user.id,
        conversation_id=conversation_id,
        idempotency_key="supervisor-stream-topology",
        message="stream this",
    )
    factory = await service.stream_factory(prepared=prepared)

    stream = factory()

    async def first_chunk() -> str:
        return await stream.__anext__()

    consume = asyncio.create_task(first_chunk())
    await asyncio.wait_for(entered.wait(), timeout=1)
    assert supervisor.is_running(request_id)
    release.set()
    assert await asyncio.wait_for(consume, timeout=1) == "chunk-1"
    assert [chunk async for chunk in stream] == ["chunk-2"]
    messages = await _messages_for_request(request_id)
    assistant = next(
        message for message in messages if message.role is MessageRole.ASSISTANT
    )
    assert assistant.reasoning_summary == "公开的规划思路摘要"
    await supervisor.shutdown()


async def test_stream_error_terminal_is_emitted_after_failed_commit(
    db: AsyncSession,
    normal_user_token_headers: dict[str, str],
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = await _create_conversation(
        client, normal_user_token_headers, "Streaming error gate"
    )
    user = await UserService(db).get_by_email(settings.EMAIL_TEST_USER)
    assert user is not None

    async def failing_stream(request, *, on_complete=None, on_terminal=None):
        del request, on_complete, on_terminal
        yield "non-terminal"
        raise RuntimeError("provider detail must not reach the UI")

    monkeypatch.setattr(service_module, "stream_vercel_events", failing_stream)
    service = ChatService(db, executor=ImmediateExecutor())
    request_id = uuid.uuid4()
    prepared = await service.prepare_turn(
        request_id=request_id,
        user_id=user.id,
        conversation_id=conversation_id,
        idempotency_key="stream-error-gate",
        message="fail this stream",
    )
    factory = await service.stream_factory(prepared=prepared)

    chunks = [chunk async for chunk in factory()]
    assert chunks[0] == "non-terminal"
    assert '"type": "error"' in chunks[1]
    assert "provider detail" not in chunks[1]
    assert chunks[2] == "data: [DONE]\n\n"
    request_run = await _request_run_for_key("stream-error-gate")
    assert request_run.status is RequestRunStatus.FAILED
    assert request_run.error_code == "INTERNAL_ERROR"
    assert [message.role for message in await _messages_for_request(request_id)] == [
        MessageRole.USER
    ]




@pytest.mark.parametrize(
    "error_code",
    ["MODEL_TIMEOUT", "MODEL_RATE_LIMITED", "MODEL_UNAVAILABLE"],
)
async def test_stream_typed_model_error_preserves_product_code(
    db: AsyncSession,
    normal_user_token_headers: dict[str, str],
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    error_code: str,
) -> None:
    conversation_id = await _create_conversation(
        client, normal_user_token_headers, f"Streaming {error_code} gate"
    )
    user = await UserService(db).get_by_email(settings.EMAIL_TEST_USER)
    assert user is not None
    raw_provider_detail = "private-provider-model sk-secret-upstream-detail"

    async def classified_stream(request, *, on_complete=None, on_terminal=None):
        del request, on_complete
        assert on_terminal is not None
        yield await on_terminal("error", error_code)
        assert raw_provider_detail not in error_code

    monkeypatch.setattr(service_module, "stream_vercel_events", classified_stream)
    service = ChatService(db, executor=ImmediateExecutor())
    request_id = uuid.uuid4()
    idempotency_key = f"stream-{error_code.lower()}-gate"
    prepared = await service.prepare_turn(
        request_id=request_id,
        user_id=user.id,
        conversation_id=conversation_id,
        idempotency_key=idempotency_key,
        message=f"fail with {error_code}",
    )
    factory = await service.stream_factory(prepared=prepared)

    chunks = [chunk async for chunk in factory()]
    assert any('"type": "error"' in chunk for chunk in chunks)
    assert raw_provider_detail not in "".join(chunks)
    request_run = await _request_run_for_key(idempotency_key)
    assert request_run.status is RequestRunStatus.FAILED
    assert request_run.error_code == error_code


async def test_stream_cancel_terminal_is_emitted_after_cancel_commit(
    db: AsyncSession,
    normal_user_token_headers: dict[str, str],
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = await _create_conversation(
        client, normal_user_token_headers, "Streaming cancel gate"
    )
    user = await UserService(db).get_by_email(settings.EMAIL_TEST_USER)
    assert user is not None
    supervisor = ExecutionSupervisor()
    entered = asyncio.Event()

    async def blocking_stream(request, *, on_complete=None, on_terminal=None):
        del request, on_complete, on_terminal
        entered.set()
        await asyncio.Future[None]()
        yield "unreachable"

    monkeypatch.setattr(service_module, "stream_vercel_events", blocking_stream)
    service = ChatService(
        db,
        executor=ImmediateExecutor(),
        supervisor=supervisor,
    )
    request_id = uuid.uuid4()
    prepared = await service.prepare_turn(
        request_id=request_id,
        user_id=user.id,
        conversation_id=conversation_id,
        idempotency_key="stream-cancel-gate",
        message="cancel this stream",
    )
    factory = await service.stream_factory(prepared=prepared)
    stream = factory()

    async def collect_stream() -> list[str]:
        return [chunk async for chunk in stream]

    consume = asyncio.create_task(collect_stream())
    await asyncio.wait_for(entered.wait(), timeout=1)
    supervisor.request_cancel(request_id)

    chunks = await asyncio.wait_for(consume, timeout=1)
    assert any('"type": "abort"' in chunk for chunk in chunks)
    assert chunks[-1] == "data: [DONE]\n\n"
    request_run = await _request_run_for_key("stream-cancel-gate")
    assert request_run.status is RequestRunStatus.CANCELLED
    await supervisor.shutdown()


async def test_stream_deadline_terminal_is_emitted_after_failed_commit(
    db: AsyncSession,
    normal_user_token_headers: dict[str, str],
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_id = await _create_conversation(
        client, normal_user_token_headers, "Streaming deadline gate"
    )
    user = await UserService(db).get_by_email(settings.EMAIL_TEST_USER)
    assert user is not None

    async def never_stream(request, *, on_complete=None, on_terminal=None):
        del request, on_complete, on_terminal
        await asyncio.Future[None]()
        yield "unreachable"

    monkeypatch.setattr(service_module, "stream_vercel_events", never_stream)
    monkeypatch.setattr(settings, "REQUEST_DEADLINE_SECONDS", 0.05)
    service = ChatService(db, executor=ImmediateExecutor())
    request_id = uuid.uuid4()
    prepared = await service.prepare_turn(
        request_id=request_id,
        user_id=user.id,
        conversation_id=conversation_id,
        idempotency_key="stream-deadline-gate",
        message="deadline this stream",
    )
    factory = await service.stream_factory(prepared=prepared)

    chunks = [chunk async for chunk in factory()]
    assert '"type": "error"' in chunks[0]
    assert "超时" in chunks[0]
    assert chunks[1] == "data: [DONE]\n\n"
    request_run = await _request_run_for_key("stream-deadline-gate")
    assert request_run.status is RequestRunStatus.FAILED
    assert request_run.error_code == "REQUEST_DEADLINE_EXCEEDED"
