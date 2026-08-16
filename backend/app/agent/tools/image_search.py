"""Image discovery backed by the self-hosted SearXNG images API."""

from __future__ import annotations

import logging

import httpx
from pydantic import BaseModel

from app.agent.tools._settings import searxng_base_url
from app.core.config import settings

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 10
_MAX_RESULTS = 12


class ImageSearchResult(BaseModel):
    """Display-media candidate returned by ``image_search``."""

    title: str
    image_url: str
    thumbnail_url: str | None = None
    source_page_url: str
    width: int | None = None
    height: int | None = None
    source: str | None = None


def _to_int(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def _parse_resolution(resolution: object) -> tuple[int | None, int | None]:
    if not isinstance(resolution, str) or "×" not in resolution:
        return None, None
    width, _, height = resolution.partition("×")
    return _to_int(width), _to_int(height)


async def image_search(
    query: str,
    max_results: int = 8,
) -> list[ImageSearchResult] | str:
    """Discover image candidates for POIs, attractions, hotels, and landmarks."""
    if settings.APP_ENV == "test":
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

    safe_max_results = max(1, min(max_results, _MAX_RESULTS))
    params = {
        "q": query,
        "format": "json",
        "categories": "images",
        "language": "auto",
        "safesearch": 0,
        "pageno": 1,
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.get(f"{searxng_base_url()}/search", params=params)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        logger.warning("image_search failed: %s", exc)
        return "IMAGE_SEARCH_UNAVAILABLE"

    results: list[ImageSearchResult] = []
    for row in list(payload.get("results") or [])[:safe_max_results]:
        image_url = str(row.get("img_src") or "").strip()
        source_page_url = str(row.get("url") or "").strip()
        if not image_url or not source_page_url:
            continue
        width, height = _parse_resolution(row.get("resolution"))
        results.append(
            ImageSearchResult(
                title=str(row.get("title") or "").strip(),
                image_url=image_url,
                thumbnail_url=str(row.get("thumbnail_src") or "").strip() or None,
                source_page_url=source_page_url,
                width=width,
                height=height,
                source=str(row.get("engine") or "").strip() or None,
            )
        )
    return results if results else "NO_RESULTS"