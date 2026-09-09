from __future__ import annotations

import json
from collections.abc import Coroutine
from typing import Any

import httpx
import pytest

from app.agent.tools.web_search import _search_one, web_search


@pytest.mark.asyncio
async def test_search_one_uses_tavily_contract_and_truncates_snippet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        observed["authorization"] = request.headers.get("Authorization")
        observed["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "北京最新消息",
                        "url": "https://example.com/news",
                        "score": 0.9,
                        "content": "新" * 150,
                    }
                ]
            },
        )

    monkeypatch.setattr(
        "app.agent.tools.web_search.require_tool_key",
        lambda name: "tvly-test" if name == "TAVILY_API_KEY" else "",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await _search_one("北京 今日 新闻", client)

    assert observed == {
        "authorization": "Bearer tvly-test",
        "payload": {
            "query": "北京 今日 新闻",
            "search_depth": "basic",
            "include_answer": False,
            "include_raw_content": False,
            "max_results": 5,
        },
    }
    assert result["results"] == [
        {
            "title": "北京最新消息",
            "url": "https://example.com/news",
            "score": 0.9,
            "snippet": "新" * 100,
        }
    ]


@pytest.mark.asyncio
async def test_web_search_requires_at_least_one_query() -> None:
    assert await web_search([]) == [
        {"query": "", "error": "至少需要一条搜索词", "results": []}
    ]


@pytest.mark.asyncio
async def test_web_search_degrades_the_whole_batch_on_hard_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def timeout(coro: Coroutine[Any, Any, object]) -> object:
        coro.close()
        raise TimeoutError

    monkeypatch.setattr("app.agent.tools.web_search.bound_tool_execution", timeout)

    assert await web_search(["北京新闻", "北京政策"]) == [
        {"query": "北京新闻", "error": "联网搜索暂时超时", "results": []},
        {"query": "北京政策", "error": "联网搜索暂时超时", "results": []},
    ]
