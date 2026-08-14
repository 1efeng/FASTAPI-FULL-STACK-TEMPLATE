import pytest
from pydantic_ai import Agent, Tool
from pydantic_ai.capabilities import AbstractCapability, Capability
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai_harness.skills import Skills

from app.agent.capabilities.travel import (
    SKILL_LIBRARY,
    build_travel_capabilities,
    validate_skill_tool_dependencies,
)
from app.agent.tools.budget import calculate_budget


def _leaf_capabilities(
    capability: AbstractCapability[object],
) -> list[AbstractCapability[object]]:
    leaves: list[AbstractCapability[object]] = []
    capability.apply(leaves.append)
    return leaves


def test_travel_bundle_contains_deferred_skill_and_required_tool() -> None:
    capabilities = build_travel_capabilities()

    skills = next(item for item in capabilities if isinstance(item, Skills))
    tool_capability = next(
        item
        for item in capabilities
        if isinstance(item, Capability) and item.id == "travel-deterministic-tools"
    )

    skill_leaves = _leaf_capabilities(skills)
    assert [leaf.id for leaf in skill_leaves] == ["travel-budget"]
    assert skills.directories == (SKILL_LIBRARY,)
    assert skills.include == frozenset({"travel-budget"})
    registered_tools = [
        tool for tool in tool_capability.tools if isinstance(tool, Tool)
    ]
    assert any(tool.function is calculate_budget for tool in registered_tools)

    toolset = tool_capability.get_toolset()
    assert isinstance(toolset, FunctionToolset)
    assert "calculate_budget" in toolset.tools


def test_agent_request_exposes_skill_catalog_and_executable_tool() -> None:
    observed_tool_names: set[str] = set()
    observed_instructions = ""

    def model_function(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        nonlocal observed_instructions
        assert messages
        observed_tool_names.update(tool.name for tool in info.function_tools)
        observed_instructions = info.instructions or ""
        return ModelResponse(parts=[TextPart("ok")])

    agent = Agent(
        FunctionModel(model_function),
        capabilities=build_travel_capabilities(),
    )

    result = agent.run_sync("汇总旅行预算")

    assert result.output == "ok"
    assert {"load_capability", "calculate_budget"} <= observed_tool_names
    assert "travel-budget" in observed_instructions


def test_skill_tool_dependency_validation_fails_closed() -> None:
    with pytest.raises(ValueError, match="travel-budget.*calculate_budget"):
        validate_skill_tool_dependencies(
            selected_skills={"travel-budget"},
            available_tools=set(),
        )


def test_every_selected_skill_declares_dependencies() -> None:
    unknown_skill: set[str] = {"unknown-skill"}

    with pytest.raises(ValueError, match="未声明 Tool 依赖"):
        validate_skill_tool_dependencies(
            selected_skills=unknown_skill,
            available_tools={"calculate_budget"},
        )
