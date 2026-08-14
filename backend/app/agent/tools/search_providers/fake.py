"""Deterministic offline search provider for unit and trajectory tests."""

from __future__ import annotations

from app.agent.tools.search_providers.base import (
    SearchDepth,
    SearchResult,
    SearchTopic,
)


class FakeSearchProvider:
    name = "fake"

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
        del max_results, topic, search_depth, include_domains, exclude_domains
        return [
            SearchResult(
                title="[FAKE SEARCH RESULT]",
                url="https://example.test/search",
                content=f"Test-only deterministic result for query: {query}",
            )
        ]
