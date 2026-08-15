"""Keyless web search backed directly by DDGS.

The Agent sees one vendor-neutral ``web_search`` tool. DDGS owns engine selection;
this module only classifies text vs. news intent, normalizes results, bounds wall
clock time, and attaches citable ``SourceUrlChunk`` metadata for the UI.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import urllib.request
from dataclasses import dataclass
from typing import Literal

from ddgs import DDGS
from ddgs.exceptions import DDGSException, TimeoutException
from pydantic_ai import ToolReturn
from pydantic_ai.ui.vercel_ai.response_types import SourceUrlChunk

from app.core.config import settings

logger = logging.getLogger(__name__)

_DEBUG_ENDPOINT = "http://127.0.0.1:7337/ingest/03332aed-f7ea-4d3b-b470-05bcbf73fe91"
_DEBUG_LOG_PATH = r"D:\application\.cursor\debug-03332aed-f7ea-4d3b-b470-05bcbf73fe91.log"
_DEBUG_SESSION_ID = "03332aed-f7ea-4d3b-b470-05bcbf73fe91"


def _debug_log(*, run_id: str, hypothesis_id: str, location: str, message: str, data: dict[str, object]) -> None:
    threading.Thread(
        target=_send_debug_log,
        kwargs={
            "run_id": run_id,
            "hypothesis_id": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
        },
        daemon=True,
    ).start()


def _send_debug_log(*, run_id: str, hypothesis_id: str, location: str, message: str, data: dict[str, object]) -> None:
    payload = {
        "sessionId": _DEBUG_SESSION_ID,
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": round(time.time() * 1000),
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as handle:
            handle.write(body.decode("utf-8") + "\n")
    except Exception:
        pass
    request = urllib.request.Request(
        _DEBUG_ENDPOINT,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Debug-Session-Id": _DEBUG_SESSION_ID,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=1):
            pass
    except Exception:
        pass
_DDGS_TIMEOUT_SECONDS = 8
_SEARCH_WALL_TIMEOUT_SECONDS = 12
_MAX_RESULTS = 8
_NEWS_MARKERS = (
    "新闻",
    "今日要闻",
    "今天要闻",
    "最新消息",
    "新闻报道",
    "媒体报道",
    "报道",
    "breaking",
    "headline",
    "news",
)


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Normalized search result independent of DDGS result shape."""

    title: str
    url: str
    snippet: str
    published_at: str | None = None
    source: str | None = None


def _classify_operation(query: str) -> SearchOperation:
    normalized = query.casefold()
    return "news" if any(marker in normalized for marker in _NEWS_MARKERS) else "text"


def _normalize_results(
    operation: SearchOperation,
    rows: list[dict[str, object]],
) -> list[SearchResult]:
    results: list[SearchResult] = []
    for row in rows:
        if operation == "news":
            url = str(row.get("url") or "").strip()
            published_at = str(row.get("date") or "").strip() or None
            source = str(row.get("source") or "").strip() or None
        else:
            url = str(row.get("href") or "").strip()
            published_at = None
            source = None
        title = str(row.get("title") or "").strip()
        snippet = str(row.get("body") or "").strip()
        if not (title or url or snippet):
            continue
        results.append(
            SearchResult(
                title=title,
                url=url,
                snippet=snippet,
                published_at=published_at,
                source=source,
            )
        )
    return results


def _fake_results(query: str, operation: SearchOperation) -> list[SearchResult]:
    return [
        SearchResult(
            title="[FAKE SEARCH RESULT]",
            url="https://example.test/search",
            snippet=f"Test-only deterministic {operation} result for query: {query}",
            published_at="2026-08-15" if operation == "news" else None,
            source="example.test" if operation == "news" else None,
        )
    ]


async def _search_ddgs(
    *,
    query: str,
    max_results: int,
    operation: SearchOperation,
    run_id: str,
) -> list[SearchResult]:
    """Run one DDGS metasearch call off the event loop."""

    def _run() -> list[SearchResult]:
        # #region agent log
        _debug_log(
            run_id=run_id,
            hypothesis_id="H3",
            location="search.py:_search_ddgs._run:provider-entry",
            message="DDGS worker entered provider call",
            data={"operation": operation, "max_results": max_results},
        )
        # #endregion
        client = DDGS(timeout=_DDGS_TIMEOUT_SECONDS)
        # #region agent log
        _debug_log(
            run_id=run_id,
            hypothesis_id="H3",
            location="search.py:_search_ddgs._run:client-created",
            message="DDGS client constructed",
            data={"operation": operation, "timeout_seconds": _DDGS_TIMEOUT_SECONDS},
        )
        # #endregion
        if operation == "news":
            raw = client.news(
                query,
                max_results=max_results,
                backend="auto",
            )
        else:
            raw = client.text(
                query,
                max_results=max_results,
                backend="auto",
            )
        rows = list(raw or [])
        # #region agent log
        _debug_log(
            run_id=run_id,
            hypothesis_id="H1,H2",
            location="search.py:_search_ddgs._run:provider-return",
            message="DDGS provider returned rows",
            data={"operation": operation, "row_count": len(rows)},
        )
        # #endregion
        return _normalize_results(operation, rows)

    return await asyncio.to_thread(_run)


