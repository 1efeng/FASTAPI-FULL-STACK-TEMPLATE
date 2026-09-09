"""Amap POI 2.0 tool contracts."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.agent.tools.poi import get_poi_detail, search_nearby, search_poi


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeClient:
    calls: list[tuple[str, dict[str, Any]]] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        del args

    async def get(self, url: str, *, params: dict[str, Any]) -> _FakeResponse:
        type(self).calls.append((url, params))
        if url.endswith("/v5/place/text"):
            return _FakeResponse(
                {
                    "status": "1",
                    "pois": [
                        {
                            "id": "B000A8UIN8",
                            "name": "故宫博物院",
                            "location": "116.397029,39.917839",
                            "address": "景山前街4号",
                            "type": "风景名胜;风景名胜相关;旅游景点",
                            "typecode": "110201",
                            "pname": "北京市",
                            "cityname": "北京市",
                            "adname": "东城区",
                            "business": {"rating": "4.9", "tel": "4009501925"},
                        }
                    ],
                }
            )
        if url.endswith("/v5/place/detail"):
            return _FakeResponse(
                {
                    "status": "1",
                    "pois": [
                        {
                            "id": "B000A8UIN8",
                            "name": "故宫博物院",
                            "location": "116.397029,39.917839",
                            "address": "景山前街4号",
                            "business": {
                                "rating": "4.9",
                                "tel": "4009501925",
                                "opentime_week": "周二至周日 08:30-17:00",
                            },
                            "navi": {
                                "entr_location": "116.397100,39.916900",
                                "exit_location": "116.396900,39.925000",
                            },
                            "photos": [
                                {"title": "午门", "url": "https://img.example/1.jpg"},
                                {"title": "太和殿", "url": "https://img.example/2.jpg"},
                                {"title": "角楼", "url": "https://img.example/3.jpg"},
                                {"title": "不应返回", "url": "https://img.example/4.jpg"},
                            ],
                        }
                    ],
                }
            )
        if url.endswith("/v5/place/around"):
            return _FakeResponse(
                {
                    "status": "1",
                    "pois": [
                        {
                            "id": "B0FFG9V1R9",
                            "name": "四季民福烤鸭店(故宫店)",
                            "location": "116.402000,39.918000",
                            "address": "南池子大街",
                            "distance": "620",
                            "business": {"rating": "4.7", "cost": "181.00"},
                        }
                    ],
                }
            )
        raise AssertionError(f"unexpected URL: {url}")


@pytest.fixture(autouse=True)
def _fake_amap(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeClient.calls = []
    monkeypatch.setattr("app.agent.tools.poi.require_tool_key", lambda _: "test-key")
    monkeypatch.setattr("app.agent.tools.poi.httpx.AsyncClient", _FakeClient)


async def test_search_poi_returns_compact_structured_place_data() -> None:
    result = await search_poi("故宫博物院", region="北京", strict_region=True, limit=3)

    assert result["status"] == "ok"
    assert result["result_count"] == 1
    assert result["selection_required"] is False
    assert result["query"] == "故宫博物院"
    assert result["results"] == [
        {
            "id": "B000A8UIN8",
            "name": "故宫博物院",
            "location": "116.397029,39.917839",
            "address": "景山前街4号",
            "type": "风景名胜;风景名胜相关;旅游景点",
            "typecode": "110201",
            "province": "北京市",
            "city": "北京市",
            "district": "东城区",
            "tel": "4009501925",
            "rating": 4.9,
        }
    ]
    _, params = _FakeClient.calls[-1]
    assert params["page_size"] == 3
    assert params["region"] == "北京"
    assert params["city_limit"] == "true"
    assert params["show_fields"] == "business"


async def test_search_poi_marks_multiple_candidates_for_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _multiple_results(*args: object, **kwargs: object) -> dict[str, Any]:
        del args, kwargs
        return {
            "status": "1",
            "pois": [
                {"id": "A", "name": "同名地点 1", "cityname": "北京市"},
                {"id": "B", "name": "同名地点 2", "cityname": "北京市"},
            ],
        }

    monkeypatch.setattr("app.agent.tools.poi._get_json", _multiple_results)
    result = await search_poi("同名地点", region="北京")

    assert result["status"] == "ok"
    assert result["result_count"] == 2
    assert result["selection_required"] is True


async def test_search_poi_marks_empty_results_as_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _empty_results(*args: object, **kwargs: object) -> dict[str, Any]:
        del args, kwargs
        return {"status": "1", "pois": []}

    monkeypatch.setattr("app.agent.tools.poi._get_json", _empty_results)
    result = await search_poi("不存在的地点", region="北京")

    assert result == {
        "status": "not_found",
        "error_code": "POI_NOT_FOUND",
        "query": "不存在的地点",
        "region": "北京",
        "result_count": 0,
        "selection_required": False,
        "results": [],
    }


async def test_get_poi_detail_returns_business_navigation_and_limited_photos() -> None:
    result = await get_poi_detail("B000A8UIN8")

    assert result["status"] == "ok"
    poi = result["poi"]
    assert poi["name"] == "故宫博物院"
    assert poi["rating"] == 4.9
    assert poi["opentime_week"] == "周二至周日 08:30-17:00"
    assert poi["navigation"]["entr_location"] == "116.397100,39.916900"
    assert len(poi["photos"]) == 3
    _, params = _FakeClient.calls[-1]
    assert params["show_fields"] == "business,navi,photos"


async def test_search_nearby_returns_distance_rating_and_cost() -> None:
    result = await search_nearby(
        "116.397029,39.917839",
        keywords="北京菜",
        radius=3000,
        limit=3,
    )

    assert result["status"] == "ok"
    assert result["result_count"] == 1
    assert result["selection_required"] is False
    assert result["center"] == "116.397029,39.917839"
    assert result["results"] == [
        {
            "id": "B0FFG9V1R9",
            "name": "四季民福烤鸭店(故宫店)",
            "location": "116.402000,39.918000",
            "address": "南池子大街",
            "rating": 4.7,
            "cost": 181.0,
            "distance_m": 620,
        }
    ]
    _, params = _FakeClient.calls[-1]
    assert params["radius"] == 3000
    assert params["page_size"] == 3
    assert params["sortrule"] == "distance"


async def test_invalid_location_fails_closed_without_provider_call() -> None:
    result = await search_nearby("not-a-location", keywords="餐厅")

    assert result == {
        "status": "error",
        "error_code": "INVALID_INPUT",
        "message": "location 必须为 '经度,纬度'",
        "retryable": False,
    }
    assert _FakeClient.calls == []


async def test_rate_limited_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """命中高德限流(infocode=10021)时自动重试，最终返回成功结果。"""
    calls: list[str] = []

    async def _flaky(*args: object, **kwargs: object) -> dict[str, Any]:
        del args, kwargs
        calls.append("call")
        if len(calls) < 3:  # 前两次限流，第三次成功
            return {
                "status": "0",
                "info": "QUOTA_RUN_QUOTA_LIMIT",
                "infocode": "10021",
            }
        return {"status": "1", "pois": [{"id": "A", "name": "故宫博物院"}]}

    # 注入最内层真实网络调用 _fetch_once，让 _get_json 的信号量+重试逻辑真实执行。
    monkeypatch.setattr("app.agent.tools.poi._fetch_once", _flaky)
    result = await search_poi("故宫博物院", region="北京")

    assert result["status"] == "ok"
    assert len(calls) >= 3  # 至少触发两次重试


async def test_rate_limited_exhausts_retries_and_returns_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """持续限流时，重试耗尽后返回可重试的限流错误，而不是抛异常。"""
    async def _always_limited(*args: object, **kwargs: object) -> dict[str, Any]:
        del args, kwargs
        return {
            "status": "0",
            "info": "QUOTA_RUN_QUOTA_LIMIT",
            "infocode": "10021",
        }

    monkeypatch.setattr("app.agent.tools.poi._fetch_once", _always_limited)
    result = await search_poi("故宫博物院", region="北京")

    assert result["status"] == "error"
    assert result["error_code"] == "RATE_LIMITED"
    assert result["retryable"] is True


async def test_concurrent_search_poi_requests_are_semaphore_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """并发发起多个 POI 搜索时，同一时刻进行中的底层请求不超过并发上限。"""
    active: list[int] = []
    max_active = 0
    lock = asyncio.Lock()

    async def _slow(*args: object, **kwargs: object) -> dict[str, Any]:
        del args, kwargs
        nonlocal max_active
        async with lock:
            active.append(1)
            max_active = max(max_active, len(active))
        await asyncio.sleep(0.05)
        async with lock:
            active.pop()
        return {"status": "1", "pois": [{"id": "A", "name": "故宫博物院"}]}

    from app.agent.tools.poi import _POI_CONCURRENCY_LIMIT

    # 注入最内层 _fetch_once：真实走 _get_json 的信号量，观测底层并发度。
    monkeypatch.setattr("app.agent.tools.poi._fetch_once", _slow)
    # 用 6 个并发搜索压测，确认并发数被信号量限制在上限内
    results = await asyncio.gather(
        *[
            search_poi("故宫博物院", region="北京", limit=1)
            for _ in range(6)
        ]
    )

    assert all(r["status"] == "ok" for r in results)
    assert max_active <= _POI_CONCURRENCY_LIMIT
