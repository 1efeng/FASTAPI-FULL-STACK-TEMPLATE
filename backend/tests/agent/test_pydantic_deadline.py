import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from pydantic_ai import Agent, Tool
from pydantic_ai.messages import (
    ModelMessage,
    ModelResponse,
    TextPart,
    ToolCallPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agent.executor import AgentExecutionError, AgentExecutionRequest
from app.agent.pydantic_executor import PydanticAIExecutor
from app.core.config import settings


def _request(*, deadline_at: datetime) -> AgentExecutionRequest:
    return AgentExecutionRequest(
        request_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        message="hello",
        history=(),
        deadline_at=deadline_at,
    )


async def test_expired_deadline_does_not_call_model() -> None:
    called = False

    def model_function(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del messages, info
        nonlocal called
        called = True
        return ModelResponse(parts=[TextPart("too late")])

    executor = PydanticAIExecutor(Agent(FunctionModel(model_function)))

    with pytest.raises(AgentExecutionError) as captured:
        await executor.execute(
            _request(deadline_at=datetime.now(UTC) - timedelta(seconds=1))
        )

    assert captured.value.code == "MODEL_TIMEOUT"
    assert captured.value.retryable is True
    assert called is False


async def test_running_model_is_cancelled_when_deadline_expires() -> None:
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def model_function(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del messages, info
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return ModelResponse(parts=[TextPart("unreachable")])

    executor = PydanticAIExecutor(Agent(FunctionModel(model_function)))

    with pytest.raises(AgentExecutionError) as captured:
        await executor.execute(
            _request(deadline_at=datetime.now(UTC) + timedelta(seconds=0.05))
        )

    assert captured.value.code == "MODEL_TIMEOUT"
    assert entered.is_set()
    assert cancelled.is_set()


async def test_each_model_step_receives_current_remaining_budget() -> None:
    observed_timeouts: list[float] = []
    model_calls = 0

    def deadline_probe() -> str:
        """Return a deterministic tool result."""
        return "tool complete"

    def model_function(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del messages
        nonlocal model_calls
        model_calls += 1
        assert info.model_settings is not None
        timeout = info.model_settings["timeout"]
        assert isinstance(timeout, int | float)
        observed_timeouts.append(float(timeout))
        if model_calls == 1:
            return ModelResponse(
                parts=[ToolCallPart(tool_name="deadline_probe", args={})]
            )
        return ModelResponse(parts=[TextPart("done")])

    agent: Agent[object, str] = Agent(
        FunctionModel(model_function),
        tools=[Tool[object](deadline_probe, takes_ctx=False)],
    )
    executor = PydanticAIExecutor(agent)

    with patch(
        "app.agent.pydantic_executor.remaining_deadline_seconds",
        side_effect=(30.0, 20.0, 10.0),
    ):
        result = await executor.execute(
            _request(deadline_at=datetime.now(UTC) + timedelta(seconds=30))
        )

    assert result.content == "done"
    assert observed_timeouts == [20.0, 10.0]


async def test_deadline_not_enforced_when_execution_timeout_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Debug mode: AGENT_EXECUTION_TIMEOUT_ENABLED=False lets a slow Agent run to
    completion even when `deadline_at` is already in the past, so the SubAgent
    chain can be diagnosed instead of being cut by the Product wall clock."""
    monkeypatch.setattr(settings, "AGENT_EXECUTION_TIMEOUT_ENABLED", False)

    async def slow_model(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del messages, info
        await asyncio.sleep(0.01)
        return ModelResponse(parts=[TextPart("slow but finished")])

    executor = PydanticAIExecutor(Agent(FunctionModel(slow_model)))

    result = await executor.execute(
        _request(deadline_at=datetime.now(UTC) - timedelta(seconds=60))
    )

    assert result.content == "slow but finished"


async def test_deadline_enforced_when_execution_timeout_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The switch must be an explicit opt-out: with the default (enabled) the
    expired deadline still fails fast before any model call."""
    monkeypatch.setattr(settings, "AGENT_EXECUTION_TIMEOUT_ENABLED", True)
    called = False

    def model_function(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del messages, info
        nonlocal called
        called = True
        return ModelResponse(parts=[TextPart("too late")])

    executor = PydanticAIExecutor(Agent(FunctionModel(model_function)))

    with pytest.raises(AgentExecutionError) as captured:
        await executor.execute(
            _request(deadline_at=datetime.now(UTC) - timedelta(seconds=1))
        )

    assert captured.value.code == "MODEL_TIMEOUT"
    assert called is False
