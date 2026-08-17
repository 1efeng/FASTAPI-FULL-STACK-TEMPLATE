"""User-level routing contracts for Candidate Plan First research behavior."""

from __future__ import annotations

from typing import Any

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

from app.agent.capabilities.travel import build_travel_capabilities


def _tool_calls(messages: list[ModelMessage], name: str) -> int:
    return sum(
        1
        for message in messages
        for part in message.parts
        if isinstance(part, ToolCallPart) and part.tool_name == name
    )


def _tool_returns(messages: list[ModelMessage], name: str) -> list[ToolReturnPart]:
    return [
        part
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart) and part.tool_name == name
    ]


def _research_final(info: AgentInfo, payload: dict[str, Any]) -> ModelResponse:
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


def _research_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    del messages
    return _research_final(
        info,
        {
            "topic": "箱根交通比较",
            "summary": "当前证据支持方案 A。",
            "claims": [],
            "sources": [],
            "media": [],
            "unresolved": [],
        },
    )


def _direct_agent(answer: str) -> tuple[Agent[object, str], list[ModelMessage]]:
    seen: list[ModelMessage] = []

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        seen[:] = messages
        return ModelResponse(parts=[TextPart(answer)])

    return (
        Agent(
            FunctionModel(model),
            capabilities=build_travel_capabilities(
                research_model=FunctionModel(_research_model)
            ),
        ),
        seen,
    )


async def test_casual_request_does_not_call_research_agent() -> None:
    agent, seen = _direct_agent("你好！")
    result = await agent.run("你好")
    assert result.output == "你好！"
    assert _tool_calls(seen, "research_agent") == 0


async def test_rough_plan_does_not_call_research_agent() -> None:
    agent, seen = _direct_agent("东京三日游框架")
    result = await agent.run("先给我东京三日游框架，不用查最新")
    assert "东京三日游" in result.output
    assert _tool_calls(seen, "research_agent") == 0


async def test_simple_current_fact_keeps_research_agent_unused() -> None:
    available_tools: set[str] = set()

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages
        available_tools.update(tool.name for tool in info.function_tools)
        return ModelResponse(parts=[TextPart("当前规则应由 Main 直接核验")])

    agent = Agent(
        FunctionModel(model),
        capabilities=build_travel_capabilities(
            research_model=FunctionModel(_research_model)
        ),
    )
    result = await agent.run("核对一个景点当前预约规则")
    assert result.output
    assert "web_fetch" in available_tools
    assert "research_agent" in available_tools


async def test_normal_full_plan_can_finish_without_research_agent() -> None:
    agent, seen = _direct_agent("Candidate Plan → 少量事实核验 → Final Plan")
    result = await agent.run("东京三日游，按正常节奏规划")
    assert "Final Plan" in result.output
    assert _tool_calls(seen, "research_agent") == 0


async def test_beijing_three_day_plan_can_delegate_independent_topics_together() -> None:
    seen: list[ModelMessage] = []

    def research_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompt = str(messages[0])
        topic = "景点预约开放" if "景点" in prompt else "城际与八达岭交通"
        return _research_final(
            info,
            {
                "topic": topic,
                "summary": f"{topic}核验完成",
                "claims": [],
                "sources": [],
                "media": [],
                "unresolved": [],
            },
        )

    def main_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        seen[:] = messages
        returns = _tool_returns(messages, "research_agent")
        if returns:
            assert len(returns) == 2
            return ModelResponse(parts=[TextPart("Main 根据两个 Findings 修订北京三日计划")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="research_agent",
                    args={
                        "objective": "核验北京核心景点预约、开放和参观执行条件",
                        "context": "Candidate Plan: D1 天坛前门；D2 故宫景山",
                        "constraints": ["2026-08-26 至 2026-08-28", "2 人"],
                    },
                    tool_call_id="beijing-attractions",
                ),
                ToolCallPart(
                    tool_name="research_agent",
                    args={
                        "objective": "核验郑州往返北京及八达岭当天交通执行条件",
                        "context": "Candidate Plan: D3 八达岭后返郑州",
                        "constraints": ["总预算 RMB 5000"],
                    },
                    tool_call_id="beijing-transport",
                ),
            ]
        )

    agent = Agent(
        FunctionModel(main_model),
        capabilities=build_travel_capabilities(
            research_model=FunctionModel(research_model)
        ),
    )
    result = await agent.run(
        "2026-08-26 郑州出发，两个人，北京三日经典景点，总预算 RMB 5000"
    )

    assert "修订北京三日计划" in result.output
    assert _tool_calls(seen, "research_agent") == 2
    assert len(_tool_returns(seen, "research_agent")) == 2


async def test_one_coherent_pass_topic_uses_one_research_agent() -> None:
    seen: list[ModelMessage] = []

    def main_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        seen[:] = messages
        returns = _tool_returns(messages, "research_agent")
        if returns:
            return ModelResponse(parts=[TextPart("Main 最终选择方案 A")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="research_agent",
                    args={
                        "objective": "比较东京到箱根多种交通 Pass",
                        "context": "Candidate Plan: Day 2 东京前往箱根",
                        "constraints": [
                            "当前价格",
                            "儿童政策",
                            "覆盖范围",
                            "换乘复杂度",
                        ],
                    },
                    tool_call_id="research-complex",
                )
            ]
        )

    agent = Agent(
        FunctionModel(main_model),
        capabilities=build_travel_capabilities(
            research_model=FunctionModel(_research_model)
        ),
    )
    result = await agent.run("深入比较东京到箱根交通与 Pass")
    assert result.output == "Main 最终选择方案 A"
    assert _tool_calls(seen, "research_agent") == 1
    assert len(_tool_returns(seen, "research_agent")) == 1


async def test_dependent_research_topic_is_delegated_after_first_result() -> None:
    seen: list[ModelMessage] = []

    def main_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        seen[:] = messages
        returns = _tool_returns(messages, "research_agent")
        if not returns:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="research_agent",
                        args={"objective": "核验故宫当日是否可预约"},
                        tool_call_id="dependency-a",
                    )
                ]
            )
        if len(returns) == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="research_agent",
                        args={
                            "objective": "研究故宫不可预约时的同区域替代方案",
                            "context": "第一阶段 Findings 显示故宫不可预约",
                        },
                        tool_call_id="dependency-b",
                    )
                ]
            )
        return ModelResponse(parts=[TextPart("Main 根据两阶段 Findings 完成替代计划")])

    agent = Agent(
        FunctionModel(main_model),
        capabilities=build_travel_capabilities(
            research_model=FunctionModel(_research_model)
        ),
    )
    result = await agent.run("如果故宫订不到就给我同区域替代方案")

    assert "替代计划" in result.output
    assert _tool_calls(seen, "research_agent") == 2
    assert len(_tool_returns(seen, "research_agent")) == 2


async def test_existing_plan_modification_does_not_auto_research() -> None:
    agent, seen = _direct_agent("已把 Day 2 / Day 3 对调并保持其他安排")
    result = await agent.run("把 Day 2 / Day 3 对调")
    assert "对调" in result.output
    assert _tool_calls(seen, "research_agent") == 0
