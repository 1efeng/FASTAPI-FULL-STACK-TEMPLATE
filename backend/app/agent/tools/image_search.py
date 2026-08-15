"""Keyless image discovery backed directly by DDGS images search."""

from __future__ import annotations

import asyncio
import logging
import time

from ddgs import DDGS
from ddgs.exceptions import DDGSException, TimeoutException
from pydantic import BaseModel

from app.core.config import settings

logger = logging.getLogger(__name__)

_DDGS_TIMEOUT_SECONDS = 8
_IMAGE_SEARCH_WALL_TIMEOUT_SECONDS = 12
_MAX_RESULTS = 12


class ImageSearchResult(BaseModel):
    """Normalized display-media candidate returned by ``image_search``."""

    title: str
    image_url: str
    thumbnail_url: str | None = None
    source_page_url: str
    width: int | None = None
    height: int | None = None
    source: str | None = None


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_image_results(
    rows: list[dict[str, object]],
) -> list[ImageSearchResult]:
    results: list[ImageSearchResult] = []
    for row in rows:
        image_url = str(row.get("image") or "").strip()
        source_page_url = str(row.get("url") or "").strip()
        if not image_url or not source_page_url:
            continue
        thumbnail = str(row.get("thumbnail") or "").strip() or None
        source = str(row.get("source") or "").strip() or None
        results.append(
            ImageSearchResult(
                title=str(row.get("title") or "").strip(),
                image_url=image_url,
                thumbnail_url=thumbnail,
                source_page_url=source_page_url,
                width=_optional_int(row.get("width")),
                height=_optional_int(row.get("height")),
                source=source,
            )
        )
    return results


def _fake_results(query: str) -> list[ImageSearchResult]:
    return [
        ImageSearchResult(
            title=f"[FAKE IMAGE] {query}",
            image_url="https://images.example.test/poi.jpg",
            thumbnail_url="https://images.example.test/poi-thumb.jpg",
            source_page_url="https://example.test/poi",
            width=1200,
            height=800,
            source="example.test",
        )
    ]


async def _search_ddgs_images(
    *,
    query: str,
    max_results: int,
) -> list[ImageSearchResult]:
    """Run a single DDGS image metasearch call off the event loop."""

    def _run() -> list[ImageSearchResult]:
        client = DDGS(timeout=_DDGS_TIMEOUT_SECONDS)
        raw = client.images(
            query,
            max_results=max_results,
            backend="auto",
        )
        return _normalize_image_results(list(raw or []))

    return await asyncio.to_thread(_run)


async def _execute_image_search(
    *,
    query: str,
    max_results: int,
) -> list[ImageSearchResult]:
    if settings.APP_ENV == "test":
        return _fake_results(query)
    return await _search_ddgs_images(query=query, max_results=max_results)


def _is_no_results_error(exc: BaseException) -> bool:
    """Recognize DDGS's explicit empty-result sentinel without exposing its text."""
    return isinstance(exc, DDGSException) and str(exc) == "No results found."


def _failure_status(exc: BaseException) -> str:
    if isinstance(exc, (TimeoutError, TimeoutException)):
        return "IMAGE_SEARCH_TIMEOUT"
    return "IMAGE_SEARCH_UNAVAILABLE"


async def image_search(
    query: str,
    max_results: int = 8,
) -> list[ImageSearchResult] | str:
    """Discover image candidates for POIs, attractions, hotels, and landmarks.

    Results are presentation media, not factual evidence. ``image_url`` is the
    actual image while ``source_page_url`` is the page where that image was found.
    """
    safe_max_results = max(1, min(max_results, _MAX_RESULTS))
    started_at = time.monotonic()
    try:
        async with asyncio.timeout(_IMAGE_SEARCH_WALL_TIMEOUT_SECONDS):
            results = await _execute_image_search(
                query=query,
                max_results=safe_max_results,
            )
    except Exception as exc:
        elapsed_ms = round((time.monotonic() - started_at) * 1000)
        if _is_no_results_error(exc):
            logger.info(
                "image_search completed elapsed_ms=%s result_count=0",
                elapsed_ms,
            )
            return "NO_RESULTS"
        status = _failure_status(exc)
        logger.warning(
            "image_search failed elapsed_ms=%s error_type=%s status=%s",
            elapsed_ms,
            type(exc).__name__,
            status,
        )
        return status

    elapsed_ms = round((time.monotonic() - started_at) * 1000)
    if not results:
        logger.info("image_search completed elapsed_ms=%s result_count=0", elapsed_ms)
        return "NO_RESULTS"

    logger.info(
        "image_search completed elapsed_ms=%s result_count=%s",
        elapsed_ms,
        len(results),
    )
    return results
