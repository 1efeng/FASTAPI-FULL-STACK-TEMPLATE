"""Deterministic Worker trajectories for evidence attestation and media behavior."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    NativeToolCallPart,
    NativeToolReturnPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agent.research_runtime import (
    ResearchRequestState,
    WorkerEvidenceTrace,
    _attest_findings,
    _record_native_search_response,
    bind_research_request_state,
)
from app.agent.subagents.research_worker import (
    EvidenceClaim,
    EvidenceSource,
    ResearchFindings,
    build_research_worker,
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


async def test_native_web_search_attests_verified_source() -> None:
    source_url = "https://example.test/search"
    trace = WorkerEvidenceTrace()
    _record_native_search_response(
        ModelResponse(
            parts=[
                NativeToolCallPart(
                    tool_name="web_search",
                    args={"open_page": {"url": source_url}},
                    tool_call_id="web-search-1",
                ),
                NativeToolReturnPart(
                    tool_name="web_search",
                    content={"sources": [{"url": source_url}]},
                    tool_call_id="web-search-1",
                ),
            ]
        ),
        trace,
    )

    findings = _attest_findings(
        ResearchFindings(
            topic="预约",
            claims=[
                EvidenceClaim(
                    claim="当前预约规则已核实",
                    status="verified",
                    source_urls=[source_url],
                )
            ],
            sources=[EvidenceSource(title="Test official result", url=source_url)],
        ),
        trace,
    )

    assert findings.claims[0].status == "verified"
    assert findings.claims[0].source_urls == [source_url]
    assert [source.url for source in findings.sources] == [source_url]
    assert "web_search" in trace.successful_tools


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

    worker = build_research_worker(model=FunctionModel(model))
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

    worker = build_research_worker(model=FunctionModel(model))
    result = await worker.run("只核实北京未来三天的天气风险")

    assert result.output.claims[0].status == "verified"
    assert result.output.claims[0].tool_evidence == ["get_weather"]
    assert result.output.media == []
    assert _tool_calls(result.all_messages(), "get_weather") == 1
