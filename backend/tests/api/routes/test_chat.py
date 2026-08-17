import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.executor import (
    AgentExecutionError,
    AgentExecutionErrorCode,
    AgentExecutionRequest,
    AgentExecutionResult,
)
from app.core.config import settings
from app.infra.database import AsyncSessionLocal
from app.modules.chat import api as api_module
from app.modules.chat import service as service_module
from app.modules.conversation.model import Conversation, Message, MessageRole
from app.modules.request_run.model import RequestRun, RequestRunStatus


class CallbackExecutor:
    def __init__(
        self,
        *,
        on_execute: Callable[[uuid.UUID], Awaitable[None]] | None = None,
        error: BaseException | None = None,
    ) -> None:
        self.on_execute = on_execute
        self.error = error
        self.requests: list[AgentExecutionRequest] = []

    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        self.requests.append(request)
        if self.on_execute is not None:
            await self.on_execute(request.request_id)
        if self.error is not None:
            raise self.error
        return AgentExecutionResult(content="测试回复")


class RaisingExecutor:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    async def execute(self, *_: object, **__: object) -> AgentExecutionResult:
        raise self.error


class ReconnectStore:
    def __init__(self, stream: AsyncIterator[str] | None) -> None:
        self.stream = stream
        self.resume_calls: list[str] = []

    async def resume(self, stream_id: str) -> AsyncIterator[str] | None:
        self.resume_calls.append(stream_id)
        return self.stream


class StartStore:
    def __init__(self) -> None:
        self.start_ids: list[str] = []

    async def start_or_resume(
        self,
        stream_id: str,
        producer: Callable[[], AsyncIterator[str]],
    ) -> AsyncIterator[str]:
        self.start_ids.append(stream_id)
        return producer()


@pytest.fixture
async def normal_user_conversation_id(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
) -> uuid.UUID:
    response = await client.post(
        f"{settings.API_V1_STR}/conversations/",
        headers=normal_user_token_headers,
        json={"title": "Chat test"},
    )
    assert response.status_code == 200
    return uuid.UUID(response.json()["id"])


async def test_agent_chat_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(
        f"{settings.API_V1_STR}/chat",
        headers={"Idempotency-Key": "unauthenticated"},
        json={"conversation_id": str(uuid.uuid4()), "message": "你好"},
    )

    assert response.status_code == 401


async def test_stream_start_gate_creates_conversation_and_reuses_request_identity(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
) -> None:
    executor = CallbackExecutor()
    store = StartStore()
    async def fake_stream(
        request: AgentExecutionRequest,
        *,
        on_complete: Callable[[AgentExecutionResult], Awaitable[None]] | None,
        on_terminal: object,
    ) -> AsyncIterator[str]:
        del on_terminal
        executor.requests.append(request)
        assert on_complete is not None
        await on_complete(AgentExecutionResult(content="测试回复"))
        yield 'data: {"type":"finish"}\n\n'

    monkeypatch.setattr(service_module, "stream_vercel_events", fake_stream)
    monkeypatch.setattr(api_module, "get_stream_resume_store", lambda: store)

    response = await client.post(
        f"{settings.API_V1_STR}/chat/stream",
        headers={
            **normal_user_token_headers,
            "Idempotency-Key": "stream-first-turn",
        },
        json={
            "id": "ui-message-1",
            "messages": [
                {
                    "id": "ui-message-1",
                    "role": "user",
                    "parts": [{"type": "text", "text": "首条消息"}],
                }
            ],
            "conversation_id": None,
        },
    )

    assert response.status_code == 200
    request_id = response.headers["x-request-id"]
    conversation_id = uuid.UUID(response.headers["x-conversation-id"])
    assert store.start_ids == [request_id]
    assert request_id == str(executor.requests[0].request_id)
    assert executor.requests[0].conversation_id == conversation_id
    request_run = await db.get(RequestRun, uuid.UUID(request_id))
    conversation = await db.get(Conversation, conversation_id)
    assert request_run is not None
    assert conversation is not None
    assert request_run.conversation_id == conversation.id
    assert request_run.id == uuid.UUID(request_id)

    detail_response = await client.get(
        f"{settings.API_V1_STR}/conversations/{conversation_id}",
        headers=normal_user_token_headers,
    )
    assert detail_response.status_code == 200
    detail_messages = detail_response.json()["messages"]
    assert [message["role"] for message in detail_messages] == ["user", "assistant"]
    assert detail_messages[-1]["content"] == "测试回复"


