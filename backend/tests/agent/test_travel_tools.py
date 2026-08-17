from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.agent.tools.currency import (
    CurrencyAmount,
    convert_currency,
    convert_currency_data,
)
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


@pytest.mark.asyncio
async def test_weather_tool_degrades_when_provider_key_is_missing() -> None:
    with patch(
        "app.agent.tools.weather._weather_api_key",
        side_effect=RuntimeError("missing"),
    ):
        result = await get_weather("东京")

    assert result == "天气查询暂时失败：RuntimeError"
