"""QWeather-backed current weather tool.

Uses the same configured host for geo lookup and weather queries. The free
``devapi`` host serves both ``/geo/v2/city/lookup`` and ``/v7/weather/*``;
a paid/enterprise host (``QWEATHER_API_HOST``, e.g. ``*.re.qweatherapi.com``)
serves the same paths under its own domain.
"""

from __future__ import annotations

import httpx

from app.agent.tools._timeout import bound_tool_execution
from app.core.config import settings


def _weather_api_key() -> str:
    if settings.QWEATHER_API_KEY:
        return settings.QWEATHER_API_KEY
    if settings.WEATHER_API_KEY:
        return settings.WEATHER_API_KEY
    raise RuntimeError("缺少环境变量 QWEATHER_API_KEY / WEATHER_API_KEY")


def _weather_host() -> str:
    return settings.QWEATHER_API_HOST.rstrip("/")


async def _geo_lookup(city: str, client: httpx.AsyncClient) -> str | None:
    response = await client.get(
        f"{_weather_host()}/geo/v2/city/lookup",
        params={"location": city, "key": _weather_api_key()},
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") == "200" and payload.get("location"):
        return str(payload["location"][0]["id"])
    return None


async def _get_weather(city: str, forecast: bool = False) -> str:
    key = _weather_api_key()
    async with httpx.AsyncClient(timeout=10.0) as client:
        location_id = await _geo_lookup(city, client)
        if not location_id:
            return f"未能解析城市：{city}"

        now_response = await client.get(
            f"{_weather_host()}/v7/weather/now",
            params={"location": location_id, "key": key},
        )
        now_response.raise_for_status()
        now_payload = now_response.json()
        if now_payload.get("code") != "200":
            return f"查询天气失败：{now_payload.get('code')}"

        now = now_payload.get("now", {})
        lines = [
            f"{city} 当前天气：{now.get('text', '未知')}，"
            f"{now.get('temp', '?')}℃（体感 {now.get('feelsLike', '?')}℃），"
            f"湿度 {now.get('humidity', '?')}%，风向 {now.get('windDir', '?')}。"
        ]
        if forecast:
            forecast_response = await client.get(
                f"{_weather_host()}/v7/weather/3d",
                params={"location": location_id, "key": key},
            )
            forecast_response.raise_for_status()
            forecast_payload = forecast_response.json()
            if forecast_payload.get("code") == "200":
                lines.append("\n未来 3 天预报：")
                for day in forecast_payload.get("daily", []):
                    lines.append(
                        f"- {day.get('fxDate')}: {day.get('textDay')}，"
                        f"{day.get('tempMin')}~{day.get('tempMax')}℃"
                    )
        return "\n".join(lines)


async def get_weather(city: str, forecast: bool = False) -> str:
    """查询当前天气；仅在未来三天确实影响计划时请求 forecast。

    超过三天的旅行不得把短期预报当作届时天气，应改查季节气候或说明尚不可预测。
    """
    try:
        return await bound_tool_execution(
            _get_weather(city=city, forecast=forecast)
        )
    except Exception as exc:
        return f"天气查询暂时失败：{type(exc).__name__}"
