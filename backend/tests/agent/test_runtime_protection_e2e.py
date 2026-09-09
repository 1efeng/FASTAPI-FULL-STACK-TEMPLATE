"""Runtime protection contracts for Main Agent execution."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic_ai import Agent, Tool
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    ToolCallPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agent.executor import AgentExecutionError, AgentExecutionRequest
from app.agent.pydantic_executor import PydanticAIExecutor, _main_usage_limits
from app.agent.tools import _timeout
from app.core.config import settings


def _request() -> AgentExecutionRequest:
    return AgentExecutionRequest(
        request_id=uuid4(),
        conversation_id=uuid4(),
        message="hello",
        history=(),
        deadline_at=datetime.now(UTC) + timedelta(seconds=30),
    )


async def test_main_blocks_request_beyond_configured_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MAIN_TOOL_CALL_LIMIT", 20)
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
            parts=[
                ToolCallPart(
                    tool_name="lookup",
                    args={},
                    tool_call_id=f"lookup-{model_calls}",
                )
            ]
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
    assert model_calls == 12


async def test_main_blocks_tool_call_beyond_configured_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MAIN_MODEL_REQUEST_LIMIT", 40)
    tool_calls = 0

    def lookup() -> str:
        nonlocal tool_calls
        tool_calls += 1
        return f"tool-{tool_calls}"

    def model_function(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del messages, info
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="lookup",
                    args={},
                    tool_call_id=f"lookup-{tool_calls + 1}",
                )
            ]
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
    assert tool_calls == settings.MAIN_TOOL_CALL_LIMIT == 30


def test_main_limits_are_role_specific_and_token_free() -> None:
    limits = _main_usage_limits()

    assert limits.request_limit == settings.MAIN_MODEL_REQUEST_LIMIT == 12
    assert limits.tool_calls_limit == settings.MAIN_TOOL_CALL_LIMIT == 30
    assert limits.total_tokens_limit is None
    assert limits.input_tokens_limit is None
    assert limits.output_tokens_limit is None


def test_timeout_ownership_hierarchy_is_stable() -> None:
    assert (
        0
        < _timeout.TOOL_EXECUTION_TIMEOUT_SECONDS
        < settings.LITELLM_CLIENT_TIMEOUT_SECONDS
        < settings.REQUEST_DEADLINE_SECONDS
    )
    assert _timeout.TOOL_EXECUTION_TIMEOUT_SECONDS == 30
    assert settings.LITELLM_CLIENT_TIMEOUT_SECONDS == 240
    assert settings.REQUEST_DEADLINE_SECONDS == 900
    assert not hasattr(settings, "TRAVEL_RESEARCHER_TIMEOUT_SECONDS")
