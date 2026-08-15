"""Runtime protection contracts for Main + DynamicWorkflow research workers."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic_ai import Agent, RunContext, Tool
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from pydantic_ai_harness.dynamic_workflow import DynamicWorkflow, DynamicWorkflowToolset

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


def _ctx() -> RunContext[object]:
    return RunContext[object](
        deps=None,
        model=TestModel(),
        usage=RunUsage(),
        prompt=None,
        messages=[],
        run_step=1,
    )


async def _run_script(toolset: DynamicWorkflowToolset[object], code: str) -> object:
    ctx = _ctx()
    tools = await toolset.get_tools(ctx)
    tool = tools[toolset.tool_name]
    return await toolset.call_tool(toolset.tool_name, {"code": code}, ctx, tool)


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


async def test_main_blocks_seventh_tool_call(
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
    assert tool_calls == 6


def test_main_limits_are_role_specific_and_token_free() -> None:
    limits = _main_usage_limits()

    assert limits.request_limit == settings.MAIN_MODEL_REQUEST_LIMIT == 8
    assert limits.tool_calls_limit == settings.MAIN_TOOL_CALL_LIMIT == 6
    assert limits.total_tokens_limit is None
    assert limits.input_tokens_limit is None
    assert limits.output_tokens_limit is None


def test_research_worker_limits_and_fanout_ceiling_are_role_specific() -> None:
    def worker_model(
        messages: list[ModelMessage],
        info: AgentInfo,
    ) -> ModelResponse:
        del messages, info
        return ModelResponse(parts=[TextPart("ok")])

    capabilities = build_travel_capabilities(
        researcher_model=FunctionModel(worker_model)
    )
    workflow = next(
        capability
        for capability in capabilities
        if isinstance(capability, DynamicWorkflow)
    )

    assert workflow.max_agent_calls == 3
    assert workflow.forward_usage is False
    assert workflow.resource_limits == {"max_duration_secs": 5}
    assert workflow.sub_agent_usage_limits is not None
    assert workflow.sub_agent_usage_limits.request_limit == 8
    assert workflow.sub_agent_usage_limits.tool_calls_limit == 18
    assert workflow.sub_agent_usage_limits.total_tokens_limit is None
    assert workflow.sub_agent_usage_limits.input_tokens_limit is None
    assert workflow.sub_agent_usage_limits.output_tokens_limit is None


async def test_parent_cancellation_reaches_workflow_worker() -> None:
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

    worker = Agent(FunctionModel(slow_child), name="research_worker")
    workflow = DynamicWorkflow[object](agents=[worker], max_agent_calls=3)
    run = asyncio.create_task(
        _run_script(
            workflow.get_toolset(),
            'await research_worker(task="BRIEF")',
        )
    )

    await asyncio.wait_for(child_started.wait(), timeout=1)
    run.cancel()
    with pytest.raises(asyncio.CancelledError):
        await run
    await asyncio.wait_for(child_cancelled.wait(), timeout=1)


def test_timeout_ownership_hierarchy_is_stable_without_legacy_subagent_timer() -> None:
    assert (
        0
        < _timeout.TOOL_EXECUTION_TIMEOUT_SECONDS
        < settings.LITELLM_CLIENT_TIMEOUT_SECONDS
        < settings.REQUEST_DEADLINE_SECONDS
    )
    assert _timeout.TOOL_EXECUTION_TIMEOUT_SECONDS == 30
    assert settings.LITELLM_CLIENT_TIMEOUT_SECONDS == 150
    assert settings.REQUEST_DEADLINE_SECONDS == 300
    assert not hasattr(settings, "TRAVEL_RESEARCHER_TIMEOUT_SECONDS")
