"""Web search backed by the self-hosted SearXNG JSON API."""

from __future__ import annotations

import logging

import httpx

from app.agent.tools._settings import searxng_base_url
from app.core.config import settings

logger = logging.getLogger(__name__)

# #region agent log
import json as _json
import time as _time

_DEBUG_LOG = "/tmp/debug-be622727.log"


def _dbg(hyp: str, loc: str, msg: str, data: dict[str, object]) -> None:
    try:
        with open(_DEBUG_LOG, "a", encoding="utf-8") as _f:
            _f.write(
                _json.dumps(
                    {
                        "sessionId": "be622727-6e96-45b9-8a76-54bc855c563f",
                        "id": f"log_{int(_time.time() * 1000)}_{loc}",
                        "timestamp": int(_time.time() * 1000),
                        "location": f"search.py:{loc}",
                        "message": msg,
                        "data": data,
                        "runId": "pre-fix",
                        "hypothesisId": hyp,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    except Exception:
        pass


# #endregion agent log

_TIMEOUT_SECONDS = 10
_MAX_RESULTS = 5

# Queries with news intent route to the `news` category, which uses dedicated
# news engines (bing news/google news/reuters) instead of the general engines
# that are frequently rate-limited here. Verified at runtime: general category
# returned calendar-spam and gibberish pages for "北京新闻", while news
# category returned real Beijing news items.
_NEWS_INTENT_MARKERS = ("新闻", "news", "资讯", "时事", "最新消息", "热点")

# Whitelist of fields forwarded to the LLM. The raw SearXNG row also carries
# heavy/irrelevant data (base64 thumbnails, parsed_url, raw_data) that would
# waste tokens, so we pick only what the model needs for answering + citing.
_SEARCH_FIELDS = ("title", "url", "content", "publishedDate", "engine", "score")


async def web_search(query: str, max_results: int = 5) -> list[dict[str, object]] | str:
    """Search current web information and return structured JSON rows.

    Each row contains title/url/content (snippet) plus optional
    publishedDate/engine/score. Use this for current/latest facts, official
    rules, prices, opening/booking policies, and news discovery. Important
    dynamic facts should be verified by fetching the key/official URL before
    treating them as authoritative.
    """
    if settings.APP_ENV == "test":
        return [
            {
                "title": "FAKE SEARCH RESULT",
                "url": "https://example.test/search",
                "content": f"Test-only deterministic result for query: {query}",
            }
        ]

    safe_max_results = max(1, min(max_results, _MAX_RESULTS))
    params = {
        "q": query,
        "format": "json",
        "language": "auto",
        "safesearch": 0,
        "pageno": 1,
    }
    if any(marker in query for marker in _NEWS_INTENT_MARKERS):
        params["categories"] = "news"
        params["time_range"] = "month"
    _dbg("H1", "entry", "web_search entry", {"query": query, "max_results": max_results, "params": params})
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.get(f"{searxng_base_url()}/search", params=params)
            response.raise_for_status()
            payload = response.json()
        _dbg(
            "H1",
            "payload",
            "payload received",
            {
                "total": len(payload.get("results") or []),
                "unresponsive": [u[0] for u in payload.get("unresponsive_engines", [])],
                "first5": [
                    {
                        "t": (r.get("title") or "")[:40],
                        "u": (r.get("url") or "")[:50],
                        "pub": r.get("publishedDate"),
                    }
                    for r in (payload.get("results") or [])[:5]
                ],
            },
        )
    except Exception as exc:
        logger.warning("web_search failed: %s", exc)
        return "SEARCH_UNAVAILABLE"

    rows: list[dict[str, object]] = []
    for row in list(payload.get("results") or [])[:safe_max_results]:
        clean = {key: row.get(key) for key in _SEARCH_FIELDS if row.get(key) is not None}
        if not (clean.get("title") or clean.get("url") or clean.get("content")):
            continue
        rows.append(clean)
    _dbg("H2", "rows", "rows returned to LLM", {"count": len(rows), "titles": [r.get("title", "")[:40] for r in rows]})
    return rows if rows else "NO_RESULTS"


def web_search_tool() -> "Tool[object]":
    """Create the SearXNG-backed tool under the project's stable tool name."""
    from pydantic_ai import Tool

    return Tool[object](
        web_search,
        takes_ctx=False,
        name="web_search",
        description=(
            "Search current web information (news, official rules, prices, "
            "opening/booking policies). Returns structured JSON rows with "
            "title, url, content snippet and citation fields."
        ),
        timeout=_TIMEOUT_SECONDS,
    )