"""Product usage must aggregate isolated Deep Research Worker usage."""

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
from app.agent.research_runtime import ResearchRequestState, WorkerUsageObservation
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
        message="需要多轴核实",
        history=(),
        deadline_at=datetime.now(UTC) + timedelta(seconds=30),
    )


async def test_product_usage_merges_main_and_isolated_worker_model_calls() -> None:
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
    worker_response = ModelResponse(
        parts=[TextPart("worker finding")],
        usage=RequestUsage(input_tokens=40, output_tokens=10),
        model_name="worker-model",
        provider_response_id="worker-1",
    )
    state = ResearchRequestState(
        worker_runs=[
            WorkerUsageObservation(
                responses=(worker_response,),
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
        "worker-1",
    ]
    assert [call.call_index for call in usage.model_calls] == [0, 1]


async def test_executor_end_to_end_includes_dynamic_workflow_worker_usage() -> None:
    """Main limits remain local, but Product AgentUsage sees Main + Worker calls."""

    worker_calls = 0

    def worker_model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        del messages
        nonlocal worker_calls
        worker_calls += 1
        assert info.output_tools
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=info.output_tools[0].name,
                    args={
                        "topic": "worker usage",
                        "claims": [],
                        "sources": [],
                        "media": [],
                        "unresolved": [],
                    },
                    tool_call_id="worker-final",
                )
            ],
            usage=RequestUsage(input_tokens=40, output_tokens=4),
            provider_response_id="worker-response",
        )

    def main_model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        del info
        if _tool_returns(messages, "run_workflow"):
            return ModelResponse(
                parts=[TextPart("main final")],
                usage=RequestUsage(input_tokens=30, output_tokens=3),
                provider_response_id="main-final",
            )
        if _tool_returns(messages, "load_capability"):
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="run_workflow",
                        args={
                            "code": "await research_worker(task='single worker usage test')"
                        },
                        tool_call_id="workflow-1",
                    )
                ],
                usage=RequestUsage(input_tokens=20, output_tokens=2),
                provider_response_id="main-workflow",
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="load_capability",
                    args={"id": "deep-research"},
                    tool_call_id="load-deep",
                )
            ],
            usage=RequestUsage(input_tokens=10, output_tokens=1),
            provider_response_id="main-load",
        )

    agent = Agent(
        FunctionModel(main_model),
        capabilities=build_travel_capabilities(
            researcher_model=FunctionModel(worker_model)
        ),
    )
    result = await PydanticAIExecutor(
        agent,
        logical_model="travel-agent-llm",
    ).execute(_request())

    assert result.content == "main final"
    assert worker_calls == 1
    assert result.usage.model_requests == 4
    assert result.usage.input_tokens == 100
    assert result.usage.output_tokens == 10
    assert result.usage.total_tokens == 110
    assert {call.provider_response_id for call in result.usage.model_calls} == {
        "main-load",
        "main-workflow",
        "main-final",
        "worker-response",
    }
    # At minimum Main's capability load + run_workflow must be accounted; Worker
    # research tool calls (if any) are added on top by the request-scoped collector.
    assert result.usage.tool_calls >= 2



async def test_role_limits_are_isolated_while_product_usage_aggregates_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """3 Main requests + 7 Worker requests may exceed Main 8/6 *in total*.

    The run must still succeed because role limits are independent, while Product
    AgentUsage must report all ten model requests and all Worker research tools.
    """

    monkeypatch.setattr(settings, "APP_ENV", "test")
    worker_model_calls = 0

    def worker_model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        nonlocal worker_model_calls
        worker_model_calls += 1
        completed_searches = len(_tool_returns(messages, "web_search"))
        if completed_searches < 6:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="web_search",
                        args={"query": f"independent worker query {completed_searches + 1}"},
                        tool_call_id=f"worker-search-{completed_searches + 1}",
                    )
                ],
                usage=RequestUsage(
                    input_tokens=10 + completed_searches,
                    output_tokens=1,
                ),
                provider_response_id=f"worker-{worker_model_calls}",
            )

        assert info.output_tools
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=info.output_tools[0].name,
                    args={
                        "topic": "bounded worker",
                        "claims": [],
                        "sources": [],
                        "media": [],
                        "unresolved": [],
                    },
                    tool_call_id="worker-bounded-final",
                )
            ],
            usage=RequestUsage(input_tokens=16, output_tokens=1),
            provider_response_id="worker-7",
        )

    def main_model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        del info
        if _tool_returns(messages, "run_workflow"):
            return ModelResponse(
                parts=[TextPart("main final after isolated worker")],
                usage=RequestUsage(input_tokens=30, output_tokens=3),
                provider_response_id="main-3",
            )
        if _tool_returns(messages, "load_capability"):
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="run_workflow",
                        args={"code": "await research_worker(task='use seven model requests')"},
                        tool_call_id="workflow-heavy-worker",
                    )
                ],
                usage=RequestUsage(input_tokens=20, output_tokens=2),
                provider_response_id="main-2",
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="load_capability",
                    args={"id": "deep-research"},
                    tool_call_id="load-deep-heavy",
                )
            ],
            usage=RequestUsage(input_tokens=10, output_tokens=1),
            provider_response_id="main-1",
        )

    agent = Agent(
        FunctionModel(main_model),
        capabilities=build_travel_capabilities(
            researcher_model=FunctionModel(worker_model)
        ),
    )
    result = await PydanticAIExecutor(agent).execute(_request())

    assert result.content == "main final after isolated worker"
    assert worker_model_calls == 7
    assert result.usage.model_requests == 10
    # Main uses load_capability + run_workflow (2); Worker executes six web searches.
    assert result.usage.tool_calls >= 8
    # This total deliberately exceeds Main's role-local 8 model / 6 tool caps.
    assert result.usage.model_requests > settings.MAIN_MODEL_REQUEST_LIMIT
    assert result.usage.tool_calls > settings.MAIN_TOOL_CALL_LIMIT

def test_unobserved_worker_request_remains_unattributed_not_zero() -> None:
    class FakeResult:
        def new_messages(self) -> list[ModelResponse]:
            return []

        class Usage:
            requests = 0
            tool_calls = 0

        usage = Usage()

    state = ResearchRequestState(
        worker_runs=[
            WorkerUsageObservation(responses=(), requests=1, tool_calls=0),
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
