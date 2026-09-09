"""Amap route tool backed by Amap Route Planning 2.0."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Literal

import httpx

from app.agent.tools._settings import require_tool_key
from app.agent.tools._timeout import bound_tool_execution

AMAP_HOST = "https://restapi.amap.com"
AMAP_GEOCODE_URL = f"{AMAP_HOST}/v3/geocode/geo"
AMAP_DRIVING_URL = f"{AMAP_HOST}/v5/direction/driving"
AMAP_TRANSIT_URL = f"{AMAP_HOST}/v5/direction/transit/integrated"
_GEOCODE_CACHE_MAX_SIZE = 256
_GEOCODE_CACHE: OrderedDict[tuple[str, str], dict[str, str]] = OrderedDict()


class _AmapRouteError(RuntimeError):
    """A provider response that cannot produce a usable route."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "ROUTE_UNAVAILABLE",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def _route_error(
    *,
    code: str,
    message: str,
    retryable: bool = False,
) -> dict[str, Any]:
    return {
        "status": "error",
        "error_code": code,
        "message": message,
        "retryable": retryable,
    }


def _require_success(payload: Any, action: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise _AmapRouteError(f"{action}失败：高德返回格式异常")
    if payload.get("status") != "1":
        info = str(payload.get("info") or "UNKNOWN")
        infocode = str(payload.get("infocode") or "")
        suffix = f"（{infocode}）" if infocode else ""
        normalized_info = info.upper()
        if infocode == "10021" or "LIMIT" in normalized_info:
            raise _AmapRouteError(
                f"{action}失败：{info}{suffix}",
                code="RATE_LIMITED",
                retryable=True,
            )
        if "KEY" in normalized_info or "AUTH" in normalized_info:
            raise _AmapRouteError(
                f"{action}失败：{info}{suffix}",
                code="AUTHENTICATION_ERROR",
            )
        if "NO_ROUTE" in normalized_info or "NO ROUTE" in normalized_info:
            raise _AmapRouteError(
                f"{action}失败：{info}{suffix}",
                code="ROUTE_UNAVAILABLE",
            )
        raise _AmapRouteError(
            f"{action}失败：{info}{suffix}",
            code="UPSTREAM_ERROR",
            retryable=True,
        )
    return payload


def _first_record(value: Any, action: str) -> dict[str, Any]:
    if not isinstance(value, list) or not value or not isinstance(value[0], dict):
        raise _AmapRouteError(f"{action}失败：未找到可用结果")
    return value[0]


def _minutes(value: Any, action: str) -> float:
    try:
        return float(value) / 60
    except (TypeError, ValueError) as exc:
        raise _AmapRouteError(f"{action}失败：高德返回的时长无效") from exc


def _kilometres(value: Any, action: str) -> float:
    try:
        return float(value) / 1000
    except (TypeError, ValueError) as exc:
        raise _AmapRouteError(f"{action}失败：高德返回的距离无效") from exc


def _optional_kilometres(value: Any, action: str) -> float | None:
    if value is None or value == "" or value == []:
        return None
    return _kilometres(value, action)


async def _geocode(
    address: str,
    client: httpx.AsyncClient,
    city_hint: str | None = None,
) -> dict[str, str]:
    normalized_address = address.strip()
    normalized_city = city_hint.strip() if city_hint else ""
    cache_key = (normalized_address, normalized_city)
    if cached := _GEOCODE_CACHE.get(cache_key):
        _GEOCODE_CACHE.move_to_end(cache_key)
        return dict(cached)

    params = {
        "address": normalized_address,
        "key": require_tool_key("AMAP_API_KEY"),
    }
    if normalized_city:
        params["city"] = normalized_city
    response = await client.get(
        AMAP_GEOCODE_URL,
        params=params,
    )
    response.raise_for_status()
    payload = _require_success(response.json(), f"地理编码“{address}”")
    geocode = _first_record(payload.get("geocodes"), f"地理编码“{address}”")
    location = str(geocode.get("location") or "")
    city_id = str(
        geocode.get("citycode") or geocode.get("adcode") or geocode.get("city") or ""
    )
    city_name = str(geocode.get("city") or geocode.get("province") or "")
    if not location:
        raise _AmapRouteError(f"地理编码“{address}”失败：未返回坐标")
    if not city_id:
        raise _AmapRouteError(f"地理编码“{address}”失败：未返回城市编码")
    result = {"location": location, "city_id": city_id, "city_name": city_name}
    _GEOCODE_CACHE[cache_key] = result
    _GEOCODE_CACHE.move_to_end(cache_key)
    if len(_GEOCODE_CACHE) > _GEOCODE_CACHE_MAX_SIZE:
        _GEOCODE_CACHE.popitem(last=False)
    return dict(result)


async def _get_route(
    origin: str,
    destination: str,
    mode: Literal["driving", "transit"] = "driving",
    city: str | None = None,
) -> dict[str, Any]:
    key = require_tool_key("AMAP_API_KEY")
    async with httpx.AsyncClient(timeout=10.0) as client:
        start = await _geocode(origin, client, city)
        inferred_city = city or start["city_name"] or start["city_id"]
        end = await _geocode(destination, client, inferred_city)

        if mode == "transit":
            response = await client.get(
                AMAP_TRANSIT_URL,
                params={
                    "origin": start["location"],
                    "destination": end["location"],
                    "city1": start["city_id"],
                    "city2": end["city_id"],
                    "show_fields": "cost",
                    "key": key,
                },
            )
            response.raise_for_status()
            payload = _require_success(response.json(), "公交路线查询")
            route = payload.get("route")
            if not isinstance(route, dict):
                raise _AmapRouteError("公交路线查询失败：高德返回格式异常")
            transit = _first_record(route.get("transits"), "公交路线查询")
            cost = transit.get("cost")
            if not isinstance(cost, dict):
                raise _AmapRouteError("公交路线查询失败：高德未返回费用与时长")
            duration = _minutes(cost.get("duration"), "公交路线查询")
            walking = _optional_kilometres(
                transit.get("walking_distance", 0),
                "公交路线查询",
            )
            transit_fee = cost.get("transit_fee")
            return {
                "status": "ok",
                "origin": origin,
                "destination": destination,
                "mode": "transit",
                "duration_minutes": round(duration),
                "transit_fee_cny": transit_fee,
                "walking_distance_km": round(walking, 1) if walking is not None else None,
            }

        response = await client.get(
            AMAP_DRIVING_URL,
            params={
                "origin": start["location"],
                "destination": end["location"],
                "show_fields": "cost",
                "key": key,
            },
        )
        response.raise_for_status()
        payload = _require_success(response.json(), "驾车路线查询")
        route = payload.get("route")
        if not isinstance(route, dict):
            raise _AmapRouteError("驾车路线查询失败：高德返回格式异常")
        path = _first_record(route.get("paths"), "驾车路线查询")
        cost = path.get("cost")
        if not isinstance(cost, dict):
            raise _AmapRouteError("驾车路线查询失败：高德未返回费用与时长")
        distance = _kilometres(path.get("distance"), "驾车路线查询")
        duration = _minutes(cost.get("duration"), "驾车路线查询")
        return {
            "status": "ok",
            "origin": origin,
            "destination": destination,
            "mode": "driving",
            "distance_km": round(distance, 1),
            "duration_minutes": round(duration),
        }


async def search_maps(
    origin: str,
    destination: str,
    mode: Literal["driving", "transit"] = "driving",
    city: str | None = None,
) -> dict[str, Any]:
    """查询同一城市内两处地点的路线；提供 city 可避免同名地点误匹配。"""
    try:
        return await bound_tool_execution(
            _get_route(
                origin=origin,
                destination=destination,
                mode=mode,
                city=city,
            )
        )
    except ValueError as exc:
        return _route_error(code="INVALID_INPUT", message=str(exc))
    except _AmapRouteError as exc:
        return _route_error(
            code=exc.code,
            message=str(exc),
            retryable=exc.retryable,
        )
    except (httpx.TimeoutException, TimeoutError) as exc:
        return _route_error(
            code="PROVIDER_TIMEOUT",
            message=f"路线查询暂时超时：{type(exc).__name__}",
            retryable=True,
        )
    except Exception as exc:
        return _route_error(
            code="UPSTREAM_ERROR",
            message=f"路线查询暂时失败：{type(exc).__name__}",
            retryable=True,
        )
