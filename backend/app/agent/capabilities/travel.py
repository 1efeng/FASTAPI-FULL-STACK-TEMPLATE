"""Travel capability composition and Skill-to-Tool dependency validation."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from pathlib import Path

from pydantic_ai import Tool, WebSearchTool
from pydantic_ai.capabilities import AgentCapability, Capability, WebSearch
from pydantic_ai.models import KnownModelName, Model
from pydantic_ai_harness.skills import Skills

from app.agent.capabilities.research_agent import (
    RESEARCH_WORKFLOW_CAPABILITY_ID,
    build_research_workflow_capability,
)
from app.agent.tools.budget import calculate_budget
from app.agent.tools.currency import convert_currency
from app.agent.tools.research_tools import build_research_tools

SKILL_LIBRARY = Path(__file__).resolve().parents[1] / "skills"

# Skills contain instructions only. Every executable dependency stays explicit and
# is validated before the capability bundle can reach a model.
SKILL_TOOL_DEPENDENCIES: Mapping[str, frozenset[str]] = {
    "travel-budget": frozenset({"calculate_budget"}),
    "travel-planning": frozenset(
        {
            "web_fetch",
            "search_maps",
            "get_weather",
            "calculate_budget",
            "convert_currency",
            "run_workflow",
        }
    ),
}

_BUDGET_TOOL = Tool[object](calculate_budget, takes_ctx=False)
_CURRENCY_TOOL = Tool[object](convert_currency, takes_ctx=False)
_MAIN_TOOLS: tuple[Tool[object], ...] = (
    *build_research_tools(),
    _BUDGET_TOOL,
    _CURRENCY_TOOL,
)


def validate_skill_tool_dependencies(
    *,
    selected_skills: Collection[str],
    available_tools: Collection[str],
) -> None:
    """Fail closed when a selected Skill references an unavailable Tool."""
    available = frozenset(available_tools)
    for skill_name in selected_skills:
        required = SKILL_TOOL_DEPENDENCIES.get(skill_name)
        if required is None:
            raise ValueError(f"Skill 未声明 Tool 依赖：{skill_name}")
        missing = required - available
        if missing:
            missing_names = ", ".join(sorted(missing))
            raise ValueError(f"Skill {skill_name} 缺少 Tool：{missing_names}")


def build_travel_capabilities(
    *,
    research_model: Model | KnownModelName | str | None = None,
    enable_planning_core: bool = True,
    enable_web_search: bool = True,
) -> tuple[AgentCapability[object], ...]:
    """Build Main tools, Skills, Native Search, and optional research delegation."""

    selected_skills = (
        frozenset(SKILL_TOOL_DEPENDENCIES)
        if enable_planning_core and enable_web_search
        else frozenset({"travel-budget"})
    )
    active_tools = (
        _MAIN_TOOLS if enable_planning_core and enable_web_search else (_BUDGET_TOOL,)
    )
    available_tools = {tool.name for tool in active_tools}
    if enable_planning_core and enable_web_search:
        available_tools.add("run_workflow")
    validate_skill_tool_dependencies(
        selected_skills=selected_skills,
        available_tools=available_tools,
    )

    skill_catalog = Skills[object](SKILL_LIBRARY, include=selected_skills)
    main_tools = Capability[object](id="travel-main-tools", tools=active_tools)
    if not enable_web_search:
        return (skill_catalog, main_tools)

    native_web_search = WebSearch(native=WebSearchTool(optional=True))
    if not enable_planning_core:
        return (skill_catalog, native_web_search, main_tools)

    research_capability = build_research_workflow_capability(model=research_model)
    if research_capability.id != RESEARCH_WORKFLOW_CAPABILITY_ID:
        raise RuntimeError("unexpected research capability id")
    return (
        skill_catalog,
        native_web_search,
        main_tools,
        research_capability,
    )
