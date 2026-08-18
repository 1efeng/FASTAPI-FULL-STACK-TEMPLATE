import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic_ai import Agent, Tool
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from app.agent.executor import AgentExecutionError, AgentExecutionRequest, AgentMessage
from app.agent.pydantic_executor import (
    PydanticAIExecutor,
    _main_usage_limits,
    _to_agent_model_call_usage,
)
from app.core.config import settings


def _request(
    *,
    history: tuple[AgentMessage, ...] = (),
) -> AgentExecutionRequest:
    return AgentExecutionRequest(
        request_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        message="hello",
        history=history,
        deadline_at=datetime.now(UTC) + timedelta(seconds=30),
    )


async def test_executor_maps_one_model_response_to_framework_neutral_usage() -> None:
    def model_function(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del messages, info
        return ModelResponse(
            parts=[TextPart("done")],
            usage=RequestUsage(
                input_tokens=120,
                output_tokens=30,
                cache_read_tokens=70,
                details={"private_provider_counter": 999},
            ),
            provider_response_id="gateway-response-1",
        )

    executor = PydanticAIExecutor(
        Agent(FunctionModel(model_function, model_name="reported-model")),
        logical_model="travel-agent-llm",
    )

    result = await executor.execute(_request())

    assert result.usage.model_requests == 1
    call = result.usage.model_calls[0]
    assert call.call_index == 0
    assert call.logical_model == "travel-agent-llm"
    assert call.reported_model == "reported-model"
    assert call.provider_response_id == "gateway-response-1"
    assert call.token_usage is not None
    assert call.token_usage.input_tokens == 120
    assert call.token_usage.output_tokens == 30
    assert call.token_usage.cache_read_tokens == 70
    assert call.token_usage.total_tokens == 150
    assert "private_provider_counter" not in repr(call)


async def test_executor_preserves_per_call_usage_across_tool_loop() -> None:
    model_calls = 0

    def lookup() -> str:
        """Return a deterministic tool result."""
        return "found"

    def model_function(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del messages, info
        nonlocal model_calls
        model_calls += 1
        if model_calls == 1:
            return ModelResponse(
                parts=[ToolCallPart(tool_name="lookup", args={})],
                usage=RequestUsage(input_tokens=10, output_tokens=3),
                provider_response_id="call-1",
            )
        return ModelResponse(
            parts=[TextPart("done")],
            usage=RequestUsage(input_tokens=20, output_tokens=4),
            provider_response_id="call-2",
        )

    agent: Agent[object, str] = Agent(
        FunctionModel(model_function),
        tools=[Tool[object](lookup, takes_ctx=False)],
    )
    result = await PydanticAIExecutor(
        agent,
        logical_model="travel-agent-llm",
    ).execute(_request())

    assert result.usage.model_requests == 2
    assert result.usage.tool_calls == 1
    assert result.usage.input_tokens == 30
    assert result.usage.output_tokens == 7
    assert [call.provider_response_id for call in result.usage.model_calls] == [
        "call-1",
        "call-2",
    ]
    assert [call.call_index for call in result.usage.model_calls] == [0, 1]


async def test_executor_usage_excludes_model_responses_from_durable_history() -> None:
    def model_function(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del messages, info
        return ModelResponse(
            parts=[TextPart("current answer")],
            usage=RequestUsage(input_tokens=8, output_tokens=2),
        )

    result = await PydanticAIExecutor(
        Agent(FunctionModel(model_function)),
        logical_model="travel-agent-llm",
    ).execute(
        _request(
            history=(
                AgentMessage(role="user", content="previous question"),
                AgentMessage(role="assistant", content="previous answer"),
            )
        )
    )

    assert result.usage.model_requests == 1
    assert result.usage.input_tokens == 8
    assert result.usage.output_tokens == 2


def test_mapper_preserves_missing_usage_and_call_id_as_unknown() -> None:
    call = _to_agent_model_call_usage(
        ModelResponse(parts=[TextPart("done")]),
        call_index=0,
        logical_model="travel-agent-llm",
    )

    assert call.provider_response_id is None
    assert call.token_usage is None



def test_main_usage_limits_are_role_specific() -> None:
    limits = _main_usage_limits()

    assert limits.request_limit == settings.MAIN_MODEL_REQUEST_LIMIT == 8
    assert limits.tool_calls_limit == settings.MAIN_TOOL_CALL_LIMIT == 16
    assert limits.total_tokens_limit is None
    assert limits.input_tokens_limit is None
    assert limits.output_tokens_limit is None


async def test_main_request_limit_exhaustion_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MAIN_MODEL_REQUEST_LIMIT", 1)
    model_calls = 0

    def lookup() -> str:
        return "result"

    def model_function(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del messages, info
        nonlocal model_calls
        model_calls += 1
        return ModelResponse(
            parts=[ToolCallPart(tool_name="lookup", args={}, tool_call_id="lookup-1")]
        )

    executor = PydanticAIExecutor(
        Agent(
            FunctionModel(model_function),
            tools=[Tool[object](lookup, takes_ctx=False)],
        )
    )

    with pytest.raises(AgentExecutionError) as raised:
        await executor.execute(_request())

    assert raised.value.code == "MODEL_CALL_LIMIT_REACHED"
    assert model_calls == 1


async def test_main_tool_limit_exhaustion_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MAIN_TOOL_CALL_LIMIT", 0)
    tool_calls = 0

    def lookup() -> str:
        nonlocal tool_calls
        tool_calls += 1
        return "result"

    def model_function(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del messages, info
        return ModelResponse(
            parts=[ToolCallPart(tool_name="lookup", args={}, tool_call_id="lookup-1")]
        )

    executor = PydanticAIExecutor(
        Agent(
            FunctionModel(model_function),
            tools=[Tool[object](lookup, takes_ctx=False)],
        )
    )

    with pytest.raises(AgentExecutionError) as raised:
        await executor.execute(_request())

    assert raised.value.code == "MODEL_CALL_LIMIT_REACHED"
    assert tool_calls == 0
