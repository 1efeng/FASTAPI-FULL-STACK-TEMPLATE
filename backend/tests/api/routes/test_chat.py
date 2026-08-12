import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.infra.database import AsyncSessionLocal
from app.modules.chat import api as api_module
from app.modules.chat.executor import AgentExecutionError, AgentExecutionResult
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
        self.calls: list[dict[str, object]] = []

    async def execute(
        self,
        *,
        request_id: uuid.UUID,
        conversation_id: uuid.UUID,
        message: str,
        deadline_at: object,
    ) -> AgentExecutionResult:
        self.calls.append(
            {
                "request_id": request_id,
                "conversation_id": conversation_id,
                "message": message,
                "deadline_at": deadline_at,
            }
        )
        if self.on_execute is not None:
            await self.on_execute(request_id)
        if self.error is not None:
            raise self.error
        return AgentExecutionResult(content="测试回复")


class RaisingExecutor:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    async def execute(self, *_: object, **__: object) -> AgentExecutionResult:
        raise self.error


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
    assert len(executor.calls) == 1
    assert executor.calls[0]["request_id"] == request_id
    assert executor.calls[0]["conversation_id"] == normal_user_conversation_id
    assert executor.calls[0]["message"] == "帮我规划上海两日游"


async def test_agent_chat_rejects_other_users_conversation_before_agent(
    client: AsyncClient,
    superuser_token_headers: dict[str, str],
    normal_user_conversation_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
) -> None:
    executed = False

    def fail_if_agent_is_executed() -> CallbackExecutor:
        executor = CallbackExecutor()

        async def mark_executed(*_: object, **__: object) -> AgentExecutionResult:
            nonlocal executed
            executed = True
            return AgentExecutionResult(content="should not run")

        executor.execute = mark_executed  # type: ignore[method-assign]
        return executor

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
        executor = CallbackExecutor()

        async def mark_executed(*_: object, **__: object) -> AgentExecutionResult:
            nonlocal executed
            executed = True
            return AgentExecutionResult(content="should not run")

        executor.execute = mark_executed  # type: ignore[method-assign]
        return executor

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
        executor = CallbackExecutor()

        async def mark_executed(*_: object, **__: object) -> AgentExecutionResult:
            nonlocal executed
            executed = True
            return AgentExecutionResult(content="should not run")

        executor.execute = mark_executed  # type: ignore[method-assign]
        return executor

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
    executor_error_code: str,
    status_code: int,
    error_code: str,
    db: AsyncSession,
) -> None:
    monkeypatch.setattr(
        api_module,
        "get_agent_executor",
        lambda: RaisingExecutor(AgentExecutionError(code=executor_error_code)),  # type: ignore[arg-type]
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
