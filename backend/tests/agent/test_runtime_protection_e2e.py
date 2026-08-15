"""Backend Runtime Protection E2E.

Closes R2 by proving the full runtime protection stack through the real
composition root (build_travel_capabilities + build_travel_researcher) with
FakeModel/FunctionModel and FakeTools — no provider is ever called.

Covers the literal acceptance boundaries:

- Main: 9th model request blocked (request_limit=8)
- Main: 7th tool call blocked (tool_calls_limit=6)
- Researcher: 9th model request blocked (request_limit=8)
- Researcher: 19th tool call blocked (tool_calls_limit=18)
- Researcher: second delegation blocked by max_calls=1
- CancelledError is never swallowed
- Timeout ownership hierarchy unchanged
"""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic_ai import Agent, Tool, UsageLimits
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai_harness.subagents import SubAgent, SubAgents

from app.agent.capabilities.travel import (
    RESEARCHER_ON_FAILURE_MESSAGE,
    build_travel_capabilities,
)
from app.agent.executor import AgentExecutionError, AgentExecutionRequest
from app.agent.pydantic_executor import PydanticAIExecutor, _main_usage_limits
from app.agent.tools import _timeout
from app.core.config import settings

_DELEGATE = "delegate_task"
_DELEGATE_NAME = "travel-researcher"


def _delegate_part(tool_call_id: str, task: str) -> ToolCallPart:
    return ToolCallPart(
        tool_name=_DELEGATE,
        args={"agent_name": _DELEGATE_NAME, "task": task},
        tool_call_id=tool_call_id,
    )


def _request() -> AgentExecutionRequest:
    return AgentExecutionRequest(
        request_id=uuid4(),
        conversation_id=uuid4(),
        message="hello",
        history=(),
        deadline_at=datetime.now(UTC) + timedelta(seconds=30),
    )


def _delegate_returns(messages: list[ModelMessage]) -> list[str]:
    return [
        str(part.content)
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart) and part.tool_name == _DELEGATE
    ]


def _researcher_delegation(researcher: Agent[object, str]) -> SubAgents[object]:
    """Build the production delegation shape with the configured role budgets.

    Mirrors ``build_travel_capabilities`` so the boundary tests exercise the
    real per-delegate controls (max_calls / timeout / usage_limits / on_failure).
    """
    return SubAgents[object](
        agents=(
            SubAgent[object](
                researcher,
                max_calls=1,
                timeout_seconds=settings.TRAVEL_RESEARCHER_TIMEOUT_SECONDS,
                usage_limits=UsageLimits(
                    request_limit=settings.TRAVEL_RESEARCHER_MODEL_REQUEST_LIMIT,
                    tool_calls_limit=settings.TRAVEL_RESEARCHER_TOOL_CALL_LIMIT,
                ),
                on_failure=RESEARCHER_ON_FAILURE_MESSAGE,
            ),
        ),
        agent_folders=None,
        forward_usage=True,
        inherit_tools=False,
        contain_errors=False,
        id="travel-research-delegation",
    )


# ---------------------------------------------------------------------------
# Main budgets (8 model requests / 6 tool calls)
# ---------------------------------------------------------------------------


async def test_main_blocks_ninth_model_request(monkeypatch: pytest.MonkeyPatch) -> None:
    # Isolate the request boundary: give the tool budget headroom so the loop is
    # stopped by request_limit alone.
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
    # request_limit=8 allows exactly 8 requests; the 9th is blocked.
    assert model_calls == 8


async def test_main_blocks_seventh_tool_call(monkeypatch: pytest.MonkeyPatch) -> None:
    # Isolate the tool boundary: give the request budget headroom.
    monkeypatch.setattr(settings, "MAIN_MODEL_REQUEST_LIMIT", 20)
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
    # tool_calls_limit=6 allows exactly 6 executions; the 7th is blocked.
    assert tool_calls == 6


def test_main_limits_are_role_specific_and_token_free() -> None:
    limits = _main_usage_limits()

    assert limits.request_limit == settings.MAIN_MODEL_REQUEST_LIMIT == 8
    assert limits.tool_calls_limit == settings.MAIN_TOOL_CALL_LIMIT == 6
    assert limits.total_tokens_limit is None
    assert limits.input_tokens_limit is None
    assert limits.output_tokens_limit is None


# ---------------------------------------------------------------------------
# Researcher budgets (8 model requests / 18 tool calls, soft outcomes)
# ---------------------------------------------------------------------------


