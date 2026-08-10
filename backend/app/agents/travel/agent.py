"""Composition root for the main Travel Agent."""

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from langgraph.graph.state import CompiledStateGraph

from app.agents.travel.middleware import RuntimeClockMiddleware
from app.infra.llm import build_model

_MAIN_PROMPT_PATH = Path(__file__).with_name("prompts") / "main.md"


@lru_cache(maxsize=1)
def _main_system_prompt() -> str:
    return _MAIN_PROMPT_PATH.read_text(encoding="utf-8").strip()


def build_travel_agent(
    *,
    request_id: str,
    trace_id: str | None = None,
    metadata: Mapping[str, str | int | float | bool | None] | None = None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Build a request-scoped Deep Agent backed exclusively by LiteLLM."""
    model = build_model(
        request_id=request_id,
        trace_id=trace_id,
        agent_role="main",
        metadata=metadata,
    )
    return create_deep_agent(
        model=model,
        system_prompt=_main_system_prompt(),
        middleware=[RuntimeClockMiddleware()],
        name="travel-agent",
    )
