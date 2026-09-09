"""Travel capability composition and Skill-to-Tool dependency validation."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from pathlib import Path

from pydantic_ai.capabilities import AgentCapability, Capability
from pydantic_ai_harness.skills import Skills

from app.agent.capabilities.skill_resources import build_skill_resource_tools
from app.agent.tools.travel_facts import build_travel_fact_tools

SKILL_LIBRARY = Path(__file__).resolve().parents[1] / "skills"

# Skill packages contain declarative instructions and read-only resources. Every
# executable dependency stays explicit and is validated before reaching a model.
SKILL_TOOL_DEPENDENCIES: Mapping[str, frozenset[str]] = {
    "travel-plan-skill": frozenset(
        {
            "search_poi",
            "get_poi_detail",
            "search_nearby",
            "search_maps",
            "query_train_tickets",
            "get_weather",
            "list_skill_resources",
            "read_skill_resource",
        }
    ),
}

_MAIN_TOOLS = build_travel_fact_tools()


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
    enable_planning_core: bool = True,
) -> tuple[AgentCapability[object], ...]:
    """Build Main tools and Skills.

    Domain-neutral Web Search is registered separately at the Main Agent
    composition root, so it is intentionally not a travel Skill dependency here.
    """

    selected_skills = (
        frozenset(SKILL_TOOL_DEPENDENCIES) if enable_planning_core else frozenset()
    )
    resource_tools = build_skill_resource_tools(
        SKILL_LIBRARY,
        selected_skills=selected_skills,
    )
    active_tools = (
        (*_MAIN_TOOLS, *resource_tools) if enable_planning_core else resource_tools
    )
    available_tools = {tool.name for tool in active_tools}
    validate_skill_tool_dependencies(
        selected_skills=selected_skills,
        available_tools=available_tools,
    )

    skill_catalog = Skills[object](SKILL_LIBRARY, include=selected_skills)
    main_tools = Capability[object](id="travel-main-tools", tools=active_tools)
    return (skill_catalog, main_tools)
