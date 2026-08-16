"""External-tool timeout ownership contracts after the web research refactor."""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pydantic_ai.common_tools.web_fetch import WebFetchLocalTool, web_fetch_tool

from app.agent.tools import _timeout
from app.agent.tools.currency import CurrencyAmount, convert_currency
from app.agent.tools.image_search import _TIMEOUT_SECONDS as IMAGE_SEARCH_TIMEOUT_SECONDS
from app.agent.tools.route import search_maps
from app.agent.tools.search import _TIMEOUT_SECONDS as WEB_SEARCH_TIMEOUT_SECONDS
from app.agent.tools.weather import get_weather
from app.core.config import settings


def test_runtime_timeout_hierarchy_is_bounded() -> None:
    assert 0 < _timeout.TOOL_EXECUTION_TIMEOUT_SECONDS
    assert _timeout.TOOL_EXECUTION_TIMEOUT_SECONDS < settings.LITELLM_CLIENT_TIMEOUT_SECONDS
    assert settings.LITELLM_CLIENT_TIMEOUT_SECONDS < settings.REQUEST_DEADLINE_SECONDS
    assert _timeout.TOOL_EXECUTION_TIMEOUT_SECONDS == 30
    assert settings.LITELLM_CLIENT_TIMEOUT_SECONDS == 150
    assert settings.REQUEST_DEADLINE_SECONDS == 300


def test_search_timeouts_are_tighter_than_model_rpc_bound() -> None:
    assert 0 < WEB_SEARCH_TIMEOUT_SECONDS < settings.LITELLM_CLIENT_TIMEOUT_SECONDS
    assert 0 < IMAGE_SEARCH_TIMEOUT_SECONDS < settings.LITELLM_CLIENT_TIMEOUT_SECONDS


def test_official_web_fetch_keeps_its_internal_30_second_bound() -> None:
    tool = web_fetch_tool()
    bound_instance = getattr(tool.function, "__self__", None)

    assert isinstance(bound_instance, WebFetchLocalTool)
    assert bound_instance.timeout == 30
    assert bound_instance.allow_local_urls is False
    assert bound_instance.max_content_length == 50_000
    assert bound_instance.timeout < settings.LITELLM_CLIENT_TIMEOUT_SECONDS


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

    assert result == "天气查询暂时失败：TimeoutError"


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

    assert result == "路线查询暂时失败：TimeoutError"


async def _never(*args: object, **kwargs: object) -> Any:
    del args, kwargs
    await asyncio.Future[None]()
    raise AssertionError("hung provider returned")


@pytest.mark.asyncio
async def test_currency_tool_bounded_when_provider_hangs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_timeout, "TOOL_EXECUTION_TIMEOUT_SECONDS", 0.05)
    with patch(
        "app.agent.tools.currency.get_exchange_rate",
        AsyncMock(side_effect=_never),
    ):
        result = await asyncio.wait_for(
            convert_currency(
                from_currency="JPY",
                amounts=[CurrencyAmount(name="预算", amount_min=Decimal("100"))],
            ),
            timeout=2,
        )

    assert result == "汇率换算暂时失败：TimeoutError"
