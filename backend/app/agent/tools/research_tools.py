"""Shared Tool registration for Main and isolated research workers.

The underlying implementations live in their own modules. This module only creates
fresh PydanticAI Tool objects so multiple agents reuse the same capability contracts
without sharing mutable Tool instances or adding research-specific wrappers.
"""

from __future__ import annotations

from typing import cast

from pydantic_ai import Tool
from pydantic_ai.common_tools.web_fetch import web_fetch_tool

from app.agent.tools.image_search import image_search
from app.agent.tools.route import search_maps
from app.agent.tools.search import web_search
from app.agent.tools.weather import get_weather


def build_research_tools() -> tuple[Tool[object], ...]:
    """Return the shared fact/media research Tool surface."""
    return (
        Tool[object](web_search, takes_ctx=False),
        cast(Tool[object], web_fetch_tool()),
        Tool[object](image_search, takes_ctx=False),
        Tool[object](search_maps, takes_ctx=False),
        Tool[object](get_weather, takes_ctx=False),
    )
