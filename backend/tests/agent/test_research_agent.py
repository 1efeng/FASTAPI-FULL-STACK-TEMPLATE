"""Phase 1 contracts for the search + summarize research_agent."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agent.agents.research_agent import (
    RESEARCH_AGENT_NAME,
    EvidenceSource,
    ResearchFindings,
    ResearchRequest,
    build_research_agent,
)
from app.agent.research_runtime import ResearchRequestState, bind_research_request_state


def _structured_output(info: AgentInfo, payload: dict[str, Any]) -> ModelResponse:
    assert info.output_tools, "ResearchFindings must use structured output"
    return ModelResponse(
        parts=[
            ToolCallPart(
                tool_name=info.output_tools[0].name,
                args=payload,
                tool_call_id="research-agent-final",
            )
        ]
    )


def test_research_request_accepts_minimal_context_contract() -> None:
    # The handoff is a minimal decision-facing contract: objective/title/context/
    # constraints. There is no verification checklist; the child only searches +
    # summarizes context for Main to decide.
    request = ResearchRequest(
        title="箱根交通 Pass 比较",
        objective="比较东京到箱根交通 Pass",
        context="Candidate Plan: Day 2 前往箱根",
        constraints=["2 adults", "1 child"],
    )

    assert request.title == "箱根交通 Pass 比较"
    assert request.objective == "比较东京到箱根交通 Pass"
    assert request.context == "Candidate Plan: Day 2 前往箱根"
    assert request.constraints == ["2 adults", "1 child"]
    # Defaults are fine: an objective-only request is valid.
    assert ResearchRequest(objective="只提供 objective 也可以").title is None


def test_research_findings_returns_compressed_context() -> None:
    url = "https://official.example/pass"
    findings = ResearchFindings(
        topic="交通 Pass",
        summary="当前可选方案已经整理到足够供 Main 比较。",
        sources=[
            EvidenceSource(title="Official Pass", url=url, source_type="official")
        ],
    )

    assert findings.topic == "交通 Pass"
    assert findings.summary is not None
    assert findings.sources[0].url == url
    assert findings.media == []


async def test_build_research_agent_has_host_owned_search_and_no_native_web_search() -> (
    None
):
    observed: dict[str, set[str]] = {}

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages
        observed["function_tools"] = {tool.name for tool in info.function_tools}
        observed["native_tools"] = {
            type(tool).__name__ for tool in info.model_request_parameters.native_tools
        }
        return _structured_output(
            info,
            {
                "topic": "箱根交通",
                "summary": "背景已整理供 Main 决策。",
                "sources": [],
                "media": [],
            },
        )

    agent = build_research_agent(model=FunctionModel(model))
    result = await agent.run("研究东京到箱根交通方案")

    assert agent.name == RESEARCH_AGENT_NAME == "research_agent"
    assert result.output.topic == "箱根交通"
    assert observed["function_tools"] == {
        "search_web",
        "web_fetch",
        "search_poi",
        "get_poi_detail",
        "search_nearby",
        "search_maps",
        "get_weather",
    }
    assert observed["native_tools"] == set()
    assert "calculate_budget" not in observed["function_tools"]
    assert "convert_currency" not in observed["function_tools"]
    assert "research_agent" not in observed["function_tools"]


async def test_research_agent_filters_unobserved_source_urls() -> None:
    invented_url = "https://official.example/invented"

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages
        return _structured_output(
            info,
            {
                "topic": "预约规则",
                "summary": "模型尝试引用未实际搜索到的 URL。",
                "sources": [
                    {
                        "title": "Invented source",
                        "url": invented_url,
                        "source_type": "official",
                    }
                ],
                "media": [],
            },
        )

    agent = build_research_agent(model=FunctionModel(model))
    state = ResearchRequestState()
    with bind_research_request_state(state):
        result = await agent.run("收集当前预约规则背景")

    # Source hygiene: fabricated URLs never survive into the summary's sources.
    assert result.output.sources == []
    assert state.research_requests == result.usage.requests


def test_build_research_agent_requires_explicit_model() -> None:
    with pytest.raises(ValueError, match="research_agent requires an explicit model"):
        build_research_agent()