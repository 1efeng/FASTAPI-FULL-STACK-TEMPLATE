"""Capability wiring contracts for Skills + Main tools + research_agent."""

from __future__ import annotations

import pytest
from pydantic_ai import Tool
from pydantic_ai.capabilities import AbstractCapability, Capability, WebSearch
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai_harness.dynamic_workflow import DynamicWorkflow
from pydantic_ai_harness.skills import Skills

from app.agent.capabilities.research_agent import (
    RESEARCH_WORKFLOW_CAPABILITY_ID,
)
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


def _noop_model(
    messages: list[ModelMessage], info: AgentInfo
) -> ModelResponse:
    del messages, info
    return ModelResponse(parts=[TextPart("ok")])


def test_travel_bundle_contains_skills_main_tools_and_research_workflow() -> None:
    capabilities = build_travel_capabilities(research_model=FunctionModel(_noop_model))

    skills = next(item for item in capabilities if isinstance(item, Skills))
    main_tools = next(
        item
        for item in capabilities
        if isinstance(item, Capability) and item.id == "travel-main-tools"
    )
    research_workflow = next(
        item
        for item in capabilities
        if isinstance(item, DynamicWorkflow)
    )
    native_web_search = next(item for item in capabilities if isinstance(item, WebSearch))
    assert native_web_search.native is not False

    skill_leaves = _leaf_capabilities(skills)
    assert {leaf.id for leaf in skill_leaves} == {
        "travel-budget",
        "travel-planning",
    }
    assert skills.directories == (SKILL_LIBRARY,)
    assert skills.include == frozenset({"travel-budget", "travel-planning"})

    registered = {tool.name for tool in main_tools.tools if isinstance(tool, Tool)}
    assert registered == {
        "web_fetch",
        "search_maps",
        "get_weather",
        "calculate_budget",
        "convert_currency",
    }

    toolset = main_tools.get_toolset()
    assert isinstance(toolset, FunctionToolset)
    assert set(toolset.tools) == registered

    assert research_workflow.id == RESEARCH_WORKFLOW_CAPABILITY_ID
    assert research_workflow.tool_name == "run_workflow"
    assert [agent.name for agent in research_workflow.agents] == [
        "research_agent"
    ]
    assert "run_workflow" not in registered


def test_skill_tool_dependency_validation_fails_closed() -> None:
    with pytest.raises(ValueError, match="travel-budget.*calculate_budget"):
        validate_skill_tool_dependencies(
            selected_skills={"travel-budget"},
            available_tools=set(),
        )

    with pytest.raises(ValueError, match="travel-planning.*run_workflow"):
        validate_skill_tool_dependencies(
            selected_skills={"travel-planning"},
            available_tools={
                "web_fetch",
                "search_maps",
                "get_weather",
                "calculate_budget",
                "convert_currency",
            },
        )


def test_every_selected_skill_declares_dependencies() -> None:
    with pytest.raises(ValueError, match="未声明 Tool 依赖"):
        validate_skill_tool_dependencies(
            selected_skills={"unknown-skill"},
            available_tools={"calculate_budget"},
        )
