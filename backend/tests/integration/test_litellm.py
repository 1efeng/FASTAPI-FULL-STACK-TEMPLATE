import os

import httpx
import pytest

from app.core.config import settings
from app.infra.llm import build_model, close_llm, get_llm, init_llm


def test_litellm_client_uses_gateway_boundary() -> None:
    client = init_llm()
    assert str(client.base_url).rstrip("/") == (
        f"{settings.LITELLM_BASE_URL.rstrip('/')}/v1"
    )
    assert client.max_retries == 0


@pytest.mark.asyncio
async def test_litellm_client_lifecycle() -> None:
    init_llm()
    await close_llm()
    with pytest.raises(RuntimeError):
        get_llm()


@pytest.mark.asyncio
async def test_litellm_readiness_and_service_key() -> None:
    if os.getenv("RUN_LITELLM_INTEGRATION") != "1":
        pytest.skip("set RUN_LITELLM_INTEGRATION=1 to test the live gateway")

    async with httpx.AsyncClient(timeout=10) as client:
        live = await client.get(f"{settings.LITELLM_BASE_URL}/health/liveliness")
        assert live.status_code == 200
        models = await client.get(
            f"{settings.LITELLM_BASE_URL}/v1/models",
            headers={"Authorization": f"Bearer {settings.LITELLM_SERVICE_KEY}"},
        )
        assert models.status_code == 200
        assert any(
            model["id"] == settings.LLM_LOGICAL_MODEL
            for model in models.json()["data"]
        )

def test_model_builder_propagates_request_context() -> None:
    model = build_model(
        request_id="req-123",
        trace_id="trace-456",
        agent_role="researcher",
        metadata={"conversation_id": "conversation-789"},
    )

    assert model.model_name == settings.LLM_LOGICAL_MODEL
    assert str(model.openai_api_base).rstrip("/") == (
        f"{settings.LITELLM_BASE_URL.rstrip('/')}/v1"
    )
    assert model.max_retries == 0
    assert model.default_headers == {"X-Client-Request-Id": "req-123"}
    expected_metadata = {
        "request_id": "req-123",
        "trace_id": "trace-456",
        "agent_role": "researcher",
        "logical_model": settings.LLM_LOGICAL_MODEL,
        "conversation_id": "conversation-789",
    }
    assert model.metadata is not None
    assert all(model.metadata[key] == value for key, value in expected_metadata.items())
    assert model.extra_body == {"metadata": expected_metadata}
    assert model.tags == ["travel-agent", "researcher"]


def test_model_builder_rejects_empty_request_id() -> None:
    with pytest.raises(ValueError, match="request_id"):
        build_model(request_id=" ", agent_role="main")
@pytest.mark.asyncio
async def test_model_builder_live_completion() -> None:
    if os.getenv("RUN_LITELLM_INTEGRATION") != "1":
        pytest.skip("set RUN_LITELLM_INTEGRATION=1 to test the live gateway")

    model = build_model(
        request_id="m6-integration-request",
        trace_id="m6-integration-trace",
        agent_role="main",
        metadata={"test": True},
    )
    response = await model.ainvoke("Reply with exactly OK.")

    assert response.id
    assert response.usage_metadata is not None
    assert response.usage_metadata["total_tokens"] > 0
