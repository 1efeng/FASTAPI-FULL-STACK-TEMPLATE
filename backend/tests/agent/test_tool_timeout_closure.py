"""Tool Timeout Closure contract tests.

Every external IO tool must finish within a bounded window; a hung provider
must degrade to the standard tool text result instead of hanging the run or
eating the Product deadline / Researcher budget.

The tool layer owns this boundary: ``TOOL_EXECUTION_TIMEOUT_SECONDS`` is the
tightest time owner and must stay below the model RPC timeout. No real
provider is called — providers are faked or hung in-process.
"""

import asyncio
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.tools import _timeout
from app.agent.tools.currency import CurrencyAmount, convert_currency
from app.agent.tools.route import search_maps
from app.agent.tools.weather import get_weather
from app.agent.tools.web_fetch import _fetcher
from app.core.config import settings


def test_tool_execution_bound_is_tighter_than_model_rpc_timeout() -> None:
    assert 0 < _timeout.TOOL_EXECUTION_TIMEOUT_SECONDS
    assert (
        _timeout.TOOL_EXECUTION_TIMEOUT_SECONDS
        < settings.LITELLM_CLIENT_TIMEOUT_SECONDS
        < settings.TRAVEL_RESEARCHER_TIMEOUT_SECONDS
        < settings.REQUEST_DEADLINE_SECONDS
    )


class _HangingClient:
    """AsyncClient stand-in whose requests never complete."""

    async def __aenter__(self) -> _HangingClient:
        return self

    async def __aexit__(self, *args: object) -> None:
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
        result = await asyncio.wait_for(
            get_weather("东京"),
            timeout=2,
        )

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


def test_web_fetch_has_internal_execution_bound() -> None:
    fetcher = _fetcher()

    assert fetcher.timeout == 30
    assert fetcher.timeout < settings.LITELLM_CLIENT_TIMEOUT_SECONDS
