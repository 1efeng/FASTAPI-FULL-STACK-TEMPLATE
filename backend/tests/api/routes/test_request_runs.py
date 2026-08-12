import uuid

import pytest
from httpx import AsyncClient

from app.agent.executor import AgentExecutionResult
from app.core.config import settings
from app.modules.chat import api as api_module


class SuccessfulExecutor:
    async def execute(
        self,
        *,
        request_id: uuid.UUID,
        conversation_id: uuid.UUID,
        message: str,
        deadline_at: object,
    ) -> AgentExecutionResult:
        del request_id, conversation_id, message, deadline_at
        return AgentExecutionResult(content="done")


async def _completed_request(
    client: AsyncClient,
    headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[uuid.UUID, uuid.UUID]:
    conversation_response = await client.post(
        f"{settings.API_V1_STR}/conversations/",
        headers=headers,
        json={"title": "Request status"},
    )
    assert conversation_response.status_code == 200
    conversation_id = uuid.UUID(conversation_response.json()["id"])
    monkeypatch.setattr(
        api_module,
        "get_agent_executor",
        lambda: SuccessfulExecutor(),
    )
    chat_response = await client.post(
        f"{settings.API_V1_STR}/chat",
        headers={**headers, "Idempotency-Key": "request-status"},
        json={
            "conversation_id": str(conversation_id),
            "message": "hello",
        },
    )
    assert chat_response.status_code == 200
    return uuid.UUID(chat_response.json()["request_id"]), conversation_id


async def test_request_status_returns_owned_durable_state(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_id, conversation_id = await _completed_request(
        client, normal_user_token_headers, monkeypatch
    )

    response = await client.get(
        f"{settings.API_V1_STR}/chat/requests/{request_id}",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 200
    content = response.json()
    assert content["request_id"] == str(request_id)
    assert content["conversation_id"] == str(conversation_id)
    assert content["status"] == "completed"
    assert content["error_code"] is None
    assert content["started_at"]
    assert content["deadline_at"]
    assert content["finished_at"]
    assert "content" not in content


async def test_request_status_hides_other_users_request(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_id, _ = await _completed_request(
        client, normal_user_token_headers, monkeypatch
    )

    response = await client.get(
        f"{settings.API_V1_STR}/chat/requests/{request_id}",
        headers=superuser_token_headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Request not found"


async def test_request_status_returns_not_found(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    response = await client.get(
        f"{settings.API_V1_STR}/chat/requests/{uuid.uuid4()}",
        headers=normal_user_token_headers,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Request not found"