async def test_stream_persists_assistant_when_reasoning_lacks_public_summary(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A raw-CoT turn has no public summary yet the assistant must persist."""

    executor = CallbackExecutor()
    store = StartStore()

    async def fake_stream(
        request: AgentExecutionRequest,
        *,
        on_complete: Callable[[AgentExecutionResult], Awaitable[None]] | None,
        on_terminal: object,
    ) -> AsyncIterator[str]:
        del on_terminal
        executor.requests.append(request)
        assert on_complete is not None
        await on_complete(
            AgentExecutionResult(
                content="测试回复",
                reasoning_summary=None,
            )
        )
        yield 'data: {"type":"finish"}\n\n'

    monkeypatch.setattr(service_module, "stream_vercel_events", fake_stream)
    monkeypatch.setattr(api_module, "get_stream_resume_store", lambda: store)

    response = await client.post(
        f"{settings.API_V1_STR}/chat/stream",
        headers={
            **normal_user_token_headers,
            "Idempotency-Key": "stream-reasoning-no-summary",
        },
        json={
            "id": "ui-message-1",
            "messages": [
                {
                    "id": "ui-message-1",
                    "role": "user",
                    "parts": [{"type": "text", "text": "你好"}],
                }
            ],
            "conversation_id": None,
        },
    )

    assert response.status_code == 200
    conversation_id = uuid.UUID(response.headers["x-conversation-id"])

    detail_response = await client.get(
        f"{settings.API_V1_STR}/conversations/{conversation_id}",
        headers=normal_user_token_headers,
    )
    assert detail_response.status_code == 200
    detail_messages = detail_response.json()["messages"]
    assert [message["role"] for message in detail_messages] == ["user", "assistant"]
    assert detail_messages[-1]["content"] == "测试回复"
    assert detail_messages[-1]["reasoning_summary"] is None


async def test_stream_rejects_missing_conversation_before_opening_sse(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale localStorage conversation id must be a normal 404, not a stream reset."""
    monkeypatch.setattr(api_module, "get_agent_executor", lambda: CallbackExecutor())
    response = await client.post(
        f"{settings.API_V1_STR}/chat/stream",
        headers={
            **normal_user_token_headers,
            "Idempotency-Key": "stream-missing-conversation",
        },
        json={
            "id": "ui-message-1",
            "messages": [
                {
                    "id": "ui-message-1",
                    "role": "user",
                    "parts": [{"type": "text", "text": "你好"}],
                }
            ],
            "conversation_id": str(uuid.uuid4()),
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "会话不存在或已删除。"}


async def test_reconnect_endpoint_is_authoritative_for_stream_availability(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
    normal_user_conversation_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_module, "get_agent_executor", lambda: CallbackExecutor())
    chat_response = await client.post(
        f"{settings.API_V1_STR}/chat",
        headers={
            **normal_user_token_headers,
            "Idempotency-Key": "reconnect-authority",
        },
        json={
            "conversation_id": str(normal_user_conversation_id),
            "message": "你好",
        },
    )
    assert chat_response.status_code == 200
    request_id = chat_response.json()["request_id"]

    missing_store = ReconnectStore(None)
    monkeypatch.setattr(
        api_module,
        "get_stream_resume_store",
        lambda: missing_store,
    )
    missing_response = await client.get(
        f"{settings.API_V1_STR}/chat/requests/{request_id}/stream",
        headers=normal_user_token_headers,
    )

    assert missing_response.status_code == 204
    assert missing_store.resume_calls == [request_id]

    async def active_stream() -> AsyncIterator[str]:
        yield 'data: {"type":"finish"}\n\n'
        yield "data: [DONE]\n\n"

    active_store = ReconnectStore(active_stream())
    monkeypatch.setattr(
        api_module,
        "get_stream_resume_store",
        lambda: active_store,
    )
    active_response = await client.get(
        f"{settings.API_V1_STR}/chat/requests/{request_id}/stream",
        headers=normal_user_token_headers,
    )

    assert active_response.status_code == 200
    assert active_response.headers["x-vercel-ai-ui-message-stream"] == "v1"
    assert active_store.resume_calls == [request_id]


async def test_agent_chat_rejects_blank_message(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
    normal_user_conversation_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_module, "get_agent_executor", lambda: CallbackExecutor())
    response = await client.post(
        f"{settings.API_V1_STR}/chat",
        headers={
            **normal_user_token_headers,
            "Idempotency-Key": "blank-message",
        },
        json={
            "conversation_id": str(normal_user_conversation_id),
            "message": "   ",
        },
    )

    assert response.status_code == 422


async def test_agent_chat_requires_idempotency_key(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
    normal_user_conversation_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_module, "get_agent_executor", lambda: CallbackExecutor())
    response = await client.post(
        f"{settings.API_V1_STR}/chat",
        headers=normal_user_token_headers,
        json={
            "conversation_id": str(normal_user_conversation_id),
            "message": "你好",
        },
    )

    assert response.status_code == 422


async def test_agent_chat_invokes_agent(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
    normal_user_conversation_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
) -> None:
    captured_request_id: uuid.UUID | None = None

    async def assert_request_is_durable_before_agent(request_id: uuid.UUID) -> None:
        nonlocal captured_request_id
        captured_request_id = request_id
        async with AsyncSessionLocal() as session:
            request_run = await session.get(RequestRun, request_id)
            assert request_run is not None
            assert request_run.status is RequestRunStatus.RUNNING
            assert request_run.idempotency_key == "chat-success"
            assert request_run.conversation_id == normal_user_conversation_id
            assert request_run.deadline_at - request_run.started_at == timedelta(
                seconds=settings.REQUEST_DEADLINE_SECONDS
            )

            user_message = (
                await session.execute(
                    select(Message).where(Message.request_id == request_id)
                )
            ).scalar_one()
            assert user_message.role is MessageRole.USER
            assert user_message.content == "帮我规划上海两日游"

            conversation = await session.get(Conversation, normal_user_conversation_id)
            assert conversation is not None
            assert conversation.last_message_at == request_run.started_at

    executor = CallbackExecutor(on_execute=assert_request_is_durable_before_agent)
    monkeypatch.setattr(api_module, "get_agent_executor", lambda: executor)
    response = await client.post(
        f"{settings.API_V1_STR}/chat",
        headers={
            **normal_user_token_headers,
            "Idempotency-Key": "chat-success",
        },
        json={
            "conversation_id": str(normal_user_conversation_id),
            "message": "  帮我规划上海两日游  ",
        },
    )

    assert response.status_code == 200
    body = response.json()
    request_id = uuid.UUID(body["request_id"])
    request_run = await db.get(RequestRun, request_id)
    assert request_run is not None
    messages = (
        (
            await db.execute(
                select(Message)
                .where(Message.request_id == request_id)
                .order_by(Message.seq)
            )
        )
        .scalars()
        .all()
    )
    conversation = await db.get(Conversation, normal_user_conversation_id)
    assert conversation is not None
    assert request_run.status is RequestRunStatus.COMPLETED
    assert request_run.finished_at is not None
    assert request_run.error_code is None
    assert [message.role for message in messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
    ]
    assert messages[-1].content == "测试回复"
    assert conversation.last_message_at == request_run.finished_at
    assert body["request_id"] == str(captured_request_id)
    assert body["content"] == "测试回复"
    assert len(executor.requests) == 1
    req = executor.requests[0]
    assert req.request_id == request_id
    assert req.conversation_id == normal_user_conversation_id
    assert req.message == "帮我规划上海两日游"


async def test_agent_chat_rejects_other_users_conversation_before_agent(
    client: AsyncClient,
    superuser_token_headers: dict[str, str],
    normal_user_conversation_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
) -> None:
    executed = False

    def fail_if_agent_is_executed() -> CallbackExecutor:
        async def mark_executed(_: uuid.UUID) -> None:
            nonlocal executed
            executed = True

        return CallbackExecutor(on_execute=mark_executed)

    monkeypatch.setattr(
        api_module,
        "get_agent_executor",
        fail_if_agent_is_executed,
    )
    response = await client.post(
        f"{settings.API_V1_STR}/chat",
        headers={
            **superuser_token_headers,
            "Idempotency-Key": "cross-user",
        },
        json={
            "conversation_id": str(normal_user_conversation_id),
            "message": "越权请求",
        },
    )
    request_count = (
        await db.execute(
            select(func.count())
            .select_from(RequestRun)
            .where(RequestRun.conversation_id == normal_user_conversation_id)
        )
    ).scalar_one()

    assert response.status_code == 404
    assert response.json()["code"] == "CONVERSATION_NOT_FOUND"
    assert request_count == 0
    assert executed is False


async def test_agent_chat_rejects_deleted_conversation_before_agent(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
    normal_user_conversation_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delete_response = await client.delete(
        f"{settings.API_V1_STR}/conversations/{normal_user_conversation_id}",
        headers=normal_user_token_headers,
    )
    assert delete_response.status_code == 200

    executed = False

    def fail_if_agent_is_executed() -> CallbackExecutor:
        async def mark_executed(_: uuid.UUID) -> None:
            nonlocal executed
            executed = True

        return CallbackExecutor(on_execute=mark_executed)

    monkeypatch.setattr(
        api_module,
        "get_agent_executor",
        fail_if_agent_is_executed,
    )
    response = await client.post(
        f"{settings.API_V1_STR}/chat",
        headers={
            **normal_user_token_headers,
            "Idempotency-Key": "deleted-conversation",
        },
        json={
            "conversation_id": str(normal_user_conversation_id),
            "message": "已删除会话",
        },
    )

    assert response.status_code == 404
    assert response.json()["code"] == "CONVERSATION_NOT_FOUND"
    assert executed is False


async def test_agent_does_not_run_when_start_transaction_rolls_back(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
    normal_user_conversation_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
) -> None:
    executed = False

    def fail_if_agent_is_executed() -> CallbackExecutor:
        async def mark_executed(_: uuid.UUID) -> None:
            nonlocal executed
            executed = True

        return CallbackExecutor(on_execute=mark_executed)

    async def fail_commit(_session: AsyncSession) -> None:
        raise RuntimeError("forced start transaction commit failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(
            api_module,
            "get_agent_executor",
            fail_if_agent_is_executed,
        )
        scoped.setattr(AsyncSession, "commit", fail_commit)
        response = await client.post(
            f"{settings.API_V1_STR}/chat",
            headers={
                **normal_user_token_headers,
                "Idempotency-Key": "commit-failure",
            },
            json={
                "conversation_id": str(normal_user_conversation_id),
                "message": "不能开始",
            },
        )

    run_count = (
        await db.execute(
            select(func.count())
            .select_from(RequestRun)
            .where(RequestRun.conversation_id == normal_user_conversation_id)
        )
    ).scalar_one()
    message_count = (
        await db.execute(
            select(func.count())
            .select_from(Message)
            .where(Message.conversation_id == normal_user_conversation_id)
        )
    ).scalar_one()

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert "forced start transaction commit failure" not in response.text
    assert run_count == 0
    assert message_count == 0
    assert executed is False


@pytest.mark.parametrize(
    ("executor_error_code", "status_code", "error_code"),
    [
        ("MODEL_TIMEOUT", 504, "MODEL_TIMEOUT"),
        ("MODEL_RATE_LIMITED", 429, "MODEL_RATE_LIMITED"),
        ("MODEL_UNAVAILABLE", 503, "MODEL_UNAVAILABLE"),
    ],
)
async def test_agent_chat_maps_executor_failures_without_leaking_details(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
    normal_user_conversation_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    executor_error_code: AgentExecutionErrorCode,
    status_code: int,
    error_code: str,
    db: AsyncSession,
) -> None:
    monkeypatch.setattr(
        api_module,
        "get_agent_executor",
        lambda: RaisingExecutor(AgentExecutionError(code=executor_error_code)),
    )

    response = await client.post(
        f"{settings.API_V1_STR}/chat",
        headers={
            **normal_user_token_headers,
            "Idempotency-Key": "executor-failure",
        },
        json={
            "conversation_id": str(normal_user_conversation_id),
            "message": "测试下游错误",
        },
    )

    assert response.status_code == status_code
    body = response.json()
    assert body["code"] == error_code
    assert body["request_id"]
    request_id = uuid.UUID(body["request_id"])
    request_run = await db.get(RequestRun, request_id)
    assert request_run is not None
    assert request_run.status is RequestRunStatus.FAILED
    assert request_run.error_code == error_code
    assert request_run.finished_at is not None
    roles = (
        (await db.execute(select(Message.role).where(Message.request_id == request_id)))
        .scalars()
        .all()
    )
    assert roles == [MessageRole.USER]


async def test_agent_chat_maps_model_call_limit_without_leaking_details(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
    normal_user_conversation_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
) -> None:
    monkeypatch.setattr(
        api_module,
        "get_agent_executor",
        lambda: RaisingExecutor(
            AgentExecutionError(code="MODEL_CALL_LIMIT_REACHED", retryable=False)
        ),
    )

    response = await client.post(
        f"{settings.API_V1_STR}/chat",
        headers={
            **normal_user_token_headers,
            "Idempotency-Key": "model-call-limit",
        },
        json={
            "conversation_id": str(normal_user_conversation_id),
            "message": "触发模型调用上限",
        },
    )

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "MODEL_CALL_LIMIT_REACHED"
    request_id = uuid.UUID(body["request_id"])
    request_run = await db.get(RequestRun, request_id)
    assert request_run is not None
    assert request_run.status is RequestRunStatus.FAILED
    assert request_run.error_code == "MODEL_CALL_LIMIT_REACHED"
    roles = (
        (await db.execute(select(Message.role).where(Message.request_id == request_id)))
        .scalars()
        .all()
    )
    assert roles == [MessageRole.USER]
