"""Opt-in live acceptance test for Gate A.

Run from the host with::

    LITELLM_BASE_URL=http://localhost:4000 \
    RUN_GATE_A_LIVE=1 \
    uv run --package app pytest backend/tests/integration/test_gate_a_live.py -q

The test makes one real model request, so it remains opt-in in the default suite.
"""

import os

import pytest
from httpx import AsyncClient

from app.core.config import settings

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_GATE_A_LIVE") != "1",
    reason="RUN_GATE_A_LIVE=1 is required because this test calls a real model",
)


async def test_product_chat_completes_through_live_litellm(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    conversation_response = await client.post(
        f"{settings.API_V1_STR}/conversations/",
        headers=normal_user_token_headers,
        json={"title": "Gate A live acceptance"},
    )
    assert conversation_response.status_code == 200
    conversation_id = conversation_response.json()["id"]

    chat_response = await client.post(
        f"{settings.API_V1_STR}/chat",
        headers={
            **normal_user_token_headers,
            "Idempotency-Key": "gate-a-live-litellm",
        },
        json={
            "conversation_id": conversation_id,
            "message": "这是连通性测试。请只回复 GATE_A_OK。",
        },
    )

    assert chat_response.status_code == 200
    chat_body = chat_response.json()
    assert chat_body["status"] == "completed"
    assert chat_body["content"].strip()
    assert chat_body["replayed"] is False

    durable_response = await client.get(
        f"{settings.API_V1_STR}/conversations/{conversation_id}",
        headers=normal_user_token_headers,
    )
    assert durable_response.status_code == 200
    messages = durable_response.json()["messages"]
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[-1]["content"] == chat_body["content"]
