"""External-tool timeout ownership contracts after the web research refactor."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest

from app.agent.tools import _timeout
from app.agent.tools.route import search_maps
from app.agent.tools.weather import get_weather
from app.core.config import settings


def test_runtime_timeout_hierarchy_is_bounded() -> None:
    assert 0 < _timeout.TOOL_EXECUTION_TIMEOUT_SECONDS
    assert (
        _timeout.TOOL_EXECUTION_TIMEOUT_SECONDS
        < settings.LITELLM_CLIENT_TIMEOUT_SECONDS
    )
    assert settings.LITELLM_CLIENT_TIMEOUT_SECONDS < settings.REQUEST_DEADLINE_SECONDS
    assert _timeout.TOOL_EXECUTION_TIMEOUT_SECONDS == 30
    assert settings.LITELLM_CLIENT_TIMEOUT_SECONDS == 240
    assert settings.REQUEST_DEADLINE_SECONDS == 900


class _HangingClient:
    async def __aenter__(self) -> _HangingClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        del args
        return None

    async def get(self, *args: object, **kwargs: object) -> Any:
        del args, kwargs
        await asyncio.Future[None]()
        raise AssertionError("hanging client returned")


@pytest.mark.asyncio
async def test_weather_tool_bounded_when_provider_hangs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_timeout, "TOOL_EXECUTION_TIMEOUT_SECONDS", 0.05)
    with patch(
        "app.agent.tools.weather.httpx.AsyncClient",
        return_value=_HangingClient(),
    ):
        result = await asyncio.wait_for(get_weather("东京"), timeout=2)

    assert result == {
        "status": "error",
        "error_code": "PROVIDER_TIMEOUT",
        "message": "天气查询暂时超时：TimeoutError",
        "retryable": True,
    }


@pytest.mark.asyncio
async def test_route_tool_bounded_when_provider_hangs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_timeout, "TOOL_EXECUTION_TIMEOUT_SECONDS", 0.05)
    with patch(
        "app.agent.tools.route.httpx.AsyncClient",
        return_value=_HangingClient(),
    ):
        result = await asyncio.wait_for(
            search_maps("东京", "京都", mode="driving"),
            timeout=2,
        )

    assert result == {
        "status": "error",
        "error_code": "PROVIDER_TIMEOUT",
        "message": "路线查询暂时超时：TimeoutError",
        "retryable": True,
    }
