"""Amap route tool for driving and public transit."""

from __future__ import annotations

from typing import Literal

import httpx

from app.agent.tools._settings import require_tool_key
from app.agent.tools._timeout import bound_tool_execution

AMAP_HOST = "https://restapi.amap.com"


async def _geocode(
    address: str,
    client: httpx.AsyncClient,
) -> dict[str, str] | None:
    response = await client.get(
        f"{AMAP_HOST}/v3/geocode/geo",
        params={"address": address, "key": require_tool_key("AMAP_API_KEY")},
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("status") == "1" and payload.get("geocodes"):
        geocode = payload["geocodes"][0]
        return {
            "location": str(geocode["location"]),
            "city": str(geocode.get("city") or ""),
        }
    return None


async def _get_route(
    origin: str,
    destination: str,
    mode: Literal["driving", "transit"] = "driving",
) -> str:
    key = require_tool_key("AMAP_API_KEY")
    async with httpx.AsyncClient(timeout=10.0) as client:
        start = await _geocode(origin, client)
        end = await _geocode(destination, client)
        if not start or not end:
            return "未能解析起点或终点的经纬度。"

        if mode == "transit":
            response = await client.get(
                f"{AMAP_HOST}/v3/direction/transit",
                params={
                    "origin": start["location"],
                    "destination": end["location"],
                    "city": start["city"],
                    "key": key,
                },
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("status") != "1":
                return f"公交路线查询失败：{payload.get('info')}"
            transit = payload["route"]["transits"][0]
            duration = int(transit["duration"]) / 60
            walking = int(transit.get("walking_distance", 0)) / 1000
            cost = transit.get("cost")
            return (
                f"{origin} → {destination}（公交）\n"
                f"预计 {duration:.0f} 分钟，费用 {cost} 元，步行 {walking:.1f} 公里"
            )

        response = await client.get(
            f"{AMAP_HOST}/v3/direction/driving",
            params={
                "origin": start["location"],
                "destination": end["location"],
                "key": key,
            },
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != "1":
            return f"驾车路线查询失败：{payload.get('info')}"

        path = payload["route"]["paths"][0]
        distance = int(path["distance"]) / 1000
        duration = int(path["duration"]) / 60
        return (
            f"{origin} → {destination}（驾车）\n"
            f"距离：{distance:.1f} 公里，预计 {duration:.0f} 分钟"
        )


async def search_maps(
    origin: str,
    destination: str,
    mode: Literal["driving", "transit"] = "driving",
) -> str:
    """查询两个地点之间的路线、距离与预计耗时。"""
    try:
        return await bound_tool_execution(
            _get_route(
                origin=origin,
                destination=destination,
                mode=mode,
            )
        )
    except Exception as exc:
        return f"路线查询暂时失败：{type(exc).__name__}"
