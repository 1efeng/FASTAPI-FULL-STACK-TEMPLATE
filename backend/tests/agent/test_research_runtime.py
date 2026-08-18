"""Deterministic Worker trajectories for evidence attestation and media behavior."""

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
                "claims": [
                    {
                        "claim": "故宫明天开放",
                        "status": "verified",
                        "source_urls": ["https://www.dpm.org.cn/fake-url"],
                        "tool_evidence": [],
                    }
                ],
                "sources": [
                    {
                        "title": "故宫官网",
                        "url": "https://www.dpm.org.cn/fake-url",
                        "source_type": "official",
                    }
                ],
                "media": [],
                "unresolved": [],
            },
        )

    worker = build_research_agent(model=FunctionModel(model))
    state = ResearchRequestState()
    with bind_research_request_state(state):
        result = await worker.run("核实故宫开放")

    assert result.output.claims[0].status == "unresolved"
    assert result.output.claims[0].source_urls == []
    assert result.output.sources == []
    assert any("Host evidence validation failed" in item for item in result.output.unresolved)
    assert state.research_requests == result.usage.requests


async def test_research_progress_is_safe_and_request_scoped() -> None:
    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages
        return _final(
            info,
            {
                "topic": "预约",
                "claims": [],
                "sources": [],
                "media": [],
                "unresolved": [],
            },
        )

    worker = build_research_agent(model=FunctionModel(model))
    state = ResearchRequestState()
    prompt = '{"objective":"核验故宫预约规则","constraints":["2人"]}'
    with bind_research_request_state(state):
        await worker.run(prompt)

    events = []
    while not state.progress_queue.empty():
        events.append(state.progress_queue.get_nowait())

    assert events[0] == {
        "topic": "核验故宫预约规则",
        "status": "started",
        "stage": "research",
        "label": "开始核验研究主题",
    }
    assert any(
        event["stage"] == "analysis"
        and event["label"] == "正在拆分核验项：预约/放票"
        for event in events
    )
    assert events[-1]["status"] == "completed"
    assert events[-1]["stage"] == "research"
    assert all(
        set(event) == {"topic", "status", "stage", "label"}
        for event in events
    )


async def test_checklist_progress_uses_attested_results_and_fills_missing_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_url = "https://www.dpm.org.cn/visit"

    async def fake_search_web(**kwargs: Any) -> dict[str, Any]:
        del kwargs
        return {
            "query": "故宫 开放规则",
            "result_count": 1,
            "results": [{"title": "故宫博物院", "url": source_url, "summary": "官方规则"}],
        }

    fake_search_web.__name__ = "search_web"
    monkeypatch.setattr("app.agent.tools.research_tools.search_web", fake_search_web)

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if not _tool_returns(messages, "search_web"):
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="search_web",
                        args={"query": "故宫 开放规则", "authoritative": True},
                        tool_call_id="checklist-search",
                    )
                ]
            )
        return _final(
            info,
            {
                "topic": "北京核心景点开放、预约与门票",
                "summary": "故宫开放规则已确认，预约规则仍缺少可靠证据。",
                "verification_results": [
                    {
                        "item_id": "palace-opening",
                        "summary": "官方页面确认指定日期适用的开放规则。",
                        "status": "verified",
                        "source_urls": [source_url],
                        "tool_evidence": [],
                    }
                ],
                "claims": [],
                "sources": [
                    {
                        "title": "故宫博物院",
                        "url": source_url,
                        "source_type": "official",
                    }
                ],
                "media": [],
                "unresolved": [],
            },
        )

    prompt = json.dumps(
        {
            "title": "北京核心景点开放、预约与门票",
            "objective": "核验故宫开放与预约规则",
            "verification_items": [
                {
                    "id": "palace-opening",
                    "entity": "故宫博物院",
                    "aspect": "开放与闭馆规则",
                    "question": "指定日期是否开放？",
                },
                {
                    "id": "palace-reservation",
                    "entity": "故宫博物院",
                    "aspect": "预约与放票规则",
                    "question": "预约渠道、提前天数与放票时间是什么？",
                },
            ],
        },
        ensure_ascii=False,
    )
    worker = build_research_agent(model=FunctionModel(model))
    state = ResearchRequestState()
    with bind_research_request_state(state):
        result = await worker.run(prompt)

    assert [item.item_id for item in result.output.verification_results] == [
        "palace-opening",
        "palace-reservation",
    ]
    assert [item.status for item in result.output.verification_results] == [
        "verified",
        "unresolved",
    ]

    events = []
    while not state.progress_queue.empty():
        events.append(state.progress_queue.get_nowait())

    start = events[0]
    assert start["topic_title"] == "北京核心景点开放、预约与门票"
    assert [item["id"] for item in start["verification_items"]] == [
        "palace-opening",
        "palace-reservation",
    ]
    assert all(item["status"] == "pending" for item in start["verification_items"])
    assert any(
        event.get("item_id") == "palace-opening"
        and event.get("item_status") == "verified"
        and event["status"] == "completed"
        for event in events
    )
    assert any(
        event.get("item_id") == "palace-reservation"
        and event.get("item_status") == "unresolved"
        and event["status"] == "unresolved"
        for event in events
    )


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
                "claims": [],
                "sources": [],
                "media": [],
                "unresolved": [],
            },
        )

    worker = build_research_agent(model=FunctionModel(model))
    state = ResearchRequestState()
    prompt = '{"objective":"核验故宫预约规则"}'
    with bind_research_request_state(state):
        await worker.run(prompt)

    events = []
    while not state.progress_queue.empty():
        events.append(state.progress_queue.get_nowait())

    assert any(
        event == {
            "topic": "核验故宫预约规则",
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
    ) == "正在核验路线：北京北站 → 八达岭长城"
    assert _tool_progress_label(
        "get_weather",
        {"city": "北京"},
        completed=True,
    ) == "天气已核验：北京"
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


async def test_parallel_research_runs_keep_evidence_traces_isolated(
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
                "claims": [
                    {
                        "claim": "主题事实已核验",
                        "status": "verified",
                        "source_urls": [],
                        # Deliberately claim both tokens. Host attestation must keep
                        # only the tool that executed in this specific child run.
                        "tool_evidence": ["get_weather", "search_maps"],
                    }
                ],
                "sources": [],
                "media": [],
                "unresolved": [],
            },
        )

    agent = build_research_agent(model=FunctionModel(model))
    state = ResearchRequestState()
    with bind_research_request_state(state):
        weather_result, maps_result = await asyncio.gather(
            agent.run("天气主题"),
            agent.run("交通主题"),
        )

    assert weather_result.output.claims[0].tool_evidence == ["get_weather"]
    assert maps_result.output.claims[0].tool_evidence == ["search_maps"]
    assert len(state.research_runs) == 2


