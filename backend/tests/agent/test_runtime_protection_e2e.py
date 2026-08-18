"""Runtime protection contracts for Main + inline Research Agent execution."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic_ai import Agent, Tool
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agent.capabilities.travel import build_travel_capabilities
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


def _tool_returns(messages: list[ModelMessage], name: str) -> list[ToolReturnPart]:
    return [
        part
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart) and part.tool_name == name
    ]


async def test_main_blocks_ninth_model_request(
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
    assert model_calls == 8


async def test_main_blocks_tool_call_beyond_configured_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    assert tool_calls == settings.MAIN_TOOL_CALL_LIMIT == 16


def test_main_limits_are_role_specific_and_token_free() -> None:
    limits = _main_usage_limits()

    assert limits.request_limit == settings.MAIN_MODEL_REQUEST_LIMIT == 8
    assert limits.tool_calls_limit == settings.MAIN_TOOL_CALL_LIMIT == 16
    assert limits.total_tokens_limit is None
    assert limits.input_tokens_limit is None
    assert limits.output_tokens_limit is None


async def test_parent_cancellation_reaches_research_agent() -> None:
    child_started = asyncio.Event()
    child_cancelled = asyncio.Event()

    async def slow_research(
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

    def main_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        if _tool_returns(messages, "research_agent"):
            return ModelResponse(parts=[TextPart("done")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="research_agent",
                    args={
                        "objective": "复杂研究",
                        "verification_items": [
                            {
                                "id": "complex-item",
                                "entity": "复杂主题",
                                "aspect": "核验维度",
                                "question": "该主题需要核验什么？",
                            }
                        ],
                        "constraints": [],
                    },
                    tool_call_id="research-cancel",
                )
            ]
        )

    agent = Agent(
        FunctionModel(main_model),
        capabilities=build_travel_capabilities(
            research_model=FunctionModel(slow_research)
        ),
    )
    run = asyncio.create_task(agent.run("start"))

    await asyncio.wait_for(child_started.wait(), timeout=1)
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run
    await asyncio.wait_for(child_cancelled.wait(), timeout=1)


async def test_parent_cancellation_reaches_parallel_research_agents() -> None:
    started = 0
    cancelled = 0
    all_started = asyncio.Event()
    all_cancelled = asyncio.Event()

    async def slow_research(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del messages, info
        nonlocal started, cancelled
        started += 1
        if started == 2:
            all_started.set()
        try:
            await asyncio.Future[None]()
        except asyncio.CancelledError:
            cancelled += 1
            if cancelled == 2:
                all_cancelled.set()
            raise

    def main_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        if _tool_returns(messages, "research_agent"):
            return ModelResponse(parts=[TextPart("done")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="research_agent",
                    args={
                        "objective": "独立研究主题 A",
                        "verification_items": [
                            {
                                "id": "topic-a-item",
                                "entity": "主题 A",
                                "aspect": "核验维度",
                                "question": "该主题需要核验什么？",
                            }
                        ],
                        "constraints": [],
                    },
                    tool_call_id="research-cancel-a",
                ),
                ToolCallPart(
                    tool_name="research_agent",
                    args={
                        "objective": "独立研究主题 B",
                        "verification_items": [
                            {
                                "id": "topic-b-item",
                                "entity": "主题 B",
                                "aspect": "核验维度",
                                "question": "该主题需要核验什么？",
                            }
                        ],
                        "constraints": [],
                    },
                    tool_call_id="research-cancel-b",
                ),
            ]
        )

    agent = Agent(
        FunctionModel(main_model),
        capabilities=build_travel_capabilities(
            research_model=FunctionModel(slow_research)
        ),
    )
    run = asyncio.create_task(agent.run("start parallel research"))

    await asyncio.wait_for(all_started.wait(), timeout=1)
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run
    await asyncio.wait_for(all_cancelled.wait(), timeout=1)
    assert started == 2
    assert cancelled == 2


def test_timeout_ownership_hierarchy_is_stable_without_child_timer() -> None:
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
