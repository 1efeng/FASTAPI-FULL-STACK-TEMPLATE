"""Deterministic Worker trajectories for evidence attestation and media behavior."""

from __future__ import annotations

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

from app.agent.research_runtime import ResearchRequestState, bind_research_request_state
from app.agent.subagents.research_worker import build_research_worker
from app.core.config import settings


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

    worker = build_research_worker(model=FunctionModel(model))
    state = ResearchRequestState()
    with bind_research_request_state(state):
        result = await worker.run("核实故宫开放")

    assert result.output.claims[0].status == "unresolved"
    assert result.output.claims[0].source_urls == []
    assert result.output.sources == []
    assert any("Host evidence validation failed" in item for item in result.output.unresolved)
    assert state.worker_requests == result.usage.requests


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

    worker = build_research_worker(model=FunctionModel(model))
    result = await worker.run("核实北京明天天气")

    assert result.output.claims[0].status == "unresolved"
    assert result.output.claims[0].tool_evidence == []


async def test_actual_web_search_attests_verified_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "test")

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if _tool_returns(messages, "web_search"):
            return _final(
                info,
                {
                    "topic": "预约",
                    "claims": [
                        {
                            "claim": "当前预约规则已核实",
                            "status": "verified",
                            "source_urls": ["https://example.test/search"],
                            "tool_evidence": [],
                        }
                    ],
                    "sources": [
                        {
                            "title": "Test official result",
                            "url": "https://example.test/search",
                            "source_type": "official",
                        }
                    ],
                    "media": [],
                    "unresolved": [],
                },
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="web_search",
                    args={"query": "故宫 当前 预约 官方"},
                    tool_call_id="web-search-1",
                )
            ]
        )

    worker = build_research_worker(model=FunctionModel(model))
    result = await worker.run("核实故宫预约")

    assert result.output.claims[0].status == "verified"
    assert result.output.claims[0].source_urls == ["https://example.test/search"]
    assert [source.url for source in result.output.sources] == ["https://example.test/search"]
    assert _tool_calls(result.all_messages(), "web_search") == 1


async def test_poi_worker_image_search_trajectory_preserves_attested_media(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POI Worker -> image_search -> DDGS-normalized result -> Findings.media."""

    monkeypatch.setattr(settings, "APP_ENV", "test")

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if _tool_returns(messages, "image_search"):
            return _final(
                info,
                {
                    "topic": "故宫 POI 图片",
                    "claims": [],
                    "sources": [],
                    "media": [
                        {
                            "place_name": "故宫",
                            "image_url": "https://images.example.test/poi.jpg",
                            "thumbnail_url": "https://images.example.test/poi-thumb.jpg",
                            "source_page_url": "https://example.test/poi",
                            # Deliberately wrong model-declared metadata: Host must
                            # replace it from the actual normalized image_search row.
                            "title": "invented title",
                            "width": 1,
                            "height": 2,
                            "source": "invented.example",
                        }
                    ],
                    "unresolved": [],
                },
            )
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="image_search",
                    args={"query": "故宫"},
                    tool_call_id="image-search-1",
                )
            ]
        )

    state = ResearchRequestState()
    worker = build_research_worker(model=FunctionModel(model))
    with bind_research_request_state(state):
        result = await worker.run("为最终方案中的故宫寻找展示图片")

    assert _tool_calls(result.all_messages(), "image_search") == 1
    assert len(result.output.media) == 1
    assert result.output.media[0].place_name == "故宫"
    assert result.output.media[0].image_url == "https://images.example.test/poi.jpg"
    assert result.output.media[0].source_page_url == "https://example.test/poi"
    assert result.output.media[0].title == "[FAKE IMAGE] 故宫"
    assert result.output.media[0].width == 1200
    assert result.output.media[0].height == 800
    assert result.output.media[0].source == "example.test"
    assert state.worker_tool_calls >= 1


async def test_failed_weather_execution_cannot_attest_verified_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failed_weather(city: str, forecast: bool = False) -> str:
        del city, forecast
        return "天气查询暂时失败：RuntimeError"

    monkeypatch.setattr("app.agent.tools.research_tools.get_weather", failed_weather)

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

    worker = build_research_worker(model=FunctionModel(model))
    result = await worker.run("核实北京天气")

    assert result.output.claims[0].status == "unresolved"
    assert result.output.claims[0].tool_evidence == []


async def test_weather_only_worker_never_calls_image_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pure weather research must not spend a media search."""

    async def fake_weather(city: str, forecast: bool = False) -> str:
        del forecast
        return f"{city}：晴，20℃"

    # build_research_tools resolves this module global when the Worker is built.
    monkeypatch.setattr("app.agent.tools.research_tools.get_weather", fake_weather)

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

    worker = build_research_worker(model=FunctionModel(model))
    result = await worker.run("只核实北京未来三天的天气风险")

    assert result.output.claims[0].status == "verified"
    assert result.output.claims[0].tool_evidence == ["get_weather"]
    assert result.output.media == []
    assert _tool_calls(result.all_messages(), "get_weather") == 1
    assert _tool_calls(result.all_messages(), "image_search") == 0
