"""Shared Tool registration for Main and isolated research workers.

The underlying implementations live in their own modules. This module only creates
fresh PydanticAI Tool objects so multiple agents reuse the same capability contracts
without sharing mutable Tool instances or adding research-specific wrappers.
"""

from __future__ import annotations

from typing import cast

from pydantic_ai import Tool
from pydantic_ai.common_tools.web_fetch import web_fetch_tool

from app.agent.tools.poi import get_poi_detail, search_nearby, search_poi
from app.agent.tools.route import search_maps
from app.agent.tools.weather import get_weather
from app.agent.tools.web_search import search_web


def build_research_tools(*, include_web_search: bool = False) -> tuple[Tool[object], ...]:
    """Return fact research tools; child research optionally owns Web discovery."""
    tools: list[Tool[object]] = []
    if include_web_search:
        tools.append(Tool[object](search_web, takes_ctx=False))
    tools.extend(
        (
            cast(Tool[object], web_fetch_tool()),
            Tool[object](search_poi, takes_ctx=False),
            Tool[object](get_poi_detail, takes_ctx=False),
            Tool[object](search_nearby, takes_ctx=False),
            Tool[object](search_maps, takes_ctx=False),
            Tool[object](get_weather, takes_ctx=False),
        )
    )
    return tuple(tools)
