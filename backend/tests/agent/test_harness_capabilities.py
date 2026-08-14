import asyncio

import pytest
from pydantic_ai import Agent, Tool
from pydantic_ai.capabilities import AbstractCapability, Capability
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai_harness.skills import Skills
from pydantic_ai_harness.subagents import SubAgent, SubAgents

from app.agent.capabilities.travel import (
    RESEARCHER_ON_FAILURE_MESSAGE,
    SKILL_LIBRARY,
    build_travel_capabilities,
    validate_skill_tool_dependencies,
)
from app.agent.subagents.travel_researcher import build_travel_researcher


def _leaf_capabilities(
    capability: AbstractCapability[object],
) -> list[AbstractCapability[object]]:
    leaves: list[AbstractCapability[object]] = []
    capability.apply(leaves.append)
    return leaves


def _noop_model(
    messages: list[ModelMessage],
    info: AgentInfo,
) -> ModelResponse:
    del messages, info
    return ModelResponse(parts=[TextPart("ok")])


def test_travel_bundle_contains_skills_main_tools_and_research_delegate() -> None:
    capabilities = build_travel_capabilities(researcher_model=FunctionModel(_noop_model))

    skills = next(item for item in capabilities if isinstance(item, Skills))
    main_tools = next(
        item
        for item in capabilities
        if isinstance(item, Capability) and item.id == "travel-main-tools"
    )
    delegation = next(item for item in capabilities if isinstance(item, SubAgents))

    skill_leaves = _leaf_capabilities(skills)
    assert {leaf.id for leaf in skill_leaves} == {
        "travel-budget",
        "travel-planning",
    }
    assert skills.directories == (SKILL_LIBRARY,)
    assert skills.include == frozenset({"travel-budget", "travel-planning"})

    registered = {tool.name for tool in main_tools.tools if isinstance(tool, Tool)}
    assert registered == {
        "search_web",
        "get_weather",
        "search_maps",
        "calculate_budget",
        "convert_currency",
        "web_fetch",
    }

    main_toolset = main_tools.get_toolset()
    assert isinstance(main_toolset, FunctionToolset)
    assert set(main_toolset.tools) == {
        "search_web",
        "get_weather",
        "search_maps",
        "calculate_budget",
        "convert_currency",
        "web_fetch",
    }

    delegate_toolset = delegation.get_toolset()
    assert isinstance(delegate_toolset, FunctionToolset)
    assert set(delegate_toolset.tools) == {"delegate_task"}


def test_agent_request_exposes_skill_catalog_tools_and_delegate() -> None:
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
        capabilities=build_travel_capabilities(researcher_model=FunctionModel(_noop_model)),
    )

    result = agent.run_sync("规划旅行")

    assert result.output == "ok"
    assert {
        "load_capability",
        "delegate_task",
        "search_web",
        "get_weather",
        "search_maps",
        "calculate_budget",
        "convert_currency",
        "web_fetch",
    } <= observed_tool_names
    assert "travel-budget" in observed_instructions
    assert "travel-planning" in observed_instructions
    assert "travel-researcher" in observed_instructions


def test_researcher_has_fresh_history_and_research_only_tools() -> None:
    child_messages: list[ModelMessage] = []
    child_tool_names: set[str] = set()

    def child_model(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        child_messages.extend(messages)
        child_tool_names.update(tool.name for tool in info.function_tools)
        return ModelResponse(parts=[TextPart("Research Findings: isolated")])

    def parent_model(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del info
        if any(
            isinstance(part, ToolReturnPart)
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
        ):
            return ModelResponse(parts=[TextPart("final")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="delegate_task",
                    args={
                        "agent_name": "travel-researcher",
                        "task": "SELF_CONTAINED_RESEARCH_BRIEF",
                    },
                    tool_call_id="delegate-1",
                )
            ]
        )

    agent = Agent(
        FunctionModel(parent_model),
        capabilities=build_travel_capabilities(
            researcher_model=FunctionModel(child_model)
        ),
    )
    result = agent.run_sync(
        "PARENT_CURRENT_SECRET",
        message_history=[ModelRequest(parts=[UserPromptPart("PARENT_HISTORY_SECRET")])],
    )

    assert result.output == "final"
    child_transcript = repr(child_messages)
    assert "SELF_CONTAINED_RESEARCH_BRIEF" in child_transcript
    assert "PARENT_CURRENT_SECRET" not in child_transcript
    assert "PARENT_HISTORY_SECRET" not in child_transcript
    assert child_tool_names == {
        "search_web",
        "get_weather",
        "search_maps",
    }


async def test_researcher_timeout_returns_soft_steering_and_parent_continues() -> None:
    async def slow_child(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del messages, info
        await asyncio.sleep(1)
        return ModelResponse(parts=[TextPart("late")])

    async def parent_model(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del info
        if any(
            isinstance(part, ToolReturnPart)
            for message in messages
            if isinstance(message, ModelRequest)
            for part in message.parts
        ):
            return ModelResponse(parts=[TextPart("final")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="delegate_task",
                    args={"agent_name": "travel-researcher", "task": "BRIEF"},
                    tool_call_id="delegate-1",
                )
            ]
        )

    researcher = build_travel_researcher(model=FunctionModel(slow_child))
    delegation = SubAgents[object](
        agents=(
            SubAgent[object](
                researcher,
                timeout_seconds=0.01,
                on_failure=RESEARCHER_ON_FAILURE_MESSAGE,
            ),
        ),
        agent_folders=None,
    )
    agent = Agent(FunctionModel(parent_model), capabilities=(delegation,))

    result = await agent.run("go")

    assert result.output == "final"
    delegate_returns = [
        part.content
        for message in result.all_messages()
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart) and part.tool_name == "delegate_task"
    ]
    assert delegate_returns == [RESEARCHER_ON_FAILURE_MESSAGE]


def test_skill_tool_dependency_validation_fails_closed() -> None:
    with pytest.raises(ValueError, match="travel-budget.*calculate_budget"):
        validate_skill_tool_dependencies(
            selected_skills={"travel-budget"},
            available_tools=set(),
        )

    with pytest.raises(ValueError, match="travel-planning.*delegate_task"):
        validate_skill_tool_dependencies(
            selected_skills={"travel-planning"},
            available_tools={
                "search_web",
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
