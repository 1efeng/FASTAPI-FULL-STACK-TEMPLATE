"""Deterministic trajectories for source hygiene and media behavior.

The research_agent only searches + summarizes. These tests verify:
- fabricated source URLs never survive into the summary (source hygiene);
- progress events are safe and request-scoped;
- parallel research runs keep their observed traces isolated;
- media discovery keeps its own lane (never migrates into web_urls sources).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agent.agents.research_agent import build_research_agent
from app.agent.research_runtime import (
    ResearchRequestState,
    _tool_progress_label,
    bind_research_request_state,
)


def _tool_returns(messages: list[ModelMessage], name: str) -> list[ToolReturnPart]:
    return [
        part
        for message in messages
        if isinstance(message, ModelRequest)
        for part in message.parts
        if isinstance(part, ToolReturnPart) and part.tool_name == name
    ]


def _tool_calls(messages: list[ModelMessage], name: str) -> int:
    return sum(
        1
        for message in messages
        for part in message.parts
        if isinstance(part, ToolCallPart) and part.tool_name == name
    )


def _final(info: AgentInfo, payload: dict[str, Any]) -> ModelResponse:
    assert info.output_tools, "ResearchFindings must be emitted through a structured output tool"
    return ModelResponse(
        parts=[
            ToolCallPart(
                tool_name=info.output_tools[0].name,
                args=payload,
                tool_call_id="research-final",
            )
        ]
    )


async def test_model_cannot_self_certify_invented_source_url() -> None:
    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages
        return _final(
            info,
            {
                "topic": "预约",
                "summary": "模型引用未实际搜索到的 URL。",
                "sources": [
                    {
                        "title": "故宫官网",
                        "url": "https://www.dpm.org.cn/fake-url",
                        "source_type": "official",
                    }
                ],
                "media": [],
            },
        )

    worker = build_research_agent(model=FunctionModel(model))
    state = ResearchRequestState()
    with bind_research_request_state(state):
        result = await worker.run("收集故宫开放背景")

    # Source hygiene: fabricated URLs never survive into the summary's sources.
    assert result.output.sources == []
    assert state.research_requests == result.usage.requests


async def test_research_progress_is_safe_and_request_scoped() -> None:
    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages
        return _final(
            info,
            {
                "topic": "预约",
                "summary": "背景已整理。",
                "sources": [],
                "media": [],
            },
        )

    worker = build_research_agent(model=FunctionModel(model))
    state = ResearchRequestState()
    prompt = '{"objective":"收集故宫预约规则背景","constraints":["2人"]}'
    with bind_research_request_state(state):
        await worker.run(prompt)

    events = []
    while not state.progress_queue.empty():
        events.append(state.progress_queue.get_nowait())

    assert events[0] == {
        "topic": "收集故宫预约规则背景",
        "status": "started",
        "stage": "research",
        "label": "开始检索研究主题",
    }
    assert any(
        event["stage"] == "analysis"
        and event["label"] == "正在拆分搜索重点：预约/放票"
        for event in events
    )
    assert events[-1]["status"] == "completed"
    assert events[-1]["stage"] == "research"
    assert all(
        set(event) == {"topic", "status", "stage", "label"}
        for event in events
    )


async def test_observed_source_url_survives_and_unobserved_is_filtered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_url = "https://www.dpm.org.cn/visit"

    async def fake_search_web(**kwargs: Any) -> dict[str, Any]:
        del kwargs
        return {
            "query": "故宫 开放规则",
            "result_count": 1,
            "results": [
                {"title": "故宫博物院", "url": observed_url, "summary": "官方规则"}
            ],
        }

    fake_search_web.__name__ = "search_web"
    monkeypatch.setattr("app.agent.tools.research_tools.search_web", fake_search_web)

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if not _tool_returns(messages, "search_web"):
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="search_web",
                        args={"query": "故宫 开放规则"},
                        tool_call_id="checklist-search",
                    )
                ]
            )
        return _final(
            info,
            {
                "topic": "故宫背景",
                "summary": "故宫开放规则背景已整理。",
                "sources": [
                    {
                        "title": "故宫博物院",
                        "url": observed_url,
                        "source_type": "official",
                    },
                    {
                        "title": "未搜索到的 URL",
                        "url": "https://example.com/unobserved",
                        "source_type": "official",
                    },
                ],
                "media": [],
            },
        )

    worker = build_research_agent(model=FunctionModel(model))
    result = await worker.run("收集故宫开放背景")

    # Only the actually-observed URL survives.
    assert [source.url for source in result.output.sources] == [observed_url]


async def test_host_owned_web_search_emits_safe_progress_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_search_web(**kwargs: Any) -> dict[str, Any]:
        del kwargs
        return {
            "query": "故宫 当前预约规则",
            "result_count": 1,
            "results": [{"url": "https://example.test/current", "title": "Current"}],
        }

    fake_search_web.__name__ = "search_web"
    monkeypatch.setattr("app.agent.tools.research_tools.search_web", fake_search_web)

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if not _tool_returns(messages, "search_web"):
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="search_web",
                        args={"query": "故宫 当前预约规则"},
                        tool_call_id="web-search-progress",
                    )
                ]
            )
        return _final(
            info,
            {
                "topic": "预约",
                "summary": "背景已整理。",
                "sources": [],
                "media": [],
            },
        )

    worker = build_research_agent(model=FunctionModel(model))
    state = ResearchRequestState()
    prompt = '{"objective":"收集故宫预约规则背景"}'
    with bind_research_request_state(state):
        await worker.run(prompt)

    events = []
    while not state.progress_queue.empty():
        events.append(state.progress_queue.get_nowait())

    assert any(
        event == {
            "topic": "收集故宫预约规则背景",
            "status": "checking",
            "stage": "web_search",
            "label": "最新来源已检索",
        }
        for event in events
    )


def test_tool_progress_labels_include_observable_targets() -> None:
    assert _tool_progress_label(
        "web_fetch",
        {"url": "https://www.dpm.org.cn/visit"},
        completed=False,
    ) == "正在读取来源：dpm.org.cn"
    assert _tool_progress_label(
        "search_maps",
        {"origin": "北京北站", "destination": "八达岭长城"},
        completed=False,
    ) == "正在检索路线：北京北站 → 八达岭长城"
    assert _tool_progress_label(
        "get_weather",
        {"city": "北京"},
        completed=True,
    ) == "天气背景已收集：北京"
    assert _tool_progress_label(
        "search_poi",
        {"keywords": "故宫博物院"},
        completed=False,
    ) == "正在查找地点：故宫博物院"
    assert _tool_progress_label(
        "search_nearby",
        {"keywords": "北京菜"},
        completed=True,
    ) == "附近地点已找到：北京菜"


async def test_parallel_research_runs_keep_traces_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_weather(city: str, forecast: bool = False) -> str:
        return f"{city}: sunny (forecast={forecast})"

    async def fake_maps(
        origin: str,
        destination: str,
        mode: str = "driving",
    ) -> str:
        return f"{origin} -> {destination} ({mode})"

    fake_weather.__name__ = "get_weather"
    fake_maps.__name__ = "search_maps"
    monkeypatch.setattr("app.agent.tools.research_tools.get_weather", fake_weather)
    monkeypatch.setattr("app.agent.tools.research_tools.search_maps", fake_maps)

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompt = str(messages[0])
        weather_topic = "天气主题" in prompt
        actual_tool = "get_weather" if weather_topic else "search_maps"
        if not _tool_returns(messages, actual_tool):
            if weather_topic:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="get_weather",
                            args={"city": "北京"},
                            tool_call_id="weather-evidence",
                        )
                    ]
                )
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="search_maps",
                        args={
                            "origin": "北京站",
                            "destination": "八达岭",
                            "mode": "transit",
                        },
                        tool_call_id="maps-evidence",
                    )
                ]
            )

        return _final(
            info,
            {
                "topic": "天气" if weather_topic else "交通",
                "summary": "背景已整理。",
                "sources": [],
                "media": [],
            },
        )

    agent = build_research_agent(model=FunctionModel(model))
    state = ResearchRequestState()
    with bind_research_request_state(state):
        weather_result, maps_result = await asyncio.gather(
            agent.run("天气主题"),
            agent.run("交通主题"),
        )

    assert weather_result.output.topic == "天气"
    assert maps_result.output.topic == "交通"
    assert len(state.research_runs) == 2


async def test_weather_only_worker_never_calls_image_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pure weather research must not create media findings."""

    async def fake_weather(city: str, forecast: bool = False) -> str:
        del forecast
        return f"{city}：晴，20℃"

    monkeypatch.setattr("app.agent.tools.weather._get_weather", fake_weather)

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if _tool_returns(messages, "get_weather"):
            return _final(
                info,
                {
                    "topic": "北京天气",
                    "summary": "北京相关日期天气背景已查询。",
                    "sources": [],
                    "media": [],
                },
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="get_weather",
                    args={"city": "北京", "forecast": True},
                    tool_call_id="weather-1",
                )
            ]
        )

    worker = build_research_agent(model=FunctionModel(model))
    result = await worker.run("只收集北京未来三天的天气背景")

    assert result.output.media == []
    assert _tool_calls(result.all_messages(), "get_weather") == 1