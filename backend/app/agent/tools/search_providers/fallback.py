"""Ordered multi-provider chain with graceful degradation.

Each provider is tried in order; the first non-empty result wins. Exceptions on
an earlier provider fall through to the next one. If every provider fails (or
returns nothing), a single :class:`SearchProviderError` summarizes the whole
chain so the Agent tool can degrade to a text result.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.agent.tools.search_providers.base import (
    SearchDepth,
    SearchProvider,
    SearchProviderError,
    SearchResult,
    SearchTopic,
)


class FallbackSearchProvider:
    name = "fallback"

    def __init__(self, providers: Sequence[SearchProvider]) -> None:
        if not providers:
            raise ValueError("providers must not be empty")
        self._providers = tuple(providers)

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
        failures: list[str] = []
        for provider in self._providers:
            try:
                result = provider.search(
                    query=query,
                    max_results=max_results,
                    topic=topic,
                    search_depth=search_depth,
                    include_domains=include_domains,
                    exclude_domains=exclude_domains,
                )
                if result:
                    return result
            except Exception as exc:
                failures.append(f"{provider.name}={type(exc).__name__}: {exc}")
                continue
            failures.append(f"{provider.name}=no results")

        raise SearchProviderError("所有搜索供应商均失败：" + "; ".join(failures))
