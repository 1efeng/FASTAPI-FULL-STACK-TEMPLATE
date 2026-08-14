"""Environment-aware generic web search facade.

The Agent sees one generic ``search_web`` tool. Provider choice, ordering and
fallback are a runtime strategy owned by this module; the model never selects a
vendor. Domain preference is per-call: when the model needs a specific source
(e.g. travel facts), it passes ``include_domains``; otherwise the search is
unfiltered.

The tool returns a :class:`ToolReturn`: the model reads the numbered result text
in ``return_value``, while the citable ``SourceUrlChunk`` metadata flows to the
UI as ``source-url`` parts (so the frontend can render clickable references).
"""

from __future__ import annotations

from functools import lru_cache
from typing import cast

from pydantic_ai import ToolReturn
from pydantic_ai.ui.vercel_ai.response_types import SourceUrlChunk

from app.agent.tools.search_providers.base import (
    SearchProvider,
    SearchResult,
    format_results,
)
from app.core.config import settings


def _build_provider_chain() -> SearchProvider:
    from app.agent.tools.search_providers.duckduckgo import (
        DuckDuckGoSearchProvider,
    )
    from app.agent.tools.search_providers.fake import FakeSearchProvider

    if settings.APP_ENV == "test":
        return cast(SearchProvider, FakeSearchProvider())

    providers: list[SearchProvider] = []

    if settings.TAVILY_API_KEY:
        from app.agent.tools.search_providers.tavily import TavilySearchProvider

        providers.append(cast(SearchProvider, TavilySearchProvider()))

    providers.append(cast(SearchProvider, DuckDuckGoSearchProvider()))

    if len(providers) == 1:
        return providers[0]

    from app.agent.tools.search_providers.fallback import FallbackSearchProvider

    return cast(SearchProvider, FallbackSearchProvider(providers))


@lru_cache(maxsize=1)
def get_search_provider() -> SearchProvider:
    """Build the provider chain without exposing vendor choice to the Agent."""
    return _build_provider_chain()


def _source_chunks(results: list[SearchResult]) -> list[SourceUrlChunk]:
    return [
        SourceUrlChunk(
            source_id=f"src-{index}",
            url=result.url,
            title=result.title or None,
        )
        for index, result in enumerate(results)
        if result.url
    ]


def search_web(
    query: str,
    max_results: int = 5,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> ToolReturn[str] | str:
    """联网搜索会变化的当前事实，如开放、预约、价格、政策与实时新闻。

    Query 必须描述待核实的问题，不得把未经确认的价格、日期或政策写成事实。
    需要限定来源时通过 include_domains 传入站点域名（例如旅行事实可用
    携程、马蜂窝、穷游等），需要排除低质来源时用 exclude_domains。
    不传时不过滤，返回通用搜索结果。
    """
    try:
        safe_max_results = max(1, min(max_results, 8))
        provider = get_search_provider()
        results = provider.search(
            query=query,
            max_results=safe_max_results,
            topic="general",
            search_depth="advanced",
            include_domains=include_domains,
            exclude_domains=exclude_domains,
        )
        if not results:
            return "未找到相关搜索结果。"
        return ToolReturn[str](
            return_value=format_results(results),
            metadata=_source_chunks(results),
        )
    except Exception as exc:
        return f"联网搜索暂时失败：{type(exc).__name__}"
