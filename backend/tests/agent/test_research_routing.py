"""Routing contracts for native web-search capability ownership."""

from __future__ import annotations

from pydantic_ai import Agent
from pydantic_ai.capabilities import Capability
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agent.capabilities.travel import build_travel_capabilities


def _available_tools() -> set[str]:
    capabilities = build_travel_capabilities()
    main = next(
        capability
        for capability in capabilities
        if isinstance(capability, Capability) and capability.id == "travel-main-tools"
    )
    return {tool.name for tool in main.tools}


def test_main_does_not_expose_custom_web_tools_or_legacy_agents() -> None:
    tools = _available_tools()

    assert "web_search" not in tools
    assert "web_fetch" not in tools
    assert "research_agent" not in tools
    assert "search_web" not in tools
    assert "tavily_search" not in tools
    assert "tavily_extract" not in tools
    assert "run_workflow" not in tools


async def test_casual_request_has_no_custom_web_tool_calls() -> None:
    observed: set[str] = set()

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages
        observed.update(tool.name for tool in info.function_tools)
        return ModelResponse(parts=[TextPart("你好！")])

    agent = Agent(FunctionModel(model), capabilities=build_travel_capabilities())
    result = await agent.run("你好")

    assert result.output == "你好！"
    assert "web_search" not in observed
    assert "web_fetch" not in observed
