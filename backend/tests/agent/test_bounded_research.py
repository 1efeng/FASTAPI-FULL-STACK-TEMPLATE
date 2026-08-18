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


def _two_item_request() -> ResearchRequest:
    return ResearchRequest(
        title="Pass 比较",
        objective="比较全国 JR Pass 与区域 Pass 的覆盖与价格",
        verification_items=[
            VerificationItem(
                id="opening",
                entity="八达岭长城",
                aspect="开放与预约",
                question="指定日期是否开放并需要预约？",
            ),
            VerificationItem(
                id="transit",
                entity="北京北站→八达岭",
                aspect="交通时间",
                question="公共交通耗时是多少？",
            ),
        ],
    )


async def test_empty_item_ids_are_rejected_by_structured_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Planner action with ``item_ids=[]`` cannot execute any tool.

    The structured ``ResearchPlan`` schema requires at least one item id per action.
    An empty batch fails structured output validation, so the bounded run degrades
    to unresolved and no Host tool is invoked.
    """

    tool_calls = 0

    async def fake_search_web(**kwargs: Any) -> dict[str, Any]:
        nonlocal tool_calls
        tool_calls += 1
        del kwargs
        return {"query": "x", "result_count": 0, "results": []}

    monkeypatch.setattr("app.agent.bounded_research.search_web", fake_search_web)

    model_calls = 0

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
                            "item_ids": [],
                            "query": "八达岭长城 开放 预约",
                            "authoritative": True,
                        }
                    ]
                },
            )
        return _output(
            info,
            {
                "topic": "Pass 比较",
                "summary": "不应有证据",
                "verification_results": [],
                "claims": [],
                "sources": [],
                "media": [],
                "unresolved": [],
            },
        )

    state = ResearchRequestState()
    with bind_research_request_state(state):
        result = await run_bounded_research(
            _two_item_request(),
            model=FunctionModel(model),
        )

    assert tool_calls == 0
    assert all(item.status == "unresolved" for item in result.verification_results)


async def test_unknown_item_id_action_is_dropped_without_tool_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Planner output binding to a non-existent item id must not run any tool.

    Host validation drops the action without correction, fuzzy matching, checklist
    expansion, or a Planner re-request. The run stays intact and the input item is
    unresolved because it has no executed evidence.
    """

    tool_calls = 0

    async def fake_search_web(**kwargs: Any) -> dict[str, Any]:
        nonlocal tool_calls
        tool_calls += 1
        del kwargs
        return {"query": "x", "result_count": 0, "results": []}

    monkeypatch.setattr("app.agent.bounded_research.search_web", fake_search_web)

    model_calls = 0

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
                            "item_ids": ["unknown"],
                            "query": "八达岭长城 开放 预约",
                            "authoritative": True,
                        }
                    ]
                },
            )
        return _output(
            info,
            {
                "topic": "Pass 比较",
                "summary": "无有效证据",
                "verification_results": [],
                "claims": [],
                "sources": [],
                "media": [],
                "unresolved": [],
            },
        )

    state = ResearchRequestState()
    with bind_research_request_state(state):
        result = await run_bounded_research(
            _two_item_request(),
            model=FunctionModel(model),
        )

    assert tool_calls == 0
    assert all(item.status == "unresolved" for item in result.verification_results)


async def test_valid_item_binding_executes_tool_and_verifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Planner action bound to a real item id executes and can be verified."""

    model_calls = 0
    source_url = "https://example.com/official-opening"

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
                "topic": "Pass 比较",
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
        del count, time_range, authoritative, query_rewrite, max_snippet_length
        return {
            "query": query,
            "result_count": 1,
            "results": [
                {
                    "title": "官方公告",
                    "url": source_url,
                    "site_name": "官方",
                    "authority": "very_high",
                    "summary": "指定日期开放且需预约。",
                }
            ],
        }

    monkeypatch.setattr("app.agent.bounded_research.search_web", fake_search_web)
    monkeypatch.setattr(
        "app.agent.bounded_research.WebFetchLocalTool",
        lambda **kwargs: None,
    )
    # Ensure no authoritative fetch happens: keep the fetch budget at the tool
    # call limit used by the existing two-model-call test path.

    state = ResearchRequestState()
    with bind_research_request_state(state):
        result = await run_bounded_research(
            _two_item_request(),
            model=FunctionModel(model),
        )

    opening = next(r for r in result.verification_results if r.item_id == "opening")
    transit = next(r for r in result.verification_results if r.item_id == "transit")
    assert opening.status == "verified"
    assert opening.source_urls == [source_url]
    assert transit.status == "unresolved"


async def test_cross_item_evidence_misuse_is_downgraded_to_unresolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A result must only use evidence observed for its own verification item.

    search_web runs for ``opening`` and search_maps runs for ``transit``. The
    Finalizer deliberately claims ``opening`` with ``tool_evidence=["search_maps"]``
    and ``transit`` with the URL observed by the ``opening`` search. Item-scoped
    normalization must strip the foreign evidence and downgrade both to unresolved.
    """

    source_url = "https://example.com/official-opening"

    async def fake_search_web(
        query: str,
        count: int = 10,
        time_range: str | None = None,
        authoritative: bool = False,
        query_rewrite: bool = False,
        max_snippet_length: int = 200,
    ) -> dict[str, Any]:
        del count, time_range, authoritative, query_rewrite, max_snippet_length
        return {
            "query": query,
            "result_count": 1,
            "results": [
                {
                    "title": "官方公告",
                    "url": source_url,
                    "site_name": "官方",
                    "authority": "very_high",
                    "summary": "指定日期开放且需预约。",
                }
            ],
        }

    async def fake_maps(origin: str, destination: str, mode: str = "driving") -> str:
        del mode
        return f"{origin} → {destination}（公交）预计 70 分钟"

    monkeypatch.setattr("app.agent.bounded_research.search_web", fake_search_web)
    monkeypatch.setattr("app.agent.bounded_research.search_maps", fake_maps)
    monkeypatch.setattr(
        "app.agent.bounded_research.WebFetchLocalTool",
        lambda **kwargs: None,
    )

    model_calls = 0

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
                        },
                        {
                            "tool": "search_maps",
                            "item_ids": ["transit"],
                            "origin": "北京北站",
                            "destination": "八达岭",
                            "mode": "transit",
                        },
                    ]
                },
            )
        return _output(
            info,
            {
                "topic": "Pass 比较",
                "summary": "Finalizer 故意交叉引用证据。",
                "verification_results": [
                    {
                        "item_id": "opening",
                        "summary": "用 transit 的工具自证。",
                        "source_urls": [],
                        "tool_evidence": ["search_maps"],
                        "status": "verified",
                    },
                    {
                        "item_id": "transit",
                        "summary": "用 opening 的 URL 自证。",
                        "source_urls": [source_url],
                        "tool_evidence": [],
                        "status": "verified",
                    },
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

    state = ResearchRequestState()
    with bind_research_request_state(state):
        result = await run_bounded_research(
            _two_item_request(),
            model=FunctionModel(model),
        )

    opening = next(r for r in result.verification_results if r.item_id == "opening")
    transit = next(r for r in result.verification_results if r.item_id == "transit")
    assert opening.status == "unresolved"
    assert opening.tool_evidence == []
    assert transit.status == "unresolved"
    assert transit.source_urls == []
    assert any("Draft evidence incomplete" in item for item in result.unresolved)
