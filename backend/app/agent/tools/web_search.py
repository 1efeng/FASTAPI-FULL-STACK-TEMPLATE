"""Domain-neutral Tavily Web Search tool owned by the Agent host."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from app.agent.tools._settings import require_tool_key
from app.agent.tools._timeout import bound_tool_execution

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
_SEARCH_RESULT_LIMIT = 5
_SNIPPET_MAX_CHARS = 100


def _normalize_result(result: dict[str, Any]) -> dict[str, Any] | None:
    url = result.get("url")
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return None
    content = result.get("content")
    snippet = str(content or "").strip()
    return {
        "title": str(result.get("title") or ""),
        "url": url,
        "score": result.get("score"),
        "snippet": snippet[:_SNIPPET_MAX_CHARS],
    }


async def _search_one(query: str, client: httpx.AsyncClient) -> dict[str, Any]:
    normalized_query = query.strip()
    if not normalized_query:
        return {"query": query, "error": "搜索词不能为空", "results": []}

    try:
        response = await client.post(
            TAVILY_SEARCH_URL,
            headers={
                "Authorization": f"Bearer {require_tool_key('TAVILY_API_KEY')}",
                "Content-Type": "application/json",
            },
            json={
                "query": normalized_query,
                "search_depth": "basic",
                "include_answer": False,
                "include_raw_content": False,
                "max_results": _SEARCH_RESULT_LIMIT,
            },
        )
        response.raise_for_status()
        payload = response.json()
        raw_results = payload.get("results", []) if isinstance(payload, dict) else []
        results = [
            normalized
            for item in raw_results
            if isinstance(item, dict)
            if (normalized := _normalize_result(item)) is not None
        ]
        return {
            "query": normalized_query,
            "results": results,
        }
    except RuntimeError:
        return {
            "query": normalized_query,
            "error": "联网搜索配置不可用",
            "results": [],
        }
    except httpx.TimeoutException, TimeoutError:
        return {
            "query": normalized_query,
            "error": "联网搜索暂时超时",
            "results": [],
        }
    except Exception as exc:
        return {
            "query": normalized_query,
            "error": f"联网搜索暂时失败：{type(exc).__name__}",
            "results": [],
        }


async def _web_search(queries: list[str]) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        return list(
            await asyncio.gather(*(_search_one(query, client) for query in queries))
        )


async def web_search(queries: list[str]) -> list[dict[str, Any]]:
    """搜索最新或需外部核验的公开信息，可用于通用新闻和非旅行主题。

    一次可提交多条互补查询。查询中应带上必要的地点、主题和日期语境；返回结果
    只含标题、URL、相关性和极简摘要，回答时应引用实际使用的来源链接。
    """
    normalized_queries = [query for query in queries if isinstance(query, str)]
    if not normalized_queries:
        return [{"query": "", "error": "至少需要一条搜索词", "results": []}]
    try:
        return await bound_tool_execution(_web_search(normalized_queries))
    except TimeoutError:
        return [
            {"query": query.strip(), "error": "联网搜索暂时超时", "results": []}
            for query in normalized_queries
        ]
