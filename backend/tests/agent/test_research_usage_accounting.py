"""Product usage must aggregate isolated Research Agent usage."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from app.agent.capabilities.travel import build_travel_capabilities
from app.agent.executor import AgentExecutionRequest
from app.agent.pydantic_executor import PydanticAIExecutor, _to_agent_usage
from app.agent.research_runtime import ResearchRequestState, ResearchUsageObservation
from app.core.config import settings


def _tool_returns(messages: list[ModelMessage], name: str) -> list[ToolReturnPart]:
    return [
        part
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart) and part.tool_name == name
    ]


def _request() -> AgentExecutionRequest:
    return AgentExecutionRequest(
        request_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        message="需要复杂研究核实",
        history=(),
        deadline_at=datetime.now(UTC) + timedelta(seconds=30),
    )


async def test_product_usage_merges_main_and_research_agent_model_calls() -> None:
    def main_model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        del messages, info
        return ModelResponse(
            parts=[TextPart("main final")],
            usage=RequestUsage(input_tokens=100, output_tokens=20),
            provider_response_id="main-1",
        )

    main_result = await Agent(FunctionModel(main_model)).run("hello")
    research_response = ModelResponse(
        parts=[TextPart("research finding")],
        usage=RequestUsage(input_tokens=40, output_tokens=10),
        model_name="research-model",
        provider_response_id="research-1",
    )
    state = ResearchRequestState(
        research_runs=[
            ResearchUsageObservation(
                responses=(research_response,),
                requests=1,
                tool_calls=3,
            )
        ]
    )

    usage = _to_agent_usage(
        main_result,
        logical_model="travel-agent-llm",
        research_state=state,
    )

    assert usage.model_requests == 2
    assert usage.tool_calls == main_result.usage.tool_calls + 3
    assert usage.input_tokens == 140
    assert usage.output_tokens == 30
    assert usage.total_tokens == 170
    assert [call.provider_response_id for call in usage.model_calls] == [
        "main-1",
        "research-1",
    ]
    assert [call.call_index for call in usage.model_calls] == [0, 1]


async def test_executor_end_to_end_includes_research_agent_usage() -> None:
    research_calls = 0

    def research_model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        del messages
        nonlocal research_calls
        research_calls += 1
        assert info.output_tools
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=info.output_tools[0].name,
                    args={
                        "topic": "箱根交通",
                        "summary": "方案 A 证据更完整",
                        "claims": [],
                        "sources": [],
                        "media": [],
                        "unresolved": [],
                    },
                    tool_call_id="research-final",
                )
            ],
            usage=RequestUsage(input_tokens=40, output_tokens=4),
            provider_response_id="research-response",
        )

    def main_model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        del info
        if _tool_returns(messages, "research_agent"):
            return ModelResponse(
                parts=[TextPart("main final")],
                usage=RequestUsage(input_tokens=30, output_tokens=3),
                provider_response_id="main-final",
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="research_agent",
                    args={
                        "objective": "比较东京到箱根交通 Pass",
                        "context": "Candidate Plan: Day 2 去箱根",
                        "constraints": ["当前价格", "儿童政策"],
                    },
                    tool_call_id="research-1",
                )
            ],
            usage=RequestUsage(input_tokens=20, output_tokens=2),
            provider_response_id="main-research",
        )

    agent = Agent(
        FunctionModel(main_model),
        capabilities=build_travel_capabilities(
            research_model=FunctionModel(research_model)
        ),
    )
    result = await PydanticAIExecutor(
        agent,
        logical_model="travel-agent-llm",
    ).execute(_request())

    assert result.content == "main final"
    assert research_calls == 1
    assert result.usage.model_requests == 3
    assert result.usage.input_tokens == 90
    assert result.usage.output_tokens == 9
    assert result.usage.total_tokens == 99
    assert {call.provider_response_id for call in result.usage.model_calls} == {
        "main-research",
        "main-final",
        "research-response",
    }
    assert result.usage.tool_calls >= 1


async def test_role_limits_are_isolated_while_product_usage_aggregates_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2 Main requests + 7 Research requests may exceed Main limits in total."""

    monkeypatch.setattr(settings, "APP_ENV", "test")

    async def fake_weather(city: str, forecast: bool = False) -> str:
        return f"{city}: sunny (forecast={forecast})"

    monkeypatch.setattr("app.agent.tools.weather._get_weather", fake_weather)
    research_model_calls = 0

    def research_model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        nonlocal research_model_calls
        research_model_calls += 1
        completed_searches = len(_tool_returns(messages, "get_weather"))
        if completed_searches < 6:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="get_weather",
                        args={"city": "东京"},
                        tool_call_id=f"research-weather-{completed_searches + 1}",
                    )
                ],
                usage=RequestUsage(
                    input_tokens=10 + completed_searches,
                    output_tokens=1,
                ),
                provider_response_id=f"research-{research_model_calls}",
            )

        assert info.output_tools
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=info.output_tools[0].name,
                    args={
                        "topic": "bounded research",
                        "summary": "天气核验完成",
                        "claims": [],
                        "sources": [],
                        "media": [],
                        "unresolved": [],
                    },
                    tool_call_id="research-bounded-final",
                )
            ],
            usage=RequestUsage(input_tokens=16, output_tokens=1),
            provider_response_id="research-7",
        )

    def main_model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        del info
        if _tool_returns(messages, "research_agent"):
            return ModelResponse(
                parts=[TextPart("main final after isolated research")],
                usage=RequestUsage(input_tokens=30, output_tokens=3),
                provider_response_id="main-2",
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="research_agent",
                    args={"objective": "核验东京天气", "constraints": []},
                    tool_call_id="research-heavy",
                )
            ],
            usage=RequestUsage(input_tokens=20, output_tokens=2),
            provider_response_id="main-1",
        )

    agent = Agent(
        FunctionModel(main_model),
        capabilities=build_travel_capabilities(
            research_model=FunctionModel(research_model)
        ),
    )
    result = await PydanticAIExecutor(agent).execute(_request())

    assert result.content == "main final after isolated research"
    assert research_model_calls == 7
    assert result.usage.model_requests == 9
    assert result.usage.tool_calls >= 7
    assert result.usage.model_requests > settings.MAIN_MODEL_REQUEST_LIMIT
    assert result.usage.tool_calls > settings.MAIN_TOOL_CALL_LIMIT


def test_unobserved_research_request_remains_unattributed_not_zero() -> None:
    class FakeResult:
        def new_messages(self) -> list[ModelResponse]:
            return []

        class Usage:
            requests = 0
            tool_calls = 0

        usage = Usage()

    state = ResearchRequestState(
        research_runs=[
            ResearchUsageObservation(responses=(), requests=1, tool_calls=0),
        ]
    )
    usage = _to_agent_usage(  # type: ignore[arg-type]
        FakeResult(),
        logical_model="travel-agent-llm",
        research_state=state,
    )

    assert usage.model_requests == 1
    assert usage.unattributed_model_requests == 1
    assert usage.token_usage_available is False
    assert usage.total_tokens is None
