"""Volcengine 豆包搜索 Global 版 Web Search tool contracts."""

from __future__ import annotations

from typing import Any

import pytest

from app.agent.tools import _timeout
from app.agent.tools.web_search import _build_request_body, search_web


def test_web_search_request_body_matches_global_api_contract() -> None:
    assert _build_request_body(
        query="故宫 预约规则",
        count=8,
        max_snippet_length=200,
    ) == {
        "Query": "故宫 预约规则",
        "DocCount": 8,
        "MaxSnippetLength": 200,
    }


def test_web_search_request_body_rejects_out_of_range_count() -> None:
    with pytest.raises(ValueError):
        _build_request_body(query="故宫", count=21, max_snippet_length=200)
    with pytest.raises(ValueError):
        _build_request_body(query="故宫", count=0, max_snippet_length=200)


def test_web_search_request_body_rejects_out_of_range_snippet_length() -> None:
    with pytest.raises(ValueError):
        _build_request_body(query="故宫", count=3, max_snippet_length=0)
    with pytest.raises(ValueError):
        _build_request_body(query="故宫", count=3, max_snippet_length=3001)


class _FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return {
            "ResponseMetadata": {"RequestId": "req-1", "Action": "", "Version": "", "Service": "", "Region": ""},
            "Result": {
                "TotalDocCount": 1,
                "Documents": [
                    {
                        "Rank": 0,
                        "Url": "https://www.dpm.org.cn/visit",
                        "Title": "故宫博物院",
                        "Snippet": [
                            {"Type": "text", "Text": "预约规则摘要"},
                            {"Type": "image", "Image": {"Width": 10, "Height": 10, "ImageUrl": "https://img.example.com/a.png", "Alt": ""}},
                            {"Type": "text", "Text": "第二段"},
                        ],
                        "DocumentInfo": {"ContentCharCount": 100, "ContentTokenCount": 50, "Filetype": "webpage", "PublishTime": "2026-08-13 09:55:00"},
                        "HostInfo": {"Hostname": "故宫博物院", "IconUrl": "", "AuthorityLevel": "very_high"},
                    }
                ],
                "ErrorCode": 0,
                "ErrorMsg": "",
            },
        }


class _FakeClient:
    last_headers: dict[str, str] | None = None
    last_json: dict[str, Any] | None = None

    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        del args

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
    ) -> _FakeResponse:
        assert url == "https://open.feedcoopapi.com/search_api/global_search"
        type(self).last_headers = headers
        type(self).last_json = json
        return _FakeResponse()


async def test_search_web_returns_host_attestable_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.agent.tools.web_search.require_tool_key", lambda _: "test-key")
    monkeypatch.setattr("app.agent.tools.web_search.httpx.AsyncClient", _FakeClient)

    result = await search_web("故宫 预约规则", authoritative=True, count=5)

    assert result == {
        "query": "故宫 预约规则",
        "result_count": 1,
        "time_cost_ms": None,
        "results": [
            {
                "title": "故宫博物院",
                "url": "https://www.dpm.org.cn/visit",
                "site_name": "故宫博物院",
                "authority": "very_high",
                "summary": "预约规则摘要\n第二段",
                "published": "2026-08-13 09:55:00",
            }
        ],
    }
    assert _FakeClient.last_headers is not None
    assert _FakeClient.last_headers["Authorization"] == "Bearer test-key"
    assert _FakeClient.last_json is not None
    assert _FakeClient.last_json == {"Query": "故宫 预约规则", "DocCount": 5, "MaxSnippetLength": 200}


class _NormalAuthorityResponse(_FakeResponse):
    def json(self) -> dict[str, Any]:
        payload = super().json()
        payload["Result"]["Documents"][0]["HostInfo"]["AuthorityLevel"] = "normal"
        return payload


class _NormalAuthorityClient(_FakeClient):
    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
    ) -> _NormalAuthorityResponse:
        assert url == "https://open.feedcoopapi.com/search_api/global_search"
        type(self).last_headers = headers
        type(self).last_json = json
        return _NormalAuthorityResponse()


async def test_search_web_authoritative_filters_normal_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.agent.tools.web_search.require_tool_key", lambda _: "test-key")
    monkeypatch.setattr("app.agent.tools.web_search.httpx.AsyncClient", _NormalAuthorityClient)

    result = await search_web("故宫 预约规则", authoritative=True, count=5)

    assert result["results"] == []


class _HangingClient:
    def __init__(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    async def __aenter__(self) -> _HangingClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        del args

    async def post(self, *args: object, **kwargs: object) -> Any:
        del args, kwargs
        import asyncio

        await asyncio.Future[None]()
        raise AssertionError("hanging search returned")


async def test_search_web_uses_shared_tool_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_timeout, "TOOL_EXECUTION_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr("app.agent.tools.web_search.require_tool_key", lambda _: "test-key")
    monkeypatch.setattr("app.agent.tools.web_search.httpx.AsyncClient", _HangingClient)

    result = await search_web("故宫")

    assert result == {"error": "联网搜索暂时失败：TimeoutError"}


class _ErrorResponse(_FakeResponse):
    def json(self) -> dict[str, Any]:
        return {
            "ResponseMetadata": {
                "RequestId": "req-2",
                "Action": "",
                "Version": "",
                "Service": "",
                "Region": "",
                "Error": {"CodeN": 10400, "Code": "10400", "Message": "query is empty"},
            },
            "Result": None,
        }


class _ErrorClient(_FakeClient):
    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
    ) -> _ErrorResponse:
        assert url == "https://open.feedcoopapi.com/search_api/global_search"
        type(self).last_headers = headers
        type(self).last_json = json
        return _ErrorResponse()


async def test_search_web_surfaces_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.agent.tools.web_search.require_tool_key", lambda _: "test-key")
    monkeypatch.setattr("app.agent.tools.web_search.httpx.AsyncClient", _ErrorClient)

    result = await search_web("故宫 预约规则")

    assert result["error"] == "联网搜索返回错误：query is empty"