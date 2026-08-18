"""Bounded research context-compressor contracts."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agent.agents.research_agent import ResearchRequest, VerificationItem
from app.agent.bounded_research import run_bounded_research
from app.agent.research_runtime import ResearchRequestState, bind_research_request_state


def _output(info: AgentInfo, payload: dict[str, Any]) -> ModelResponse:
    assert info.output_tools
    return ModelResponse(
        parts=[
            ToolCallPart(
                tool_name=info.output_tools[0].name,
                args=payload,
                tool_call_id="structured-output",
            )
        ]
    )


def _request() -> ResearchRequest:
    return ResearchRequest(
        title="八达岭返程可行性",
        objective="判断八达岭游玩后赶北京西站高铁是否可执行",
        verification_items=[
            VerificationItem(
                id="opening",
                entity="八达岭长城",
                aspect="开放与预约",
                question="指定日期是否开放并需要预约？",
            )
        ],
    )


async def test_bounded_research_uses_two_model_calls_and_host_attestation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_calls = 0
    source_url = "https://example.com/official"

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal model_calls
        del messages
        model_calls += 1
        if model_calls == 1:
            return _output(
                info,
                {
                    "actions": [
                        {
                            "tool": "search_web",
                            "item_ids": ["opening"],
                            "query": "八达岭长城 开放 预约",
                            "authoritative": True,
                        }
                    ]
                },
            )
        return _output(
            info,
            {
                "topic": "八达岭返程可行性",
                "summary": "指定日期开放且需预约。",
                "verification_results": [
                    {
                        "item_id": "opening",
                        "summary": "指定日期开放且需预约。",
                        "source_urls": [source_url],
                        "status": "verified",
                    }
                ],
                "claims": [],
                "sources": [
                    {
                        "title": "官方公告",
                        "url": source_url,
                        "source_type": "official",
                    }
                ],
                "media": [],
                "unresolved": [],
            },
        )

    async def fake_search_web(
        query: str,
        count: int = 10,
        time_range: str | None = None,
        authoritative: bool = False,
        query_rewrite: bool = False,
        max_snippet_length: int = 200,
    ) -> dict[str, Any]:
        del time_range, query_rewrite
        assert query == "八达岭长城 开放 预约"
        assert count == 3
        assert authoritative is True
        assert max_snippet_length == 200
        return {
            "query": query,
            "result_count": 1,
            "results": [
                {
                    "title": "官方公告",
                    "url": source_url,
                    "site_name": "官方",
                    "authority": "官方",
                    "summary": "指定日期开放且需预约。",
                }
            ],
        }

    class FakeFetcher:
        def __init__(self, **kwargs: object) -> None:
            assert kwargs["max_content_length"] == 8_000

        async def __call__(self, url: str) -> dict[str, str]:
            assert url == source_url
            return {"url": url, "title": "官方公告", "content": "指定日期开放且需预约。"}

    monkeypatch.setattr("app.agent.bounded_research.search_web", fake_search_web)
    monkeypatch.setattr("app.agent.bounded_research.WebFetchLocalTool", FakeFetcher)

    state = ResearchRequestState()
    with bind_research_request_state(state):
        result = await run_bounded_research(
            _request(),
            model=FunctionModel(model),
        )

    assert model_calls == 2
    assert result.verification_results[0].status == "verified"
    assert result.verification_results[0].source_urls == [source_url]
    assert len(state.research_runs) == 1
    assert state.research_runs[0].requests == 2
    assert state.research_runs[0].tool_calls == 2  # search + authoritative fetch


async def test_bounded_research_preserves_dedicated_tool_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_calls = 0
    request = ResearchRequest(
        objective="核验北京北站到八达岭交通",
        verification_items=[
            VerificationItem(
                id="route",
                entity="北京北站→八达岭",
                aspect="交通时间",
                question="公共交通耗时是多少？",
            )
        ],
    )

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal model_calls
        del messages
        model_calls += 1
        if model_calls == 1:
            return _output(
                info,
                {
                    "actions": [
                        {
                            "tool": "search_maps",
                            "item_ids": ["route"],
                            "origin": "北京北站",
                            "destination": "八达岭",
                            "mode": "transit",
                        }
                    ]
                },
            )
        return _output(
            info,
            {
                "topic": "交通",
                "summary": "路线已核验。",
                "verification_results": [
                    {
                        "item_id": "route",
                        "summary": "约 70 分钟。",
                        "tool_evidence": ["search_maps"],
                        "status": "verified",
                    }
                ],
                "claims": [],
                "sources": [],
                "media": [],
                "unresolved": [],
            },
        )

    async def fake_maps(origin: str, destination: str, mode: str = "driving") -> str:
        assert (origin, destination, mode) == ("北京北站", "八达岭", "transit")
        return "北京北站 → 八达岭（公交）预计 70 分钟"

    monkeypatch.setattr("app.agent.bounded_research.search_maps", fake_maps)

    result = await run_bounded_research(request, model=FunctionModel(model))

    assert model_calls == 2
    assert result.verification_results[0].status == "verified"
    assert result.verification_results[0].tool_evidence == ["search_maps"]


async def test_bounded_research_provider_failure_degrades_to_unresolved() -> None:
    def failing_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages, info
        raise ModelAPIError("research-model", "synthetic provider failure")

    state = ResearchRequestState()
    with bind_research_request_state(state):
        result = await run_bounded_research(
            _request(),
            model=FunctionModel(failing_model),
        )

    assert result.verification_results[0].status == "unresolved"
    assert result.unresolved == ["当前研究主题暂时无法可靠完成。"]
    assert len(state.research_runs) == 1
    assert state.research_runs[0].requests == 1
    assert state.research_runs[0].tool_calls == 0
