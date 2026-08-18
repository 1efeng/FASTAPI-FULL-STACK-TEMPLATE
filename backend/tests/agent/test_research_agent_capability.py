"""Main-to-research_agent handoff boundary tests."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic_ai import Agent
from pydantic_ai.exceptions import (
    ModelAPIError,
    UnexpectedModelBehavior,
    UsageLimitExceeded,
)
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.settings import ModelSettings

from app.agent.capabilities.research_agent import (
    RESEARCH_AGENT_CAPABILITY_ID,
    RESEARCH_AGENT_TOOL_NAME,
    RESEARCH_WORKFLOW_CAPABILITY_ID,
    build_research_agent_capability,
    build_research_workflow_capability,
)
from app.agent.research_runtime import (
    ResearchRequestState,
    bind_research_request_state,
)


def _final(info: AgentInfo, payload: dict[str, Any]) -> ModelResponse:
    assert info.output_tools
    return ModelResponse(
        parts=[
            ToolCallPart(
                tool_name=info.output_tools[0].name,
                args=payload,
                tool_call_id="research-final",
            )
        ]
    )


def _tool_returns(messages: list[ModelMessage], name: str) -> list[ToolReturnPart]:
    return [
        part
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart) and part.tool_name == name
    ]


async def test_main_receives_only_compressed_research_findings() -> None:
    child_prompts: list[str] = []

    def child_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        user_text = str(messages[0])
        child_prompts.append(user_text)
        return _final(
            info,
            {
                "topic": "东京到箱根交通比较",
                "summary": "当前证据支持方案 A；儿童政策仍需确认。",
                "claims": [],
                "sources": [],
                "media": [],
                "unresolved": ["儿童政策"],
            },
        )

    parent_seen_returns: list[ToolReturnPart] = []

    def parent_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        returns = _tool_returns(messages, RESEARCH_AGENT_TOOL_NAME)
        if not returns:
            assert any(tool.name == RESEARCH_AGENT_TOOL_NAME for tool in info.function_tools)
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name=RESEARCH_AGENT_TOOL_NAME,
                        args={
                            "title": "箱根交通 Pass 比较",
                            "objective": "比较东京到箱根交通 Pass",
                            "verification_items": [
                                {
                                    "id": "pass-price",
                                    "entity": "箱根周游券",
                                    "aspect": "当前票价",
                                    "question": "当前成人与儿童票价分别是多少？",
                                },
                                {
                                    "id": "pass-scope",
                                    "entity": "箱根周游券",
                                    "aspect": "覆盖范围",
                                    "question": "是否覆盖 Candidate Plan 需要的主要交通？",
                                },
                            ],
                            "context": "Candidate Plan: Day 2 前往箱根",
                            "constraints": ["2 adults", "1 child"],
                        },
                        tool_call_id="delegate-research",
                    )
                ]
            )
        parent_seen_returns.extend(returns)
        return ModelResponse(parts=[TextPart("采用方案 A")])

    capability = build_research_agent_capability(model=FunctionModel(child_model))
    assert capability.id == RESEARCH_AGENT_CAPABILITY_ID

    main = Agent(
        FunctionModel(
            parent_model,
            settings=ModelSettings(parallel_tool_calls=True),
        ),
        model_settings=ModelSettings(parallel_tool_calls=True),
        capabilities=(capability,),
    )
    state = ResearchRequestState()
    with bind_research_request_state(state):
        result = await main.run("做一个候选计划后比较箱根交通")

    assert result.output == "采用方案 A"
    assert len(parent_seen_returns) == 1
    returned = str(parent_seen_returns[0].content)
    assert "东京到箱根交通比较" in returned
    assert "儿童政策" in returned
    assert child_prompts
    prompt = child_prompts[0]
    assert "箱根交通 Pass 比较" in prompt
    assert "比较东京到箱根交通 Pass" in prompt
    assert "pass-price" in prompt
    assert "当前成人与儿童票价分别是多少" in prompt
    assert "Candidate Plan: Day 2 前往箱根" in prompt
    assert "2 adults" in prompt
    assert state.research_requests > 0
    # Separate child usage is collected for Product accounting rather than being
    # folded into Main's own RunUsage counter.
    assert result.usage.requests == 2
    assert state.research_requests == 2


async def test_main_can_delegate_multiple_research_topics_sequentially() -> None:
    child_prompts: list[str] = []

    def child_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompt = "\n".join(
            str(part.content)
            for message in messages
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )
        child_prompts.append(prompt)
        topic = "景点执行条件" if "景点" in prompt else "交通执行条件"
        return _final(
            info,
            {
                "topic": topic,
                "summary": f"{topic}已核验",
                "claims": [],
                "sources": [],
                "media": [],
                "unresolved": [],
            },
        )

    def parent_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        returns = _tool_returns(messages, RESEARCH_AGENT_TOOL_NAME)
        if not returns:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name=RESEARCH_AGENT_TOOL_NAME,
                        args={
                            "objective": "核验景点执行条件",
                            "verification_items": [
                                {
                                    "id": "palace-opening",
                                    "entity": "故宫博物院",
                                    "aspect": "开放与闭馆",
                                    "question": "指定日期是否开放？",
                                }
                            ],
                        },
                        tool_call_id="topic-a",
                    )
                ]
            )
        if len(returns) == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name=RESEARCH_AGENT_TOOL_NAME,
                        args={
                            "objective": "核验交通执行条件",
                            "verification_items": [
                                {
                                    "id": "route-feasibility",
                                    "entity": "北京北站→八达岭",
                                    "aspect": "交通时间",
                                    "question": "公共交通耗时是否可衔接返程？",
                                }
                            ],
                        },
                        tool_call_id="topic-b",
                    )
                ]
            )
        return ModelResponse(parts=[TextPart("两个研究主题都已整合")])

    capability = build_research_agent_capability(model=FunctionModel(child_model))
    main = Agent(
        FunctionModel(
            parent_model,
            settings=ModelSettings(parallel_tool_calls=True),
        ),
        model_settings=ModelSettings(parallel_tool_calls=True),
        capabilities=(capability,),
    )
    state = ResearchRequestState()
    with bind_research_request_state(state):
        result = await main.run("先做 Candidate Plan，再分阶段核验两个主题")

    assert result.output == "两个研究主题都已整合"
    assert len(child_prompts) == 4
    assert len(state.research_runs) == 2
    assert state.research_requests == 4


async def test_recoverable_failure_returns_unresolved_checklist_items() -> None:
    def child_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages, info
        raise ModelAPIError("research-model", "synthetic provider failure")

    captured_returns: list[ToolReturnPart] = []

    def parent_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        returns = _tool_returns(messages, RESEARCH_AGENT_TOOL_NAME)
        if not returns:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name=RESEARCH_AGENT_TOOL_NAME,
                        args={
                            "title": "故宫预约",
                            "objective": "核验故宫预约与放票规则",
                            "verification_items": [
                                {
                                    "id": "palace-reservation",
                                    "entity": "故宫博物院",
                                    "aspect": "预约与放票",
                                    "question": "预约渠道、提前天数与放票时间是什么？",
                                }
                            ],
                        },
                        tool_call_id="failed-checklist-topic",
                    )
                ]
            )
        captured_returns.extend(returns)
        return ModelResponse(parts=[TextPart("继续使用 unresolved 结果")])

    capability = build_research_agent_capability(model=FunctionModel(child_model))
    main = Agent(FunctionModel(parent_model), capabilities=(capability,))
    result = await main.run("核验故宫预约")

    assert result.output == "继续使用 unresolved 结果"
    assert len(captured_returns) == 1
    returned = str(captured_returns[0].content)
    assert "palace-reservation" in returned
    assert "unresolved" in returned


async def test_research_budget_exhaustion_degrades_to_unresolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def budget_exhausted_research(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise UsageLimitExceeded("synthetic research budget exhaustion")

    monkeypatch.setattr(
        "app.agent.capabilities.research_agent.run_bounded_research",
        budget_exhausted_research,
    )

    captured_returns: list[ToolReturnPart] = []

    def parent_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        returns = _tool_returns(messages, RESEARCH_AGENT_TOOL_NAME)
        if not returns:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name=RESEARCH_AGENT_TOOL_NAME,
                        args={
                            "objective": "核验故宫预约规则",
                            "verification_items": [
                                {
                                    "id": "palace-reservation",
                                    "entity": "故宫博物院",
                                    "aspect": "预约与放票",
                                    "question": "预约渠道和放票时间是什么？",
                                }
                            ],
                        },
                        tool_call_id="budget-exhausted-topic",
                    )
                ]
            )
        captured_returns.extend(returns)
        return ModelResponse(parts=[TextPart("保留 unresolved 后继续完成主计划")])

    capability = build_research_agent_capability(
        model=FunctionModel(
            lambda messages, info: ModelResponse(parts=[TextPart("unused")])
        )
    )
    main = Agent(FunctionModel(parent_model), capabilities=(capability,))
    result = await main.run("规划北京行程")

    assert result.output == "保留 unresolved 后继续完成主计划"
    assert len(captured_returns) == 1
    returned = str(captured_returns[0].content)
    assert "palace-reservation" in returned
    assert "unresolved" in returned


async def test_recoverable_parallel_research_failure_does_not_cancel_sibling() -> None:
    failing_started = asyncio.Event()
    healthy_started = asyncio.Event()

    async def child_model(
        messages: list[ModelMessage], info: AgentInfo
    ) -> ModelResponse:
        prompt = "\n".join(
            str(part.content)
            for message in messages
            for part in message.parts
            if isinstance(part, UserPromptPart)
        )
        if "失败主题" in prompt:
            failing_started.set()
            await asyncio.wait_for(healthy_started.wait(), timeout=1)
            raise ModelAPIError("research-model", "synthetic provider failure")

        healthy_started.set()
        await asyncio.wait_for(failing_started.wait(), timeout=1)
        return _final(
            info,
            {
                "topic": "健康主题",
                "summary": "健康主题完成",
                "claims": [],
                "sources": [],
                "media": [],
                "unresolved": [],
            },
        )

    captured_returns: list[ToolReturnPart] = []

    def parent_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        returns = _tool_returns(messages, RESEARCH_AGENT_TOOL_NAME)
        if not returns:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name=RESEARCH_AGENT_TOOL_NAME,
                        args={
                            "objective": "失败主题",
                            "verification_items": [
                                {
                                    "id": "failed-item",
                                    "entity": "失败主题实体",
                                    "aspect": "失败维度",
                                    "question": "该主题需要核验什么？",
                                }
                            ],
                        },
                        tool_call_id="failing-topic",
                    ),
                    ToolCallPart(
                        tool_name=RESEARCH_AGENT_TOOL_NAME,
                        args={
                            "objective": "健康主题",
                            "verification_items": [
                                {
                                    "id": "healthy-item",
                                    "entity": "健康主题实体",
                                    "aspect": "健康维度",
                                    "question": "该主题需要核验什么？",
                                }
                            ],
                        },
                        tool_call_id="healthy-topic",
                    ),
                ]
            )
        captured_returns.extend(returns)
        return ModelResponse(parts=[TextPart("保留成功主题并标记失败主题 unresolved")])

    capability = build_research_agent_capability(model=FunctionModel(child_model))
    main = Agent(
        FunctionModel(parent_model),
        model_settings=ModelSettings(parallel_tool_calls=True),
        capabilities=(capability,),
    )
    state = ResearchRequestState()
    with bind_research_request_state(state):
        result = await main.run("并行研究，其中一个 provider 失败")

    assert result.output == "保留成功主题并标记失败主题 unresolved"
    assert len(captured_returns) == 2
    returned_text = "\n".join(str(item.content) for item in captured_returns)
    assert "当前研究主题暂时无法可靠完成" in returned_text
    assert "健康主题完成" in returned_text
    assert len(state.research_runs) == 2


def test_research_workflow_is_bounded_and_has_one_leaf_agent() -> None:
    capability = build_research_workflow_capability(
        model=FunctionModel(lambda messages, info: ModelResponse(parts=[TextPart("ok")]))
    )

    assert capability.id == RESEARCH_WORKFLOW_CAPABILITY_ID
    assert capability.tool_name == "run_workflow"
    assert capability.max_agent_calls == 2
    assert len(capability.agents) == 1
    assert capability.agents[0].name == "research_agent"


async def test_research_agent_requires_verification_items_tool_call() -> None:
    """A tool call missing verification_items must not enter bounded research.

    ``verification_items`` is a required PydanticAI tool argument. When Main omits
    it, PydanticAI tool argument validation fails and the run aborts with
    ``UnexpectedModelBehavior`` instead of executing the child model, so a bare
    ``objective`` can never start a production Research run.
    """

    child_called = False

    def child_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal child_called
        child_called = True
        del messages
        assert info.output_tools
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=info.output_tools[0].name,
                    args={
                        "topic": "不应进入 child",
                        "summary": "child 不应被调用",
                        "verification_results": [],
                        "claims": [],
                        "sources": [],
                        "media": [],
                        "unresolved": [],
                    },
                    tool_call_id="child-final",
                )
            ]
        )

    def parent_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        if _tool_returns(messages, RESEARCH_AGENT_TOOL_NAME):
            return ModelResponse(parts=[TextPart("不应到达")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=RESEARCH_AGENT_TOOL_NAME,
                    args={"objective": "核验故宫预约规则"},
                    tool_call_id="missing-items",
                )
            ]
        )

    capability = build_research_agent_capability(model=FunctionModel(child_model))
    main = Agent(
        FunctionModel(
            parent_model,
            settings=ModelSettings(parallel_tool_calls=True),
        ),
        model_settings=ModelSettings(parallel_tool_calls=True),
        capabilities=(capability,),
    )

    with pytest.raises(UnexpectedModelBehavior):
        await main.run("核验故宫预约")

    assert child_called is False
