"""Travel capability composition and Skill-to-Tool dependency validation."""

from __future__ import annotations

from collections.abc import Collection, Mapping
from pathlib import Path

from pydantic_ai import Tool
from pydantic_ai.capabilities import AgentCapability, Capability
from pydantic_ai_harness.skills import Skills

from app.agent.tools.budget import calculate_budget

SKILL_LIBRARY = Path(__file__).resolve().parents[1] / "skills"

# Harness Skills load instructions only. Keep executable dependencies explicit so
# adding a SKILL.md cannot silently reference a tool absent from the agent runtime.
SKILL_TOOL_DEPENDENCIES: Mapping[str, frozenset[str]] = {
    "travel-budget": frozenset({"calculate_budget"}),
}

_MAIN_TOOLS: tuple[Tool[object], ...] = (
    Tool[object](calculate_budget, takes_ctx=False),
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


def build_travel_capabilities() -> tuple[AgentCapability[object], ...]:
    """Build the first atomic Harness bundle: deferred Skill plus its Tool."""
    selected_skills = frozenset(SKILL_TOOL_DEPENDENCIES)
    available_tools = frozenset(tool.name for tool in _MAIN_TOOLS)
    validate_skill_tool_dependencies(
        selected_skills=selected_skills,
        available_tools=available_tools,
    )

    skill_catalog = Skills[object](SKILL_LIBRARY, include=selected_skills)
    tool_capability = Capability[object](
        id="travel-deterministic-tools",
        tools=_MAIN_TOOLS,
    )
    return (skill_catalog, tool_capability)
