"""Free local-development search provider."""

from __future__ import annotations

from ddgs import DDGS
from ddgs.exceptions import DDGSException

from app.agent.tools.search_providers.base import (
    SearchDepth,
    SearchResult,
    SearchTopic,
)

_FALLBACK_BACKENDS = ("auto", "html")


class DuckDuckGoSearchProvider:
    name = "duckduckgo"

    def search(
        self,
        *,
        query: str,
        max_results: int,
        topic: SearchTopic,
        search_depth: SearchDepth,
        include_domains: list[str] | None,
        exclude_domains: list[str] | None,
    ) -> list[SearchResult]:
        del topic, search_depth
        effective_query = query
        if include_domains:
            site_filter = " OR ".join(f"site:{domain}" for domain in include_domains)
            effective_query = f"{query} ({site_filter})"
        if exclude_domains:
            exclude_filter = " AND ".join(f"-site:{domain}" for domain in exclude_domains)
            effective_query = f"{effective_query} ({exclude_filter})"

        client = DDGS(timeout=10)
        results: list[dict[str, object]] = []
        for backend in _FALLBACK_BACKENDS:
            try:
                raw_results = client.text(
                    effective_query,
                    max_results=max_results,
                    backend=backend,
                )
                results = list(raw_results or [])
            except DDGSException:
                continue
            if results:
                break
        if not results:
            return []

        return [
            SearchResult(
                title=str(result.get("title", "")),
                url=str(result.get("href", "")),
                content=str(result.get("body", "")),
            )
            for result in results
        ]
