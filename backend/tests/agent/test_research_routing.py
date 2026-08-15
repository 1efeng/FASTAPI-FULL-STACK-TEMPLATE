"""H1 trajectory regression suite for Main-as-Leader research routing.

This migrates the old Optional Researcher behavior coverage onto the v8
DynamicWorkflow architecture. Tests are deterministic and provider-free.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

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
from pydantic_ai.models.test import TestModel

from app.agent.capabilities.travel import build_travel_capabilities
from app.core.config import settings


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


def _load(skill_id: str, call_id: str) -> ToolCallPart:
    return ToolCallPart(
        tool_name="load_capability",
        args={"id": skill_id},
        tool_call_id=call_id,
    )


def _workflow(code: str, call_id: str) -> ToolCallPart:
    return ToolCallPart(
        tool_name="run_workflow",
        args={"code": code},
        tool_call_id=call_id,
    )


def _agent(
    parent_model: Callable[[list[ModelMessage], AgentInfo], ModelResponse],
    *,
    worker_model: Any | None = None,
) -> Agent[object, str]:
    worker_model = worker_model or TestModel(
        custom_output_args={
            "topic": "unused",
            "claims": [],
            "sources": [],
            "media": [],
            "unresolved": [],
        }
    )
    return Agent(
        FunctionModel(parent_model),
        capabilities=build_travel_capabilities(researcher_model=worker_model),
    )


async def test_casual_chat_does_not_load_skill_or_deep_research() -> None:
    def parent(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages, info
        return ModelResponse(parts=[TextPart("你好！")])

    result = await _agent(parent).run("你好")
    messages = result.all_messages()

    assert result.output == "你好！"
    assert _tool_calls(messages, "load_capability") == 0
    assert _tool_calls(messages, "run_workflow") == 0
    assert _tool_calls(messages, "web_search") == 0


async def test_inspiration_can_use_planning_skill_without_workflow() -> None:
    def parent(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        if _tool_returns(messages, "load_capability"):
            return ModelResponse(parts=[TextPart("北京灵感：故宫、胡同、长城三个方向。")])
        return ModelResponse(parts=[_load("travel-planning", "load-plan")])

    result = await _agent(parent).run("给我一些北京旅行灵感，不用查最新")
    messages = result.all_messages()

    assert "北京灵感" in result.output
    assert _tool_calls(messages, "load_capability") == 1
    assert _tool_calls(messages, "run_workflow") == 0
    assert _tool_calls(messages, "web_search") == 0


async def test_complete_plan_without_fresh_fact_dependency_uses_zero_workflow() -> None:
    def parent(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        if _tool_returns(messages, "load_capability"):
            return ModelResponse(parts=[TextPart("# 京都三日慢旅行\n\n按用户给定景点重新排序。")])
        return ModelResponse(parts=[_load("travel-planning", "load-plan")])

    result = await _agent(parent).run(
        "用我给你的清水寺、岚山、伏见稻荷排三天；开放时间我自己确认"
    )
    messages = result.all_messages()

    assert result.output.startswith("# 京都三日慢旅行")
    assert _tool_calls(messages, "run_workflow") == 0
    assert _tool_calls(messages, "web_search") == 0


async def test_single_current_fact_uses_main_web_search_without_workflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "test")

    def parent(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        if _tool_returns(messages, "web_search"):
            return ModelResponse(parts=[TextPart("已根据当前搜索结果回答。")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="web_search",
                    args={"query": "故宫 当前 预约 官方"},
                    tool_call_id="search-1",
                )
            ]
        )

    result = await _agent(parent).run("故宫现在怎么预约？")
    messages = result.all_messages()

    assert result.output == "已根据当前搜索结果回答。"
    assert _tool_calls(messages, "web_search") == 1
    assert _tool_calls(messages, "run_workflow") == 0


async def test_explicit_verification_of_one_fact_stays_quick_research(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "test")

    def parent(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        if _tool_returns(messages, "web_search"):
            return ModelResponse(parts=[TextPart("已核实单一预约事实。")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="web_search",
                    args={"query": "浅草寺 当前 预约 官方"},
                    tool_call_id="quick-verify",
                )
            ]
        )

    result = await _agent(parent).run("帮我查官方确认一下浅草寺现在是否需要预约")
    messages = result.all_messages()

    assert result.output == "已核实单一预约事实。"
    assert _tool_calls(messages, "web_search") == 1
    assert _tool_calls(messages, "run_workflow") == 0


async def test_one_successful_web_search_is_enough_no_near_duplicate_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "test")

    def parent(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        returns = _tool_returns(messages, "web_search")
        if returns:
            assert "https://example.test/search" in str(returns[0].content)
            return ModelResponse(parts=[TextPart("一个有效搜索已经足够。")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="web_search",
                    args={"query": "东京站 行李寄存 当前 官方"},
                    tool_call_id="search-once",
                )
            ]
        )

    result = await _agent(parent).run("核实东京站现在有没有行李寄存")
    messages = result.all_messages()

    assert result.output == "一个有效搜索已经足够。"
    assert _tool_calls(messages, "web_search") == 1
    assert _tool_calls(messages, "run_workflow") == 0


async def test_rough_plan_can_load_travel_skill_without_deep_research() -> None:
    def parent(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        if _tool_returns(messages, "load_capability"):
            return ModelResponse(parts=[TextPart("# 北京三日游草案")])
        return ModelResponse(parts=[_load("travel-planning", "load-plan")])

    result = await _agent(parent).run("先给我一个北京三日游大概框架，不用查最新")
    messages = result.all_messages()

    assert result.output == "# 北京三日游草案"
    assert _tool_calls(messages, "load_capability") == 1
    assert _tool_calls(messages, "run_workflow") == 0


async def test_multi_axis_executable_plan_runs_one_parallel_workflow() -> None:
    worker_model = TestModel(
        custom_output_args={
            "topic": "verified topic",
            "claims": [],
            "sources": [],
            "media": [],
            "unresolved": [],
        }
    )

    def parent(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        if _tool_returns(messages, "run_workflow"):
            return ModelResponse(parts=[TextPart("# 北京三日可执行方案")])
        if _tool_returns(messages, "load_capability"):
            return ModelResponse(
                parts=[
                    _workflow(
                        "import asyncio\n"
                        "results = await asyncio.gather(\n"
                        "    research_worker(task='核实景区开放预约并准备POI图片'),\n"
                        "    research_worker(task='核实城际与关键市内交通'),\n"
                        ")\n"
                        "results",
                        "workflow-1",
                    )
                ]
            )
        return ModelResponse(parts=[_load("deep-research", "load-deep")])

    result = await _agent(parent, worker_model=worker_model).run(
        "按实际情况做北京三日可执行方案，需要核实景区和交通"
    )
    messages = result.all_messages()

    assert result.output == "# 北京三日可执行方案"
    assert _tool_calls(messages, "run_workflow") == 1
    returns = _tool_returns(messages, "run_workflow")
    assert len(returns) == 1
    assert "verified topic" in str(returns[0].content)


async def test_multiple_explicit_verification_axes_use_one_workflow() -> None:
    worker_model = TestModel(
        custom_output_args={
            "topic": "axis",
            "claims": [],
            "sources": [],
            "media": [],
            "unresolved": [],
        }
    )

    def parent(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        if _tool_returns(messages, "run_workflow"):
            return ModelResponse(parts=[TextPart("多轴核实完成。")])
        if _tool_returns(messages, "load_capability"):
            return ModelResponse(
                parts=[
                    _workflow(
                        "import asyncio\n"
                        "results = await asyncio.gather(\n"
                        " research_worker(task='核实门票预约开放'),\n"
                        " research_worker(task='核实交通Pass与运营'),\n"
                        " research_worker(task='核实酒店区域现实通勤'),\n"
                        ")\nresults",
                        "multi-axis",
                    )
                ]
            )
        return ModelResponse(parts=[_load("deep-research", "load-deep")])

    result = await _agent(parent, worker_model=worker_model).run(
        "请把门票预约、交通Pass和住宿通勤都按最新情况核实后再规划"
    )
    messages = result.all_messages()

    assert result.output == "多轴核实完成。"
    assert _tool_calls(messages, "run_workflow") == 1


async def test_worker_failure_degrades_to_unresolved_without_second_workflow() -> None:
    worker_calls = 0

    def broken_worker(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages, info
        nonlocal worker_calls
        worker_calls += 1
        raise RuntimeError("synthetic research failure")

    def parent(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        workflow_returns = _tool_returns(messages, "run_workflow")
        if workflow_returns:
            assert "unresolved" in str(workflow_returns[-1].content)
            return ModelResponse(parts=[TextPart("最终计划：该事实 unresolved，执行前再确认。")])
        if _tool_returns(messages, "load_capability"):
            return ModelResponse(
                parts=[
                    _workflow(
                        "async def safe(task):\n"
                        "    try:\n"
                        "        return await research_worker(task=task)\n"
                        "    except RuntimeError:\n"
                        "        return {'status': 'unresolved', 'task': task}\n"
                        "await safe('核实临时运营状态')",
                        "workflow-failure",
                    )
                ]
            )
        return ModelResponse(parts=[_load("deep-research", "load-deep")])

    result = await _agent(parent, worker_model=FunctionModel(broken_worker)).run(
        "按最新运营状态规划"
    )
    messages = result.all_messages()

    assert "unresolved" in result.output
    assert _tool_calls(messages, "run_workflow") == 1
    assert worker_calls == 1


async def test_second_workflow_attempt_is_host_rejected() -> None:
    """max_agent_calls=3 is not this invariant; the host gate is."""

    worker_model_calls = 0

    def worker(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages
        nonlocal worker_model_calls
        worker_model_calls += 1
        assert info.output_tools
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name=info.output_tools[0].name,
                    args={
                        "topic": "first research",
                        "claims": [],
                        "sources": [],
                        "media": [],
                        "unresolved": [],
                    },
                    tool_call_id=f"worker-final-{worker_model_calls}",
                )
            ]
        )

    def parent(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        returns = _tool_returns(messages, "run_workflow")
        if len(returns) >= 2:
            assert "DEEP_RESEARCH_ALREADY_USED" in str(returns[-1].content)
            return ModelResponse(parts=[TextPart("使用第一次 Findings 收口。")])
        if len(returns) == 1:
            return ModelResponse(
                parts=[
                    _workflow(
                        "await research_worker(task='第二次不应执行')",
                        "workflow-2",
                    )
                ]
            )
        if _tool_returns(messages, "load_capability"):
            return ModelResponse(
                parts=[
                    _workflow(
                        "await research_worker(task='第一次允许执行')",
                        "workflow-1",
                    )
                ]
            )
        return ModelResponse(parts=[_load("deep-research", "load-deep")])

    result = await _agent(parent, worker_model=FunctionModel(worker)).run(
        "故意尝试两次 Deep Research"
    )
    messages = result.all_messages()

    assert result.output == "使用第一次 Findings 收口。"
    assert _tool_calls(messages, "run_workflow") == 2
    assert len(_tool_returns(messages, "run_workflow")) == 2
    assert worker_model_calls == 1


async def test_simple_modification_of_existing_plan_needs_no_research() -> None:
    def parent(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages, info
        return ModelResponse(parts=[TextPart("已把 Day 2 和 Day 3 对调，其余约束保持不变。")])

    result = await _agent(parent).run("把刚才计划的第二天和第三天对调")
    messages = result.all_messages()

    assert "对调" in result.output
    assert _tool_calls(messages, "web_search") == 0
    assert _tool_calls(messages, "run_workflow") == 0


async def test_modification_with_one_fresh_fact_uses_quick_research(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "test")

    def parent(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        if _tool_returns(messages, "web_search"):
            return ModelResponse(parts=[TextPart("已按刚核实的当前预约规则修改 Day 2。")])
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="web_search",
                    args={"query": "故宫 当前 预约规则 官方"},
                    tool_call_id="modify-search",
                )
            ]
        )

    result = await _agent(parent).run("把第二天换成故宫，但先确认现在的预约规则")
    messages = result.all_messages()

    assert "预约规则" in result.output
    assert _tool_calls(messages, "web_search") == 1
    assert _tool_calls(messages, "run_workflow") == 0


async def test_poi_image_media_flows_from_worker_through_workflow_to_main(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POI Worker image_search -> ResearchFindings.media -> Main workflow result."""

    monkeypatch.setattr(settings, "APP_ENV", "test")

    def worker(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if _tool_returns(messages, "image_search"):
            assert info.output_tools
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name=info.output_tools[0].name,
                        args={
                            "topic": "故宫媒体",
                            "claims": [],
                            "sources": [],
                            "media": [
                                {
                                    "place_name": "故宫",
                                    "image_url": "https://images.example.test/poi.jpg",
                                    "thumbnail_url": "https://images.example.test/poi-thumb.jpg",
                                    "source_page_url": "https://example.test/poi",
                                    "title": "model copy",
                                    "width": 1,
                                    "height": 1,
                                    "source": "model",
                                }
                            ],
                            "unresolved": [],
                        },
                        tool_call_id="worker-media-final",
                    )
                ]
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="image_search",
                    args={"query": "故宫"},
                    tool_call_id="worker-image-search",
                )
            ]
        )

    def parent(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        workflow_returns = _tool_returns(messages, "run_workflow")
        if workflow_returns:
            rendered = str(workflow_returns[0].content)
            assert "https://images.example.test/poi.jpg" in rendered
            assert "https://example.test/poi" in rendered
            return ModelResponse(parts=[TextPart("Main 已收到故宫媒体候选。")])
        if _tool_returns(messages, "load_capability"):
            return ModelResponse(
                parts=[
                    _workflow(
                        "await research_worker(task='为故宫准备一个展示图片候选')",
                        "workflow-media",
                    )
                ]
            )
        return ModelResponse(parts=[_load("deep-research", "load-deep")])

    result = await _agent(parent, worker_model=FunctionModel(worker)).run(
        "做故宫计划并准备图片"
    )
    messages = result.all_messages()

    assert result.output == "Main 已收到故宫媒体候选。"
    assert _tool_calls(messages, "run_workflow") == 1


async def test_single_workflow_gate_resets_for_each_parent_run() -> None:
    worker_model = TestModel(
        custom_output_args={
            "topic": "per-run",
            "claims": [],
            "sources": [],
            "media": [],
            "unresolved": [],
        }
    )

    def parent(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del info
        if _tool_returns(messages, "run_workflow"):
            return ModelResponse(parts=[TextPart("done")])
        if _tool_returns(messages, "load_capability"):
            return ModelResponse(
                parts=[
                    _workflow(
                        "await research_worker(task='one allowed workflow this run')",
                        "workflow-once",
                    )
                ]
            )
        return ModelResponse(parts=[_load("deep-research", "load-deep")])

    agent = _agent(parent, worker_model=worker_model)
    first = await agent.run("request one")
    second = await agent.run("request two")

    assert first.output == "done"
    assert second.output == "done"
    assert _tool_calls(first.all_messages(), "run_workflow") == 1
    assert _tool_calls(second.all_messages(), "run_workflow") == 1
