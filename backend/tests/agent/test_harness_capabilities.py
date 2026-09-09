"""Capability wiring contracts for Skills and Main tools."""

from __future__ import annotations

import pytest
from pydantic_ai import Tool
from pydantic_ai.capabilities import AbstractCapability, Capability
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai_harness.skills import Skills

from app.agent.capabilities.travel import (
    SKILL_LIBRARY,
    build_travel_capabilities,
    validate_skill_tool_dependencies,
)


def _leaf_capabilities(
    capability: AbstractCapability[object],
) -> list[AbstractCapability[object]]:
    leaves: list[AbstractCapability[object]] = []
    capability.apply(leaves.append)
    return leaves


def test_travel_bundle_contains_skills_without_custom_web_tools() -> None:
    capabilities = build_travel_capabilities()

    assert len(capabilities) == 2
    skills = next(item for item in capabilities if isinstance(item, Skills))
    main_tools = next(
        item
        for item in capabilities
        if isinstance(item, Capability) and item.id == "travel-main-tools"
    )
    skill_leaves = _leaf_capabilities(skills)
    assert {leaf.id for leaf in skill_leaves} == {
        "travel-plan-skill",
    }
    assert skills.directories == (SKILL_LIBRARY,)
    assert skills.include == frozenset({"travel-plan-skill"})

    tools_by_name = {
        tool.name: tool for tool in main_tools.tools if isinstance(tool, Tool)
    }
    registered = set(tools_by_name)
    assert registered == {
        "search_poi",
        "get_poi_detail",
        "search_nearby",
        "search_maps",
        "query_train_tickets",
        "get_weather",
        "list_skill_resources",
        "read_skill_resource",
    }
    assert "web_search" not in registered
    assert "web_fetch" not in registered
    assert "tavily_search" not in registered
    assert "tavily_extract" not in registered
    assert "research_agent" not in registered

    toolset = main_tools.get_toolset()
    assert isinstance(toolset, FunctionToolset)
    assert set(toolset.tools) == registered


def test_skill_tool_dependency_validation_fails_closed() -> None:
    with pytest.raises(ValueError, match="travel-plan-skill.*search_poi"):
        validate_skill_tool_dependencies(
            selected_skills={"travel-plan-skill"},
            available_tools=set(),
        )

    with pytest.raises(ValueError, match="travel-plan-skill.*query_train_tickets"):
        validate_skill_tool_dependencies(
            selected_skills={"travel-plan-skill"},
            available_tools={
                "search_poi",
                "get_poi_detail",
                "search_nearby",
                "search_maps",
                "get_weather",
                "list_skill_resources",
                "read_skill_resource",
            },
        )


def test_disabling_planning_core_exposes_no_skills_or_tools() -> None:
    capabilities = build_travel_capabilities(enable_planning_core=False)
    skills = next(item for item in capabilities if isinstance(item, Skills))
    main_tools = next(
        item
        for item in capabilities
        if isinstance(item, Capability) and item.id == "travel-main-tools"
    )

    assert _leaf_capabilities(skills) == []
    assert skills.include == frozenset()
    assert main_tools.tools == ()


def test_every_selected_skill_declares_dependencies() -> None:
    with pytest.raises(ValueError, match="未声明 Tool 依赖"):
        validate_skill_tool_dependencies(
            selected_skills={"unknown-skill"},
            available_tools={"search_poi"},
        )
