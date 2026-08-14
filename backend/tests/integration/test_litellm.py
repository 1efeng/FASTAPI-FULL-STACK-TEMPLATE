import os

import httpx
import pytest

from app.core.config import settings


def test_litellm_gateway_configuration_is_framework_neutral() -> None:
    assert settings.LITELLM_BASE_URL
    assert settings.LLM_LOGICAL_MODEL


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("RUN_LITELLM_INTEGRATION") != "1",
    reason="set RUN_LITELLM_INTEGRATION=1 to test the live gateway",
)
async def test_litellm_readiness_and_service_key() -> None:
    gateway_base_url = (
        os.getenv("LITELLM_BASE_URL") or settings.LITELLM_BASE_URL
    ).rstrip("/")
    async with httpx.AsyncClient(timeout=10) as client:
        live = await client.get(f"{gateway_base_url}/health/liveliness")
        assert live.status_code == 200
        models = await client.get(
            f"{gateway_base_url}/v1/models",
            headers={"Authorization": f"Bearer {settings.LITELLM_SERVICE_KEY}"},
        )
        assert models.status_code == 200
        assert any(
            model["id"] == settings.LLM_LOGICAL_MODEL
            for model in models.json()["data"]
        )
