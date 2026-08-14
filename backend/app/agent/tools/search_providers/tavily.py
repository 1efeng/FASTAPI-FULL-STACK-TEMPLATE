"""Tavily production search provider."""

from __future__ import annotations

from typing import Any

from tavily import TavilyClient  # type: ignore[import-untyped]

from app.agent.tools._settings import require_tool_key
from app.agent.tools.search_providers.base import (
    SearchDepth,
    SearchResult,
    SearchTopic,
)


class TavilySearchProvider:
    name = "tavily"

    def __init__(self) -> None:
        self._client: TavilyClient | None = None

    def _get_client(self) -> TavilyClient:
        if self._client is None:
            self._client = TavilyClient(
                api_key=require_tool_key("TAVILY_API_KEY"),
                timeout=10,
            )
        return self._client

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
        client = self._get_client()

        def do_search(
            domains: list[str] | None,
            excluded: list[str] | None,
        ) -> list[dict[str, Any]]:
            response = client.search(
                query=query,
                max_results=max_results,
                topic=topic,
                search_depth=search_depth,
                include_domains=domains,
                exclude_domains=excluded,
            )
            return list(response.get("results") or [])

        results = do_search(include_domains, exclude_domains)
        if not results and include_domains:
            results = do_search(None, exclude_domains)
        if not results:
            return []

        return [
            SearchResult(
                title=str(result.get("title", "")),
                url=str(result.get("url", "")),
                content=str(result.get("content", "")),
            )
            for result in results
        ]
