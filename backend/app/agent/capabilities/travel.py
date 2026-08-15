"""Travel capability composition and Skill-to-Tool dependency validation."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from pathlib import Path

from pydantic_ai import Tool
from pydantic_ai.capabilities import AgentCapability, Capability
from pydantic_ai.models import KnownModelName, Model
from pydantic_ai_harness.skills import Skills
from pydantic_ai_harness.subagents import SubAgent, SubAgents

from app.agent.subagents.travel_researcher import build_travel_researcher
from app.agent.tools.budget import calculate_budget
from app.agent.tools.currency import convert_currency
from app.agent.tools.route import search_maps
from app.agent.tools.search import search_web
from app.agent.tools.weather import get_weather
from app.agent.tools.web_fetch import web_fetch
from app.core.config import settings

SKILL_LIBRARY = Path(__file__).resolve().parents[1] / "skills"
_DELEGATION_TOOL_NAME = "delegate_task"
RESEARCHER_ON_FAILURE_MESSAGE = (
    "Travel Researcher 本次调研未在时限内完成（或自身重试耗尽）。"
    "请基于已有可靠信息继续，并明确标注未核实事实。"
)

# Skills contain instructions only. Every executable dependency stays explicit and
# is validated before the capability bundle can reach a model.
SKILL_TOOL_DEPENDENCIES: Mapping[str, frozenset[str]] = {
    "travel-budget": frozenset({"calculate_budget"}),
    "travel-planning": frozenset(
        {
            _DELEGATION_TOOL_NAME,
            "search_web",
            "search_maps",
            "get_weather",
            "calculate_budget",
            "convert_currency",
        }
    ),
}

_BUDGET_TOOL = Tool[object](calculate_budget, takes_ctx=False)
_WEB_FETCH_TOOL = Tool[object](web_fetch, takes_ctx=False)
_MAIN_TOOLS: tuple[Tool[object], ...] = (
    Tool[object](search_web, takes_ctx=False),
    Tool[object](get_weather, takes_ctx=False),
    Tool[object](search_maps, takes_ctx=False),
    _BUDGET_TOOL,
    Tool[object](convert_currency, takes_ctx=False),
    _WEB_FETCH_TOOL,
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
    researcher_model: Model | KnownModelName | str | None = None,
    enable_planning_core: bool = True,
) -> tuple[AgentCapability[object], ...]:
    """Build the migrated core, or the pre-Gate budget-only subset."""
    selected_skills = (
        frozenset(SKILL_TOOL_DEPENDENCIES)
        if enable_planning_core
        else frozenset({"travel-budget"})
    )
    active_tools = _MAIN_TOOLS if enable_planning_core else (_BUDGET_TOOL,)
    available_tools = {tool.name for tool in active_tools}
    if enable_planning_core:
        available_tools.add(_DELEGATION_TOOL_NAME)
    validate_skill_tool_dependencies(
        selected_skills=selected_skills,
        available_tools=available_tools,
    )

    skill_catalog = Skills[object](SKILL_LIBRARY, include=selected_skills)
    main_tools = Capability[object](
        id="travel-main-tools",
        tools=active_tools,
    )
    if not enable_planning_core:
        return (skill_catalog, main_tools)

    researcher = build_travel_researcher(model=researcher_model)
    research_delegation = SubAgents[object](
        agents=(
            SubAgent[object](
                researcher,
                max_calls=1,
                timeout_seconds=settings.TRAVEL_RESEARCHER_TIMEOUT_SECONDS,
                on_failure=RESEARCHER_ON_FAILURE_MESSAGE,
            ),
        ),
        agent_folders=None,
        forward_usage=True,
        inherit_tools=False,
        contain_errors=False,
        id="travel-research-delegation",
    )
    return (skill_catalog, main_tools, research_delegation)
