from unittest.mock import AsyncMock, patch

import pytest

from app.agent.tools.weather import get_weather


@pytest.mark.asyncio
async def test_weather_tool_degrades_when_provider_key_is_missing() -> None:
    with patch(
        "app.agent.tools.weather._weather_api_key",
        side_effect=RuntimeError("missing"),
    ):
        result = await get_weather("东京")

    assert result == {
        "status": "error",
        "error_code": "UPSTREAM_ERROR",
        "message": "天气查询暂时失败：RuntimeError",
        "retryable": True,
    }


@pytest.mark.asyncio
async def test_weather_tool_preserves_city_not_found_status() -> None:
    with patch(
        "app.agent.tools.weather._get_weather",
        AsyncMock(
            return_value={
                "status": "not_found",
                "error_code": "CITY_NOT_FOUND",
                "message": "未能解析城市：不存在的城市",
            }
        ),
    ):
        result = await get_weather("不存在的城市")

    assert result == {
        "status": "not_found",
        "error_code": "CITY_NOT_FOUND",
        "message": "未能解析城市：不存在的城市",
    }
