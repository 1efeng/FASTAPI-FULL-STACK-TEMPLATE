"""Amap POI 2.0 tools for structured place discovery and details."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

import httpx

from app.agent.tools._settings import require_tool_key
from app.agent.tools._timeout import bound_tool_execution
from app.core.config import settings

AMAP_POI_TEXT_URL = "https://restapi.amap.com/v5/place/text"
AMAP_POI_DETAIL_URL = "https://restapi.amap.com/v5/place/detail"
AMAP_POI_AROUND_URL = "https://restapi.amap.com/v5/place/around"

_SEARCH_SHOW_FIELDS = "business"
_DETAIL_SHOW_FIELDS = "business,navi,photos"
_MAX_RESULTS = 10

# Amap POI Web Service quota (keyword/nearby/polygon/ID query): 100 req/day for
# individual developers, 1000 req/day for enterprise
# (https://lbs.amap.com/api/webservice/guide/tools/flowlevel). The signal below
# throttles parallel model tool-calls so a burst does not exhaust the daily quota
# or trip per-Key QPS, which is not a published constant and must be read from
# https://console.amap.com/dev/flow/manage. Defaults come from config and can be
# overridden via POI_TOOL_CONCURRENCY_LIMIT / POI_TOOL_MAX_ATTEMPTS.
_POI_CONCURRENCY_LIMIT: int = settings.POI_TOOL_CONCURRENCY_LIMIT
_POI_SEMAPHORE = asyncio.Semaphore(_POI_CONCURRENCY_LIMIT)
_POI_MAX_ATTEMPTS: int = settings.POI_TOOL_MAX_ATTEMPTS
_POI_RETRY_BASE_SECONDS = 1.0
_POI_RETRY_BACKOFF = 2.0


def _tool_error(
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


def _exception_error(prefix: str, exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, ValueError):
        return _tool_error(code="INVALID_INPUT", message=str(exc))
    if isinstance(exc, (httpx.TimeoutException, TimeoutError)):
        return _tool_error(
            code="PROVIDER_TIMEOUT",
            message=f"{prefix}暂时超时：{type(exc).__name__}",
            retryable=True,
        )
    if isinstance(exc, RuntimeError) and "缺少环境变量" in str(exc):
        return _tool_error(
            code="AUTHENTICATION_ERROR",
            message=f"{prefix}配置不可用",
        )
    return _tool_error(
        code="UPSTREAM_ERROR",
        message=f"{prefix}暂时失败：{type(exc).__name__}",
        retryable=True,
    )


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized or None


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _validate_keywords(keywords: str) -> str:
    normalized = keywords.strip()
    if not normalized or len(normalized) > 80:
        raise ValueError("keywords 长度必须为 1~80 个字符")
    return normalized


def _validate_limit(limit: int) -> int:
    if not 1 <= limit <= _MAX_RESULTS:
        raise ValueError(f"limit 必须为 1~{_MAX_RESULTS}")
    return limit


def _validate_location(location: str) -> str:
    parts = [part.strip() for part in location.split(",")]
    if len(parts) != 2:
        raise ValueError("location 必须为 '经度,纬度'")
    try:
        longitude = float(parts[0])
        latitude = float(parts[1])
    except ValueError as exc:
        raise ValueError("location 必须为有效经纬度") from exc
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        raise ValueError("location 经纬度超出合法范围")
    return f"{longitude:.6f},{latitude:.6f}"


def _business_fields(item: dict[str, Any]) -> dict[str, Any]:
    business = item.get("business")
    if not isinstance(business, dict):
        return {}
    result: dict[str, Any] = {}
    for key in ("business_area", "tel", "tag", "parking_type", "alias", "opentime_today", "opentime_week"):
        if value := _clean_text(business.get(key)):
            result[key] = value
    if (rating := _number(business.get("rating"))) is not None:
        result["rating"] = rating
    if (cost := _number(business.get("cost"))) is not None:
        result["cost"] = cost
    return result


def _base_poi(item: dict[str, Any], *, include_distance: bool = False) -> dict[str, Any]:
    poi: dict[str, Any] = {}
    for source, target in (
        ("id", "id"),
        ("name", "name"),
        ("location", "location"),
        ("address", "address"),
        ("type", "type"),
        ("typecode", "typecode"),
        ("pname", "province"),
        ("cityname", "city"),
        ("adname", "district"),
    ):
        if value := _clean_text(item.get(source)):
            poi[target] = value
    poi.update(_business_fields(item))
    if include_distance:
        distance = _number(item.get("distance"))
        if distance is not None:
            poi["distance_m"] = int(distance)
    return poi


def _provider_error(payload: dict[str, Any]) -> dict[str, Any] | None:
    if payload.get("status") == "1":
        return None
    info = str(payload.get("info") or "UNKNOWN")
    infocode = str(payload.get("infocode") or "")
    normalized_info = info.upper()
    if infocode == "10021" or "LIMIT" in normalized_info:
        code, retryable = "RATE_LIMITED", True
    elif "KEY" in normalized_info or "AUTH" in normalized_info:
        code, retryable = "AUTHENTICATION_ERROR", False
    else:
        code, retryable = "UPSTREAM_ERROR", True
    return {
        "status": "error",
        "error_code": code,
        "message": "高德 POI 查询失败",
        "provider_info": info,
        "provider_code": infocode,
        "retryable": retryable,
    }


async def _get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
    """GET 一个高德 JSON 接口，受并发信号量节流，并在命中限流时自动重试。

    重试识别依据：请求已发到高德且返回 ``RATE_LIMITED`` 错误 payload
    （``infocode=10021`` 或 info 含 LIMIT）。退避叠加在真实网络调用之间，
    因此每次都完整经过信号量 acquire/release，保证并发上限始终生效。
    """
    for attempt in range(_POI_MAX_ATTEMPTS):
        async with _POI_SEMAPHORE:
            payload = await _fetch_once(url, params)
        # 仅对已确认为限流的错误重试；成功或其他错误直接返回。
        if not _is_rate_limited(payload):
            return payload
        if attempt + 1 < _POI_MAX_ATTEMPTS:
            await asyncio.sleep(_POI_RETRY_BASE_SECONDS * (_POI_RETRY_BACKOFF**attempt))
    return payload


def _is_rate_limited(payload: dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    info = str(payload.get("info") or "").upper()
    infocode = str(payload.get("infocode") or "")
    return infocode == "10021" or "LIMIT" in info


async def _fetch_once(url: str, params: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        return {"error": "高德 POI 返回格式异常"}
    return payload


async def _search_poi(
    *,
    keywords: str,
    region: str | None,
    strict_region: bool,
    limit: int,
) -> dict[str, Any]:
    key = require_tool_key("AMAP_API_KEY")
    params: dict[str, Any] = {
        "key": key,
        "keywords": _validate_keywords(keywords),
        "page_size": _validate_limit(limit),
        "page_num": 1,
        "show_fields": _SEARCH_SHOW_FIELDS,
    }
    if region:
        params["region"] = region.strip()
        params["city_limit"] = "true" if strict_region else "false"

    payload = await _get_json(AMAP_POI_TEXT_URL, params)
    if error := _provider_error(payload):
        return error
    results = [
        _base_poi(item)
        for item in payload.get("pois") or []
        if isinstance(item, dict)
    ]
    if not results:
        return {
            "status": "not_found",
            "error_code": "POI_NOT_FOUND",
            "query": keywords.strip(),
            "region": region,
            "result_count": 0,
            "selection_required": False,
            "results": [],
        }
    return {
        "status": "ok",
        "query": keywords.strip(),
        "region": region,
        "result_count": len(results),
        "selection_required": len(results) > 1,
        "results": results,
    }


async def search_poi(
    keywords: str,
    region: str | None = None,
    strict_region: bool = False,
    limit: int = 5,
) -> dict[str, Any]:
    """按名称或关键词搜索 POI，返回 ID、坐标、地址、评分/人均等紧凑信息；字段已足够时不要再查详情。"""
    try:
        return await bound_tool_execution(
            _search_poi(
                keywords=keywords,
                region=region,
                strict_region=strict_region,
                limit=limit,
            )
        )
    except Exception as exc:
        return _exception_error("POI 搜索", exc)


async def _get_poi_detail(*, poi_id: str) -> dict[str, Any]:
    normalized_id = poi_id.strip()
    if not normalized_id or "|" in normalized_id or len(normalized_id) > 64:
        raise ValueError("poi_id 格式无效")
    payload = await _get_json(
        AMAP_POI_DETAIL_URL,
        {
            "key": require_tool_key("AMAP_API_KEY"),
            "id": normalized_id,
            "show_fields": _DETAIL_SHOW_FIELDS,
        },
    )
    if error := _provider_error(payload):
        return error
    pois = [item for item in payload.get("pois") or [] if isinstance(item, dict)]
    if not pois:
        return {
            "status": "not_found",
            "error_code": "POI_NOT_FOUND",
            "message": "未找到对应 POI",
        }

    item = pois[0]
    poi = _base_poi(item)
    navi = item.get("navi")
    if isinstance(navi, dict):
        navigation = {
            key: value
            for key in ("entr_location", "exit_location", "gridcode")
            if (value := _clean_text(navi.get(key)))
        }
        if navigation:
            poi["navigation"] = navigation

    photos: list[dict[str, str]] = []
    for photo in item.get("photos") or []:
        if not isinstance(photo, dict):
            continue
        url = _clean_text(photo.get("url"))
        if not url:
            continue
        row = {"url": url}
        if title := _clean_text(photo.get("title")):
            row["title"] = title
        photos.append(row)
        if len(photos) >= 3:
            break
    if photos:
        poi["photos"] = photos
    return {"status": "ok", "poi": poi}


async def get_poi_detail(poi_id: str) -> dict[str, Any]:
    """按已知 POI ID 补充营业时间、入口、电话等详情；不要为已满足筛选条件的候选逐个调用。"""
    try:
        return await bound_tool_execution(_get_poi_detail(poi_id=poi_id))
    except Exception as exc:
        return _exception_error("POI 详情查询", exc)


async def _search_nearby(
    *,
    location: str,
    keywords: str | None,
    types: str | None,
    radius: int,
    limit: int,
    sort_by: Literal["distance", "weight"],
    region: str | None,
) -> dict[str, Any]:
    if not 0 <= radius <= 50_000:
        raise ValueError("radius 必须在 0~50000 米之间")
    normalized_keywords = _validate_keywords(keywords) if keywords is not None else None
    normalized_types = types.strip() if isinstance(types, str) and types.strip() else None
    params: dict[str, Any] = {
        "key": require_tool_key("AMAP_API_KEY"),
        "location": _validate_location(location),
        "radius": radius,
        "sortrule": sort_by,
        "page_size": _validate_limit(limit),
        "page_num": 1,
        "show_fields": _SEARCH_SHOW_FIELDS,
    }
    if normalized_keywords:
        params["keywords"] = normalized_keywords
    if normalized_types:
        params["types"] = normalized_types
    if region:
        params["region"] = region.strip()

    payload = await _get_json(AMAP_POI_AROUND_URL, params)
    if error := _provider_error(payload):
        return error
    results = [
        _base_poi(item, include_distance=True)
        for item in payload.get("pois") or []
        if isinstance(item, dict)
    ]
    if not results:
        return {
            "status": "not_found",
            "error_code": "POI_NOT_FOUND",
            "center": params["location"],
            "radius_m": radius,
            "query": normalized_keywords,
            "types": normalized_types,
            "result_count": 0,
            "selection_required": False,
            "results": [],
        }
    return {
        "status": "ok",
        "center": params["location"],
        "radius_m": radius,
        "query": normalized_keywords,
        "types": normalized_types,
        "result_count": len(results),
        "selection_required": len(results) > 1,
        "results": results,
    }


async def search_nearby(
    location: str,
    keywords: str | None = None,
    types: str | None = None,
    radius: int = 3000,
    limit: int = 5,
    sort_by: Literal["distance", "weight"] = "distance",
    region: str | None = None,
) -> dict[str, Any]:
    """按中心坐标搜索附近 POI，直接返回距离、评分、人均；这些字段足够回答时应立即停止。"""
    try:
        return await bound_tool_execution(
            _search_nearby(
                location=location,
                keywords=keywords,
                types=types,
                radius=radius,
                limit=limit,
                sort_by=sort_by,
                region=region,
            )
        )
    except Exception as exc:
        return _exception_error("周边 POI 搜索", exc)
