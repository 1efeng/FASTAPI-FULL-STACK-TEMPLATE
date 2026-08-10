from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from langchain_core.messages import AIMessage
from openai import APIStatusError, APITimeoutError, RateLimitError

from app.core.config import settings
from app.modules.chat import service as service_module


class FakeAgent:
    def __init__(self) -> None:
        self.input: dict[str, Any] | None = None
        self.config: dict[str, Any] | None = None

    async def ainvoke(
        self,
        input: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, list[AIMessage]]:
        self.input = input
        self.config = config
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


async def test_agent_chat_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(
        f"{settings.API_V1_STR}/chat",
        json={"message": "你好"},
    )

    assert response.status_code == 401


async def test_agent_chat_rejects_blank_message(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    response = await client.post(
        f"{settings.API_V1_STR}/chat",
        headers=normal_user_token_headers,
        json={"message": "   "},
    )

    assert response.status_code == 422


async def test_agent_chat_invokes_agent(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_agent = FakeAgent()
    captured: dict[str, Any] = {}

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
        headers=normal_user_token_headers,
        json={"message": "  帮我规划上海两日游  "},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["request_id"] == captured["request_id"]
    assert body["content"] == "测试回复"
    assert captured["metadata"] == {"endpoint": "chat"}
    assert fake_agent.input == {
        "messages": [{"role": "user", "content": "帮我规划上海两日游"}]
    }
    assert fake_agent.config == {"recursion_limit": settings.AGENT_RECURSION_LIMIT}


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
    monkeypatch: pytest.MonkeyPatch,
    error_factory: Any,
    status_code: int,
    error_code: str,
) -> None:
    monkeypatch.setattr(
        service_module,
        "build_travel_agent",
        lambda **_: RaisingAgent(error_factory()),
    )

    response = await client.post(
        f"{settings.API_V1_STR}/chat",
        headers=normal_user_token_headers,
        json={"message": "测试下游错误"},
    )

    assert response.status_code == status_code
    body = response.json()
    assert body["code"] == error_code
    assert body["request_id"]
    assert "provider-secret" not in response.text
    assert "litellm.test" not in response.text
