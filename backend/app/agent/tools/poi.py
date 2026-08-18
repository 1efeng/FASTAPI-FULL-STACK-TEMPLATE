"""Amap POI 2.0 tools for structured place discovery and details."""

from __future__ import annotations

from typing import Any, Literal

import httpx

from app.agent.tools._settings import require_tool_key
from app.agent.tools._timeout import bound_tool_execution

AMAP_POI_TEXT_URL = "https://restapi.amap.com/v5/place/text"
AMAP_POI_DETAIL_URL = "https://restapi.amap.com/v5/place/detail"
AMAP_POI_AROUND_URL = "https://restapi.amap.com/v5/place/around"

_SEARCH_SHOW_FIELDS = "business"
_DETAIL_SHOW_FIELDS = "business,navi,photos"
_MAX_RESULTS = 10


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
    return {
        "error": "高德 POI 查询失败",
        "provider_info": str(payload.get("info") or "UNKNOWN"),
        "provider_code": str(payload.get("infocode") or ""),
    }


async def _get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
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
    return {"query": keywords.strip(), "region": region, "results": results}


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
        return {"error": f"POI 搜索暂时失败：{type(exc).__name__}"}


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
        return {"error": "未找到对应 POI"}

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
    return {"poi": poi}


async def get_poi_detail(poi_id: str) -> dict[str, Any]:
    """按已知 POI ID 补充营业时间、入口、电话等详情；不要为已满足筛选条件的候选逐个调用。"""
    try:
        return await bound_tool_execution(_get_poi_detail(poi_id=poi_id))
    except Exception as exc:
        return {"error": f"POI 详情查询暂时失败：{type(exc).__name__}"}


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
    return {
        "center": params["location"],
        "radius_m": radius,
        "query": normalized_keywords,
        "types": normalized_types,
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
        return {"error": f"周边 POI 搜索暂时失败：{type(exc).__name__}"}
