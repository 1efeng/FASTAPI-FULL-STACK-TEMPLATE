"""Product usage must aggregate isolated Research Agent usage."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

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


async def test_product_usage_merges_multiple_research_agent_runs() -> None:
    def main_model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        del messages, info
        return ModelResponse(
            parts=[TextPart("main final")],
            usage=RequestUsage(input_tokens=100, output_tokens=20),
            provider_response_id="main-multi",
        )

    main_result = await Agent(FunctionModel(main_model)).run("hello")
    research_a = ModelResponse(
        parts=[TextPart("research A")],
        usage=RequestUsage(input_tokens=30, output_tokens=5),
        provider_response_id="research-a",
    )
    research_b = ModelResponse(
        parts=[TextPart("research B")],
        usage=RequestUsage(input_tokens=40, output_tokens=6),
        provider_response_id="research-b",
    )
    state = ResearchRequestState(
        research_runs=[
            ResearchUsageObservation(
                responses=(research_a,),
                requests=1,
                tool_calls=2,
            ),
            ResearchUsageObservation(
                responses=(research_b,),
                requests=1,
                tool_calls=3,
            ),
        ]
    )

    usage = _to_agent_usage(
        main_result,
        logical_model="travel-agent-llm",
        research_state=state,
    )

    assert usage.model_requests == 3
    assert usage.tool_calls == main_result.usage.tool_calls + 5
    assert usage.input_tokens == 170
    assert usage.output_tokens == 31
    assert usage.total_tokens == 201
    assert {call.provider_response_id for call in usage.model_calls} == {
        "main-multi",
        "research-a",
        "research-b",
    }


async def test_executor_end_to_end_includes_research_agent_usage() -> None:
    research_calls = 0

    def research_model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        del messages
        nonlocal research_calls
        research_calls += 1
        assert info.output_tools
        if research_calls == 1:
            payload: dict[str, Any] = {"actions": []}
            response_id = "research-plan"
        else:
            payload = {
                "topic": "箱根交通",
                "summary": "方案 A 证据更完整",
                "claims": [],
                "sources": [],
                "media": [],
                "unresolved": [],
            }
            response_id = "research-final"
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=info.output_tools[0].name,
                    args=payload,
                    tool_call_id=f"structured-{research_calls}",
                )
            ],
            usage=RequestUsage(input_tokens=40, output_tokens=4),
            provider_response_id=response_id,
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
                        "verification_items": [
                            {
                                "id": "pass-price",
                                "entity": "箱根周游券",
                                "aspect": "当前票价",
                                "question": "当前票价是多少？",
                            },
                            {
                                "id": "pass-scope",
                                "entity": "箱根周游券",
                                "aspect": "覆盖范围",
                                "question": "是否覆盖主要交通？",
                            },
                        ],
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
    assert research_calls == 2
    assert result.usage.model_requests == 4
    assert result.usage.input_tokens == 130
    assert result.usage.output_tokens == 13
    assert result.usage.total_tokens == 143
    assert {call.provider_response_id for call in result.usage.model_calls} == {
        "main-research",
        "main-final",
        "research-plan",
        "research-final",
    }
    assert result.usage.tool_calls >= 1


async def test_role_limits_are_isolated_while_product_usage_aggregates_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bounded child usage is aggregated without consuming Main role-local limits."""

    monkeypatch.setattr(settings, "APP_ENV", "test")
    # Main itself needs exactly two model requests and one research_agent tool.
    # The bounded child adds two model requests plus four Host weather calls; Product
    # usage must exceed both Main-local limits without making Main fail.
    monkeypatch.setattr(settings, "MAIN_MODEL_REQUEST_LIMIT", 2)
    monkeypatch.setattr(settings, "MAIN_TOOL_CALL_LIMIT", 1)

    async def fake_weather(city: str, forecast: bool = False) -> str:
        return f"{city}: sunny (forecast={forecast})"

    monkeypatch.setattr("app.agent.tools.weather._get_weather", fake_weather)
    research_model_calls = 0

    def research_model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        del messages
        nonlocal research_model_calls
        research_model_calls += 1
        assert info.output_tools
        if research_model_calls == 1:
            payload: dict[str, Any] = {
                "actions": [
                    {
                        "tool": "get_weather",
                        "item_ids": ["route-weather"],
                        "city": city,
                        "forecast": False,
                    }
                    for city in ("东京", "横滨", "箱根", "镰仓")
                ]
            }
            response_id = "research-plan"
        else:
            payload = {
                "topic": "bounded research",
                "summary": "天气核验完成",
                "claims": [],
                "sources": [],
                "media": [],
                "unresolved": [],
            }
            response_id = "research-final"
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=info.output_tools[0].name,
                    args=payload,
                    tool_call_id=f"research-structured-{research_model_calls}",
                )
            ],
            usage=RequestUsage(input_tokens=10, output_tokens=1),
            provider_response_id=response_id,
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
                    args={
                        "objective": "核验东京天气",
                        "verification_items": [
                            {
                                "id": "route-weather",
                                "entity": "东京",
                                "aspect": "天气",
                                "question": "指定日期天气是否影响户外计划？",
                            }
                        ],
                        "constraints": [],
                    },
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
    assert research_model_calls == 2
    assert result.usage.model_requests == 4
    assert result.usage.tool_calls >= 5
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