async def _execute_search(
    *,
    query: str,
    max_results: int,
    operation: SearchOperation,
    run_id: str,
) -> list[SearchResult]:
    """Keep tests offline while production/staging/local use DDGS directly."""
    if settings.APP_ENV == "test":
        return _fake_results(query, operation)
    return await _search_ddgs(
        query=query,
        max_results=max_results,
        operation=operation,
        run_id=run_id,
    )


def _source_chunks(results: list[SearchResult]) -> list[SourceUrlChunk]:
    return [
        SourceUrlChunk(
            source_id=f"src-{index}",
            url=result.url,
            title=result.title or None,
        )
        for index, result in enumerate(results, 1)
        if result.url
    ]


def _format_results(results: list[SearchResult]) -> str:
    lines: list[str] = []
    for index, result in enumerate(results, 1):
        details: list[str] = []
        if result.published_at:
            details.append(f"date={result.published_at}")
        if result.source:
            details.append(f"source={result.source}")
        detail_line = f" [{', '.join(details)}]" if details else ""
        lines.append(
            f"{index}. {result.title}{detail_line}\n"
            f" URL: {result.url}\n"
            f" {result.snippet}"
        )
    return "\n\n".join(lines)


def _is_no_results_error(exc: BaseException) -> bool:
    """Recognize DDGS's explicit empty-result sentinel without leaking its text."""
    return isinstance(exc, DDGSException) and str(exc) == "No results found."


def _failure_status(exc: BaseException) -> str:
    if isinstance(exc, (TimeoutError, TimeoutException)):
        return "SEARCH_TIMEOUT"
    return "SEARCH_UNAVAILABLE"


async def web_search(
    query: str,
    max_results: int = 5,
) -> ToolReturn[str] | str:
    """Search current web information without exposing a search vendor to the Agent.

    Use this for current/latest facts, official rules, prices, opening/booking
    policies, and news discovery. Important dynamic facts should be verified by
    fetching the key/official URL before treating them as authoritative.
    """
    safe_max_results = max(1, min(max_results, _MAX_RESULTS))
    operation = _classify_operation(query)
    run_id = f"web-search-{time.time_ns()}"
    # #region agent log
    _debug_log(
        run_id=run_id,
        hypothesis_id="H1,H4",
        location="search.py:web_search:entry",
        message="web_search entered",
        data={
            "operation": operation,
            "app_env": settings.APP_ENV,
            "requested_max_results": max_results,
            "safe_max_results": safe_max_results,
            "query_length": len(query),
        },
    )
    # #endregion
    started_at = time.monotonic()
    try:
        # #region agent log
        _debug_log(
            run_id=run_id,
            hypothesis_id="H2",
            location="search.py:web_search:before-execute",
            message="web_search starting bounded execution",
            data={
                "operation": operation,
                "ddgs_timeout_seconds": _DDGS_TIMEOUT_SECONDS,
                "wall_timeout_seconds": _SEARCH_WALL_TIMEOUT_SECONDS,
            },
        )
        # #endregion
        async with asyncio.timeout(_SEARCH_WALL_TIMEOUT_SECONDS):
            results = await _execute_search(
                query=query,
                max_results=safe_max_results,
                operation=operation,
                run_id=run_id,
            )
    except Exception as exc:
        elapsed_ms = round((time.monotonic() - started_at) * 1000)
        # #region agent log
        _debug_log(
            run_id=run_id,
            hypothesis_id="H2,H3",
            location="search.py:web_search:exception",
            message="web_search caught provider or bound exception",
            data={
                "operation": operation,
                "error_type": type(exc).__name__,
                "failure_status": _failure_status(exc),
                "elapsed_ms": elapsed_ms,
            },
        )
        # #endregion
        if _is_no_results_error(exc):
            logger.info(
                "web_search completed operation=%s elapsed_ms=%s result_count=0",
                operation,
                elapsed_ms,
            )
            return "NO_RESULTS"
        status = _failure_status(exc)
        logger.warning(
            "web_search failed operation=%s elapsed_ms=%s error_type=%s status=%s",
            operation,
            elapsed_ms,
            type(exc).__name__,
            status,
        )
        return status

    elapsed_ms = round((time.monotonic() - started_at) * 1000)
    # #region agent log
    _debug_log(
        run_id=run_id,
        hypothesis_id="H1,H2",
        location="search.py:web_search:result",
        message="web_search completed provider execution",
        data={"operation": operation, "result_count": len(results), "elapsed_ms": elapsed_ms},
    )
    # #endregion
    if not results:
        logger.info(
            "web_search completed operation=%s elapsed_ms=%s result_count=0",
            operation,
            elapsed_ms,
        )
        return "NO_RESULTS"

    logger.info(
        "web_search completed operation=%s elapsed_ms=%s result_count=%s",
        operation,
        elapsed_ms,
        len(results),
    )
    return ToolReturn[str](
        return_value=_format_results(results),
        metadata=_source_chunks(results),
    )
