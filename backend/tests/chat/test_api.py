from collections.abc import AsyncIterator
from typing import Any

from httpx import AsyncClient

import app.chat.api as chat_api


async def fake_ui_message_stream(
    ui_messages: list[dict[str, Any]],
) -> AsyncIterator[str]:
    assert ui_messages[-1]["role"] == "user"
    yield 'data: {"type":"start"}\n\n'
    yield 'data: {"type":"text-start","id":"text-1"}\n\n'
    yield 'data: {"type":"text-delta","id":"text-1","delta":"你好"}\n\n'
    yield 'data: {"type":"text-end","id":"text-1"}\n\n'
    yield 'data: {"type":"finish"}\n\n'
    yield "data: [DONE]\n\n"


async def test_chat_stream_uses_ai_sdk_contract(
    client: AsyncClient,
    superuser_token_headers: dict[str, str],
    monkeypatch,
) -> None:
    monkeypatch.setattr(chat_api, "ui_message_stream", fake_ui_message_stream)

    response = await client.post(
        "/api/v1/chat/stream",
        headers=superuser_token_headers,
        json={
            "id": "thread-1",
            "trigger": "submit-message",
            "messages": [
                {
                    "id": "user-1",
                    "role": "user",
                    "parts": [{"type": "text", "text": "你好"}],
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["x-vercel-ai-ui-message-stream"] == "v1"
    assert '"type":"text-delta"' in response.text
    assert response.text.endswith("data: [DONE]\n\n")


async def test_chat_stream_requires_authentication(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/chat/stream",
        json={
            "messages": [
                {
                    "role": "user",
                    "parts": [{"type": "text", "text": "你好"}],
                }
            ]
        },
    )

    assert response.status_code == 401


async def test_chat_stream_rejects_empty_messages(
    client: AsyncClient,
    superuser_token_headers: dict[str, str],
) -> None:
    response = await client.post(
        "/api/v1/chat/stream",
        headers=superuser_token_headers,
        json={"messages": []},
    )

    assert response.status_code == 422