async def test_poi_tool_can_attest_structured_place_fact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_nearby(**kwargs: Any) -> dict[str, Any]:
        del kwargs
        return {
            "results": [
                {
                    "id": "B0FFG9V1R9",
                    "name": "四季民福烤鸭店(故宫店)",
                    "distance_m": 620,
                    "rating": 4.7,
                }
            ]
        }

    fake_nearby.__name__ = "search_nearby"
    monkeypatch.setattr("app.agent.tools.research_tools.search_nearby", fake_nearby)

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if not _tool_returns(messages, "search_nearby"):
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="search_nearby",
                        args={
                            "location": "116.397029,39.917839",
                            "keywords": "北京菜",
                        },
                        tool_call_id="nearby-evidence",
                    )
                ]
            )
        return _final(
            info,
            {
                "topic": "故宫附近餐厅",
                "claims": [
                    {
                        "claim": "四季民福故宫店距离中心点约620米，评分4.7",
                        "status": "verified",
                        "source_urls": [],
                        "tool_evidence": ["search_nearby"],
                    }
                ],
                "sources": [],
                "media": [],
                "unresolved": [],
            },
        )

    worker = build_research_agent(model=FunctionModel(model))
    result = await worker.run("核验故宫附近可选北京菜餐厅")

    assert result.output.claims[0].status == "verified"
    assert result.output.claims[0].tool_evidence == ["search_nearby"]


async def test_model_cannot_self_certify_tool_name_without_execution() -> None:
    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages
        return _final(
            info,
            {
                "topic": "天气",
                "claims": [
                    {
                        "claim": "明天北京晴",
                        "status": "verified",
                        "source_urls": [],
                        "tool_evidence": ["get_weather"],
                    }
                ],
                "sources": [],
                "media": [],
                "unresolved": [],
            },
        )

    worker = build_research_agent(model=FunctionModel(model))
    result = await worker.run("核实北京明天天气")

    assert result.output.claims[0].status == "unresolved"
    assert result.output.claims[0].tool_evidence == []


async def test_failed_weather_execution_cannot_attest_verified_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failed_weather(city: str, forecast: bool = False) -> str:
        del city, forecast
        raise RuntimeError("synthetic weather failure")

    monkeypatch.setattr("app.agent.tools.weather._get_weather", failed_weather)

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if _tool_returns(messages, "get_weather"):
            return _final(
                info,
                {
                    "topic": "天气失败",
                    "claims": [
                        {
                            "claim": "明天北京晴",
                            "status": "verified",
                            "source_urls": [],
                            "tool_evidence": ["get_weather"],
                        }
                    ],
                    "sources": [],
                    "media": [],
                    "unresolved": [],
                },
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="get_weather",
                    args={"city": "北京"},
                    tool_call_id="weather-fail",
                )
            ]
        )

    worker = build_research_agent(model=FunctionModel(model))
    result = await worker.run("核实北京天气")

    assert result.output.claims[0].status == "unresolved"
    assert result.output.claims[0].tool_evidence == []


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
                    "claims": [
                        {
                            "claim": "北京相关日期天气已查询",
                            "status": "verified",
                            "source_urls": [],
                            "tool_evidence": ["get_weather"],
                        }
                    ],
                    "sources": [],
                    "media": [],
                    "unresolved": [],
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
    result = await worker.run("只核实北京未来三天的天气风险")

    assert result.output.claims[0].status == "verified"
    assert result.output.claims[0].tool_evidence == ["get_weather"]
    assert result.output.media == []
    assert _tool_calls(result.all_messages(), "get_weather") == 1
