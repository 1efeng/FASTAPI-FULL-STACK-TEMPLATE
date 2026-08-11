import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from langchain.agents.middleware.model_call_limit import (
    ModelCallLimitExceededError,
)
from langchain_core.messages import AIMessage
from openai import APIStatusError, APITimeoutError, RateLimitError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.infra.database import AsyncSessionLocal
from app.modules.chat import service as service_module
from app.modules.conversation.model import Conversation, Message, MessageRole
from app.modules.request_run.model import RequestRun, RequestRunStatus


class FakeAgent:
    def __init__(self, on_invoke: Callable[[], Awaitable[None]] | None = None) -> None:
        self.input: dict[str, Any] | None = None
        self.config: dict[str, Any] | None = None
        self.on_invoke = on_invoke

    async def ainvoke(
        self,
        input: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, list[AIMessage]]:
        self.input = input
        self.config = config
        if self.on_invoke is not None:
            await self.on_invoke()
        return {"messages": [AIMessage(content="测试回复")]}


class RaisingAgent:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def ainvoke(
        self,
        _input: dict[str, Any],
        **_: Any,
    ) -> dict[str, list[AIMessage]]:
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
) -> None:
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
) -> None:
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
    captured: dict[str, Any] = {}

    async def assert_request_is_durable_before_agent() -> None:
        request_id = uuid.UUID(captured["request_id"])
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

    fake_agent = FakeAgent(on_invoke=assert_request_is_durable_before_agent)

    def fake_build_travel_agent(**kwargs: Any) -> FakeAgent:
        captured.update(kwargs)
        return fake_agent

    monkeypatch.setattr(
        service_module,
        "build_travel_agent",
        fake_build_travel_agent,
    )
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
    assert body["request_id"] == captured["request_id"]
    assert body["content"] == "测试回复"
    assert captured["metadata"] == {
        "endpoint": "chat",
        "conversation_id": str(normal_user_conversation_id),
    }
    assert fake_agent.input == {
        "messages": [{"role": "user", "content": "帮我规划上海两日游"}]
    }
    assert fake_agent.config == {
        "recursion_limit": settings.AGENT_RECURSION_LIMIT,
        "configurable": {"thread_id": str(conversation.langgraph_thread_id)},
    }


async def test_agent_chat_rejects_other_users_conversation_before_agent(
    client: AsyncClient,
    superuser_token_headers: dict[str, str],
    normal_user_conversation_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
) -> None:
    agent_built = False

    def fail_if_agent_is_built(**_: Any) -> FakeAgent:
        nonlocal agent_built
        agent_built = True
        return FakeAgent()

    monkeypatch.setattr(service_module, "build_travel_agent", fail_if_agent_is_built)
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
    assert agent_built is False


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

    agent_built = False

    def fail_if_agent_is_built(**_: Any) -> FakeAgent:
        nonlocal agent_built
        agent_built = True
        return FakeAgent()

    monkeypatch.setattr(service_module, "build_travel_agent", fail_if_agent_is_built)
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
    assert agent_built is False


async def test_agent_does_not_run_when_start_transaction_rolls_back(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
    normal_user_conversation_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
) -> None:
    agent_built = False

    def fail_if_agent_is_built(**_: Any) -> FakeAgent:
        nonlocal agent_built
        agent_built = True
        return FakeAgent()

    async def fail_commit(_session: AsyncSession) -> None:
        raise RuntimeError("forced start transaction commit failure")

    with monkeypatch.context() as scoped:
        scoped.setattr(service_module, "build_travel_agent", fail_if_agent_is_built)
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
    assert agent_built is False


def _request() -> httpx.Request:
    return httpx.Request("POST", "http://litellm.test/v1/chat/completions")


@pytest.mark.parametrize(
    ("error_factory", "status_code", "error_code"),
    [
        (lambda: APITimeoutError(request=_request()), 504, "MODEL_TIMEOUT"),
        (
            lambda: RateLimitError(
                "provider-secret-rate-limit",
                response=httpx.Response(429, request=_request()),
                body={"error": "provider-secret-rate-limit"},
            ),
            429,
            "MODEL_RATE_LIMITED",
        ),
        (
            lambda: APIStatusError(
                "provider-secret-internal-detail",
                response=httpx.Response(503, request=_request()),
                body={"error": "provider-secret-internal-detail"},
            ),
            503,
            "MODEL_UNAVAILABLE",
        ),
    ],
)
async def test_agent_chat_maps_provider_failures_without_leaking_details(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
    normal_user_conversation_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    error_factory: Any,
    status_code: int,
    error_code: str,
    db: AsyncSession,
) -> None:
    monkeypatch.setattr(
        service_module,
        "build_travel_agent",
        lambda **_: RaisingAgent(error_factory()),
    )

    response = await client.post(
        f"{settings.API_V1_STR}/chat",
        headers={
            **normal_user_token_headers,
            "Idempotency-Key": "provider-failure",
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
    assert "provider-secret" not in response.text
    assert "litellm.test" not in response.text


async def test_agent_chat_maps_model_call_limit_without_leaking_details(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
    normal_user_conversation_id: uuid.UUID,
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
) -> None:
    monkeypatch.setattr(
        service_module,
        "build_travel_agent",
        lambda **_: RaisingAgent(
            ModelCallLimitExceededError(
                thread_count=0,
                run_count=settings.MODEL_CALL_LIMIT,
                thread_limit=None,
                run_limit=settings.MODEL_CALL_LIMIT,
            )
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
    assert "Model call limits exceeded" not in response.text
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
