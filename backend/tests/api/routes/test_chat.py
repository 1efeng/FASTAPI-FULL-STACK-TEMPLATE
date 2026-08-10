from typing import Any

import pytest
from httpx import AsyncClient
from langchain_core.messages import AIMessage

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
