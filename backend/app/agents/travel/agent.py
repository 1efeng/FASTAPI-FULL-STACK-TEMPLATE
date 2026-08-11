"""Composition root for the main Travel Agent."""

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from deepagents import create_deep_agent
from langchain.agents.middleware import AgentMiddleware, ModelCallLimitMiddleware
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Checkpointer

from app.agents.travel.middleware import RuntimeClockMiddleware
from app.core.config import settings
from app.infra.checkpoint import get_checkpointer
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
    checkpointer: Checkpointer | None = None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Build a request-scoped Deep Agent backed exclusively by LiteLLM."""
    if checkpointer is None:
        checkpointer = get_checkpointer()
    model = build_model(
        request_id=request_id,
        trace_id=trace_id,
        agent_role="main",
        metadata=metadata,
    )
    return create_deep_agent(
        model=model,
        system_prompt=_main_system_prompt(),
        middleware=[
            cast(
                AgentMiddleware,
                ModelCallLimitMiddleware(
                    run_limit=settings.MODEL_CALL_LIMIT,
                    exit_behavior="error",
                ),
            ),
            RuntimeClockMiddleware(),
        ],
        checkpointer=checkpointer,
        name="travel-agent",
    )
