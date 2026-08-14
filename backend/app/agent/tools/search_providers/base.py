"""Provider-neutral search contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

SearchTopic = Literal["general", "news", "finance"]
SearchDepth = Literal["basic", "advanced"]


@dataclass(frozen=True, slots=True)
class SearchResult:
    """One normalized web result: displayable fact rows plus a citable source."""

    title: str
    url: str
    content: str


class SearchProvider(Protocol):
    """Search capability; Agent code never selects a vendor directly."""

    name: str

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
        """Return normalized results (possibly empty); never raise for empty results."""
        ...


class SearchProviderError(RuntimeError):
    """All configured search providers failed."""


def format_results(results: list[SearchResult]) -> str:
    """Render normalized results as numbered rows for the model's context.

    The model reads this text; the citable URL/title metadata flows to the UI
    through the tool's ``ToolReturn`` metadata (see ``search_web``).
    """
    lines: list[str] = []
    for index, result in enumerate(results, 1):
        lines.append(
            f"{index}. {result.title}\n"
            f" URL: {result.url}\n"
            f" {result.content}"
        )
    return "\n\n".join(lines)
