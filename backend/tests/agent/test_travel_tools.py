from decimal import Decimal
from typing import cast
from unittest.mock import AsyncMock, patch

import pytest
from pydantic_ai import ToolReturn

from app.agent.tools.currency import (
    CurrencyAmount,
    convert_currency,
    convert_currency_data,
)
from app.agent.tools.search import search_web
from app.agent.tools.search_providers.base import SearchProvider, SearchResult
from app.agent.tools.search_providers.fake import FakeSearchProvider
from app.agent.tools.search_providers.fallback import FallbackSearchProvider
from app.agent.tools.weather import get_weather


@pytest.mark.asyncio
async def test_currency_conversion_uses_one_rate_for_every_amount() -> None:
    rate = AsyncMock(return_value=(Decimal("0.05"), "2026-08-14", "fake"))
    with patch("app.agent.tools.currency.get_exchange_rate", rate):
        result = await convert_currency_data(
            from_currency="日元",
            to_currency="CNY",
            amounts=[
                CurrencyAmount(name="交通", amount_min=Decimal("10000")),
                CurrencyAmount(
                    name="住宿",
                    amount_min=Decimal("20000"),
                    amount_max=Decimal("24000"),
                ),
            ],
        )

    rate.assert_awaited_once_with(base="JPY", quote="CNY")
    assert result["rate"] == 0.05
    assert result["amounts"] == [
        {
            "name": "交通",
            "from_min": 10000,
            "from_max": 10000,
            "to_min": 500,
            "to_max": 500,
        },
        {
            "name": "住宿",
            "from_min": 20000,
            "from_max": 24000,
            "to_min": 1000,
            "to_max": 1200,
        },
    ]


@pytest.mark.asyncio
async def test_currency_tool_degrades_to_text_on_provider_failure() -> None:
    with patch(
        "app.agent.tools.currency.get_exchange_rate",
        AsyncMock(side_effect=TimeoutError),
    ):
        result = await convert_currency(
            from_currency="JPY",
            amounts=[CurrencyAmount(name="预算", amount_min=Decimal("100"))],
        )

    assert result == "汇率换算暂时失败：TimeoutError"


def test_search_facade_clamps_results_and_uses_provider_contract() -> None:
    provider = FakeSearchProvider()
    with patch("app.agent.tools.search.get_search_provider", return_value=provider):
        result = search_web("东京 当前 开放", max_results=99)

    assert isinstance(result, ToolReturn)
    assert "FAKE SEARCH RESULT" in result.return_value
    assert "东京 当前 开放" in result.return_value
    assert result.metadata
    assert result.metadata[0].url == "https://example.test/search"


def test_fallback_search_uses_secondary_after_primary_failure() -> None:
    class BrokenProvider:
        name = "broken"

        def search(self, **kwargs: object) -> list[SearchResult]:
            del kwargs
            raise TimeoutError

    provider = FallbackSearchProvider(
        providers=[
            cast(SearchProvider, BrokenProvider()),
            cast(SearchProvider, FakeSearchProvider()),
        ],
    )
    result = provider.search(
        query="current policy",
        max_results=5,
        topic="general",
        search_depth="advanced",
        include_domains=None,
        exclude_domains=None,
    )

    assert result
    assert result[0].title == "[FAKE SEARCH RESULT]"


@pytest.mark.asyncio
async def test_weather_tool_degrades_when_provider_key_is_missing() -> None:
    with patch(
        "app.agent.tools.weather._weather_api_key",
        side_effect=RuntimeError("missing"),
    ):
        result = await get_weather("东京")

    assert result == "天气查询暂时失败：RuntimeError"