async def test_researcher_blocks_ninth_model_request() -> None:
    child_calls = 0

    def child_model(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del messages, info
        nonlocal child_calls
        child_calls += 1
        # One tool call per request keeps tool usage (<=8) below the 18 cap, so
        # the delegation ends on the request boundary: the 9th request is soft-blocked.
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="lookup",
                    args={},
                    tool_call_id=f"child-lookup-{child_calls}",
                )
            ]
        )

    def parent_model(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del info
        if _delegate_returns(messages):
            return ModelResponse(parts=[TextPart("final")])
        return ModelResponse(parts=[_delegate_part("delegate-1", "BRIEF")])

    def lookup() -> str:
        return "research source"

    researcher = Agent(
        FunctionModel(child_model),
        name=_DELEGATE_NAME,
        tools=[Tool[object](lookup, takes_ctx=False)],
    )
    agent = Agent(
        FunctionModel(parent_model),
        capabilities=(_researcher_delegation(researcher),),
    )

    result = await agent.run("plan")

    # 8 requests fit; the 9th request is blocked softly and the delegation
    # returns the on_failure steering instead of raising.
    assert child_calls == 8
    assert result.output == "final"
    assert _delegate_returns(result.all_messages()) == [RESEARCHER_ON_FAILURE_MESSAGE]


async def test_researcher_blocks_nineteenth_tool_call() -> None:
    child_calls = 0
    executed_tools = 0

    def child_model(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del messages, info
        nonlocal child_calls
        child_calls += 1
        # Three tool calls per request: 6 requests x 3 = 18 executions, then the
        # 19th tool call (7th request, within the 8-request budget) is soft-blocked.
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="lookup",
                    args={},
                    tool_call_id=f"child-lookup-{child_calls}-{index}",
                )
                for index in range(3)
            ]
        )

    def parent_model(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del info
        if _delegate_returns(messages):
            return ModelResponse(parts=[TextPart("final")])
        return ModelResponse(parts=[_delegate_part("delegate-1", "BRIEF")])

    def lookup() -> str:
        nonlocal executed_tools
        executed_tools += 1
        return f"research-{executed_tools}"

    researcher = Agent(
        FunctionModel(child_model),
        name=_DELEGATE_NAME,
        tools=[Tool[object](lookup, takes_ctx=False)],
    )
    agent = Agent(
        FunctionModel(parent_model),
        capabilities=(_researcher_delegation(researcher),),
    )

    result = await agent.run("plan")

    # tool_calls_limit=18 allows exactly 18 executions; the 19th is soft-blocked.
    assert executed_tools == 18
    assert result.output == "final"
    assert _delegate_returns(result.all_messages()) == [RESEARCHER_ON_FAILURE_MESSAGE]


def test_researcher_limits_are_role_specific_and_token_free() -> None:
    capabilities = build_travel_capabilities(
        researcher_model=FunctionModel(
            lambda messages, info: ModelResponse(parts=[TextPart("ok")])
        )
    )
    delegation = next(
        capability
        for capability in capabilities
        if isinstance(capability, SubAgents)
    )
    delegate = delegation.agents[0]

    assert delegate.usage_limits is not None
    assert (
        delegate.usage_limits.request_limit
        == settings.TRAVEL_RESEARCHER_MODEL_REQUEST_LIMIT
        == 8
    )
    assert (
        delegate.usage_limits.tool_calls_limit
        == settings.TRAVEL_RESEARCHER_TOOL_CALL_LIMIT
        == 18
    )
    assert delegate.usage_limits.total_tokens_limit is None
    assert delegate.usage_limits.input_tokens_limit is None
    assert delegate.usage_limits.output_tokens_limit is None
    assert delegate.max_calls == 1
    assert delegate.timeout_seconds == settings.TRAVEL_RESEARCHER_TIMEOUT_SECONDS


# ---------------------------------------------------------------------------
# Delegation budget and cancellation semantics
# ---------------------------------------------------------------------------


async def test_researcher_second_delegation_blocked_by_max_calls() -> None:
    child_calls = 0

    def child_model(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del messages, info
        nonlocal child_calls
        child_calls += 1
        return ModelResponse(parts=[TextPart("findings")])

    def parent_model(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del info
        returns = _delegate_returns(messages)
        if len(returns) == 0:
            return ModelResponse(parts=[_delegate_part("delegate-1", "BRIEF")])
        if len(returns) == 1:
            return ModelResponse(parts=[_delegate_part("delegate-2", "BRIEF")])
        return ModelResponse(parts=[TextPart("final")])

    agent = Agent(
        FunctionModel(parent_model),
        capabilities=build_travel_capabilities(
            researcher_model=FunctionModel(child_model),
        ),
    )
    result = await agent.run("plan")

    assert result.output == "final"
    # max_calls=1 runs the child exactly once; the second delegation returns the
    # steering message without touching the child again.
    assert child_calls == 1
    assert _delegate_returns(result.all_messages()) == [
        "findings",
        RESEARCHER_ON_FAILURE_MESSAGE,
    ]


async def test_parent_cancellation_reaches_child_and_is_not_swallowed() -> None:
    child_started = asyncio.Event()
    child_cancelled = asyncio.Event()

    async def slow_child(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del messages, info
        child_started.set()
        try:
            await asyncio.Future[None]()
        except asyncio.CancelledError:
            child_cancelled.set()
            raise
        raise AssertionError("child returned after cancellation")

    def parent_model(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del messages, info
        return ModelResponse(parts=[_delegate_part("delegate-1", "BRIEF")])

    agent = Agent(
        FunctionModel(parent_model),
        capabilities=build_travel_capabilities(
            researcher_model=FunctionModel(slow_child),
        ),
    )
    run = asyncio.create_task(agent.run("go"))
    await asyncio.wait_for(child_started.wait(), timeout=1)
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run
    await asyncio.wait_for(child_cancelled.wait(), timeout=1)


# ---------------------------------------------------------------------------
# Timeout ownership contract
# ---------------------------------------------------------------------------


def test_timeout_ownership_hierarchy_is_stable() -> None:
    assert (
        0
        < _timeout.TOOL_EXECUTION_TIMEOUT_SECONDS
        < settings.LITELLM_CLIENT_TIMEOUT_SECONDS
        < settings.TRAVEL_RESEARCHER_TIMEOUT_SECONDS
        < settings.REQUEST_DEADLINE_SECONDS
    )
    assert _timeout.TOOL_EXECUTION_TIMEOUT_SECONDS == 30
    assert settings.LITELLM_CLIENT_TIMEOUT_SECONDS == 150
    assert settings.TRAVEL_RESEARCHER_TIMEOUT_SECONDS == 240
    assert settings.REQUEST_DEADLINE_SECONDS == 300
