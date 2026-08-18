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


def _structured_output(info: AgentInfo, payload: dict[str, Any]) -> ModelResponse:
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
    """Model both bounded child stages without executing external tools."""
    del messages
    properties = info.output_tools[0].parameters_json_schema.get("properties", {})
    if "actions" in properties:
        return _structured_output(info, {"actions": []})
    return _structured_output(
        info,
        {
            "topic": "JR Pass 方案比较",
            "summary": "本 routing contract 只验证 Planner→Finalizer 编排。",
            "verification_results": [],
            "claims": [],
            "sources": [],
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


def _pass_items() -> list[dict[str, str]]:
    return [
        {
            "id": "jr-pass-price",
            "entity": "全国 JR Pass",
            "aspect": "当前价格",
            "question": "当前成人 7 日券价格是多少？",
        },
        {
            "id": "route-coverage",
            "entity": "当前路线",
            "aspect": "覆盖范围",
            "question": "关键城际段是否由 JR Pass 覆盖？",
        },
        {
            "id": "regional-pass-scope",
            "entity": "已知区域 Pass",
            "aspect": "覆盖范围",
            "question": "区域 Pass 覆盖哪些区段？",
        },
        {
            "id": "key-segment-cost",
            "entity": "关键单买段",
            "aspect": "单买成本",
            "question": "关键区段单买价格是多少？",
        },
    ]


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
    assert "run_workflow" not in available_tools


async def test_normal_full_plan_can_finish_without_research_agent() -> None:
    agent, seen = _direct_agent("Candidate Plan → 少量事实核验 → Final Plan")
    result = await agent.run("东京三日游，按正常节奏规划")
    assert "Final Plan" in result.output
    assert _tool_calls(seen, "research_agent") == 0


async def test_predetermined_parallel_fact_work_does_not_require_research_agent() -> None:
    """Multiple predetermined independent facts stay on Main Direct tools.

    Verifying palace opening / temple ticket / garden reservation is lightweight
    predetermined fact work whose queries can be fixed before execution, so the
    expected architecture routes it to Main parallel tools with zero research_agent
    delegation.
    """

    seen: list[ModelMessage] = []

    def main_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        seen[:] = messages
        return ModelResponse(
            parts=[TextPart("Main 用并行工具核验三个独立事实并完成计划")]
        )

    agent = Agent(
        FunctionModel(main_model),
        capabilities=build_travel_capabilities(
            research_model=FunctionModel(_research_model)
        ),
    )
    result = await agent.run(
        "核验故宫开放、天坛票价、颐和园预约三个独立事实后给我完整计划"
    )

    assert "并行工具核验三个独立事实" in result.output
    assert _tool_calls(seen, "research_agent") == 0


async def test_bounded_evidence_heavy_pass_comparison_uses_research_agent() -> None:
    """A bounded evidence-heavy Pass comparison delegates once to research_agent.

    Main has already defined the Research boundary (atomic verification_items),
    so the child is responsible for one bounded evidence batch plus compression.
    """

    seen: list[ModelMessage] = []

    def main_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        seen[:] = messages
        returns = _tool_returns(messages, "research_agent")
        if returns:
            return ModelResponse(parts=[TextPart("Main 最终选择区域 Pass + 单买组合")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="research_agent",
                    args={
                        "title": "JR Pass 与区域 Pass 比较",
                        "objective": (
                            "结合东京、箱根、京都、大阪、广岛 10 日路线，"
                            "比较全国 JR Pass、区域 Pass 与单买组合，判断哪种更适合。"
                        ),
                        "verification_items": _pass_items(),
                        "context": "10 日路线：东京→箱根→京都→大阪→广岛",
                        "constraints": ["2 名成人"],
                    },
                    tool_call_id="research-pass",
                )
            ]
        )

    agent = Agent(
        FunctionModel(main_model),
        capabilities=build_travel_capabilities(
            research_model=FunctionModel(_research_model)
        ),
    )
    result = await agent.run("比较这条路线下全国 JR Pass 与区域 Pass 哪个更划算")
    assert result.output == "Main 最终选择区域 Pass + 单买组合"
    assert _tool_calls(seen, "research_agent") == 1
    assert len(_tool_returns(seen, "research_agent")) == 1


async def test_path_dependency_research_a_creates_research_b() -> None:
    """Path dependence belongs to Main orchestration, not child Search-again.

    Research A compares JR Pass coverage; Main reads the Findings, discovers a new
    Reality Gap, and only then delegates Research B for the Kansai regional Pass.
    """

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
                        args={
                            "title": "全国 JR Pass 适用性",
                            "objective": "比较全国 JR Pass 与当前已知 Pass 对完整路线的适用性",
                            "verification_items": [
                                {
                                    "id": "price",
                                    "entity": "全国 JR Pass",
                                    "aspect": "价格",
                                    "question": "全国 JR Pass 当前价格是否值得？",
                                },
                                {
                                    "id": "coverage",
                                    "entity": "全国 JR Pass",
                                    "aspect": "路线覆盖",
                                    "question": "是否覆盖整条路线关键段？",
                                },
                            ],
                            "context": "10 日路线：东京→箱根→京都→大阪→广岛",
                            "constraints": [],
                        },
                        tool_call_id="research-a",
                    )
                ]
            )
        if len(returns) == 1:
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="research_agent",
                        args={
                            "title": "关西段区域 Pass",
                            "objective": "研究关西段是否有更合适的区域 Pass",
                            "verification_items": [
                                {
                                    "id": "kansai-pass",
                                    "entity": "关西区域 Pass",
                                    "aspect": "覆盖与价格",
                                    "question": "是否有覆盖关西段且更便宜的区域 Pass？",
                                }
                            ],
                            "context": "Research A Findings 显示关西段覆盖不理想",
                            "constraints": [],
                        },
                        tool_call_id="research-b",
                    )
                ]
            )
        return ModelResponse(parts=[TextPart("Main 根据两阶段 Findings 完成方案")])

    agent = Agent(
        FunctionModel(main_model),
        capabilities=build_travel_capabilities(
            research_model=FunctionModel(_research_model)
        ),
    )
    result = await agent.run("全国 JR Pass 覆盖不理想时，研究关西段替代 Pass")
    assert "两阶段 Findings" in result.output
    assert _tool_calls(seen, "research_agent") == 2
    assert len(_tool_returns(seen, "research_agent")) == 2


async def test_existing_plan_modification_does_not_auto_research() -> None:
    agent, seen = _direct_agent("已把 Day 2 / Day 3 对调并保持其他安排")
    result = await agent.run("把 Day 2 / Day 3 对调")
    assert "对调" in result.output
    assert _tool_calls(seen, "research_agent") == 0
