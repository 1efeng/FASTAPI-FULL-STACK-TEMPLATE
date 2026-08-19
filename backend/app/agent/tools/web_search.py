"""Volcengine 豆包搜索 Global 版 Web Search tool owned by the Agent host.

The provider returns concrete result URLs and per-document snippets, so Research
sources can be checked against the actual tool trajectory instead of trusting
model-authored citations or provider-internal native search state.

This module targets the 豆包搜索 Global 版 contract
(``/search_api/global_search``). Unlike the legacy Custom 版 ``web_search``
endpoint it supports ``MaxSnippetLength`` (per-snippet token cap) and returns
richer per-document metadata (``HostInfo.AuthorityLevel``, ``PublishTime``).
"""

from __future__ import annotations

from typing import Any

import httpx

from app.agent.tools._settings import require_tool_key
from app.agent.tools._timeout import bound_tool_execution

WEB_SEARCH_URL = "https://open.feedcoopapi.com/search_api/global_search"
WEB_SEARCH_TRAFFIC_TAG = "skill_web_search_common"

# 豆包搜索 Global 版：摘要片段长度上限（tokens），默认 500，最大 3000，推荐 1000 以内。
_DEFAULT_SNIPPET_LENGTH = 200
_MIN_SNIPPET_LENGTH = 1
_MAX_SNIPPET_LENGTH = 3000
_MAX_DOC_COUNT = 20

# 解析侧权威过滤：authoritative=True 时仅保留这些 AuthorityLevel。
_AUTHORITATIVE_LEVELS = frozenset({"very_high", "high"})


def _build_request_body(
    *,
    query: str,
    count: int,
    max_snippet_length: int,
) -> dict[str, Any]:
    normalized_query = query.strip()
    if not 1 <= len(normalized_query) <= 100:
        raise ValueError("query 长度必须为 1~100 个字符")
    if not 1 <= count <= _MAX_DOC_COUNT:
        raise ValueError(f"count 必须为 1~{_MAX_DOC_COUNT}")

    snippet_length = max_snippet_length
    if not _MIN_SNIPPET_LENGTH <= snippet_length <= _MAX_SNIPPET_LENGTH:
        raise ValueError(
            f"max_snippet_length 必须为 {_MIN_SNIPPET_LENGTH}~{_MAX_SNIPPET_LENGTH}"
        )

    return {
        "Query": normalized_query,
        "DocCount": count,
        "MaxSnippetLength": snippet_length,
    }


def _document_summary(doc: dict[str, Any]) -> str:
    """Join the text snippets of one Global 版 document into a single summary."""
    snippets = doc.get("Snippet")
    if not isinstance(snippets, list):
        return ""
    text_parts = [
        str(snippet.get("Text") or "")
        for snippet in snippets
        if isinstance(snippet, dict) and snippet.get("Type") == "text"
    ]
    return "\n".join(part for part in text_parts if part)


def _normalize_response(payload: dict[str, Any], *, query: str) -> dict[str, Any]:
    meta = payload.get("ResponseMetadata")
    if isinstance(meta, dict) and isinstance(meta.get("Error"), dict):
        error = meta["Error"]
        message = str(error.get("Message") or "未知错误")
        return {"error": f"联网搜索返回错误：{message}"}

    result = payload.get("Result")
    if not isinstance(result, dict):
        return {"error": "联网搜索返回缺少 Result"}

    rows: list[dict[str, Any]] = []
    for item in result.get("Documents") or []:
        if not isinstance(item, dict):
            continue
        url = item.get("Url")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            continue
        host_info = item.get("HostInfo")
        host_name = str(host_info.get("Hostname")) if isinstance(host_info, dict) else ""
        authority = str(host_info.get("AuthorityLevel")) if isinstance(host_info, dict) else ""
        doc_info = item.get("DocumentInfo")
        published = str(doc_info.get("PublishTime")) if isinstance(doc_info, dict) else ""
        rows.append(
            {
                "title": str(item.get("Title") or ""),
                "url": url,
                "site_name": host_name,
                "authority": authority,
                "summary": _document_summary(item),
                "published": published,
            }
        )

    return {
        "query": query,
        "result_count": int(result.get("TotalDocCount") or len(rows)),
        "time_cost_ms": None,
        "results": rows,
    }


async def _search_web(
    *,
    query: str,
    count: int,
    max_snippet_length: int,
) -> dict[str, Any]:
    body = _build_request_body(
        query=query,
        count=count,
        max_snippet_length=max_snippet_length,
    )
    key = require_tool_key("WEB_SEARCH_API_KEY")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-Traffic-Tag": WEB_SEARCH_TRAFFIC_TAG,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(WEB_SEARCH_URL, headers=headers, json=body)
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        return {"error": "联网搜索返回格式异常"}
    return _normalize_response(payload, query=query.strip())


def _is_authoritative_row(row: dict[str, Any]) -> bool:
    authority = str(row.get("authority") or "")
    return authority in _AUTHORITATIVE_LEVELS


async def search_web(
    query: str,
    count: int = 10,
    time_range: str | None = None,
    authoritative: bool = False,
    query_rewrite: bool = False,
    max_snippet_length: int = _DEFAULT_SNIPPET_LENGTH,
) -> dict[str, Any]:
    """搜索公开 Web 并返回可引用的 URL、标题与摘要（豆包搜索 Global 版）。

    ``authoritative=True`` 仅保留 very_high/high 权威来源。``max_snippet_length``
    控制单个摘要片段的最大 token 数（默认 200，最大 3000）。

    注意：Global 版不支持 ``time_range`` 与 ``query_rewrite`` 请求参数；需要日期
    范围时直接写进 query。这两个参数仅保留以兼容旧调用方，传值会被忽略。
    """
    del time_range, query_rewrite
    try:
        result = await bound_tool_execution(
            _search_web(
                query=query,
                count=count,
                max_snippet_length=max_snippet_length,
            )
        )
    except Exception as exc:
        return {"error": f"联网搜索暂时失败：{type(exc).__name__}"}

    if isinstance(result, dict) and isinstance(result.get("results"), list):
        rows = result["results"]
        if authoritative:
            result["results"] = [row for row in rows if _is_authoritative_row(row)]
    return result