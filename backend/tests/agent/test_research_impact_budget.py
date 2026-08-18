"""Impact-aware Research Task budget and unresolved triage contracts.

Covers the Research Decision Layer requirements:
- Research Task (distinct verification item) is the budget unit, NOT tool calls;
- multiple actions for the same item stay within one task slot;
- high/unknown impact over-budget items fall back to unresolved;
- unresolved is triaged by impact: high/unknown blocks, medium warns, low ignored;
- Evidence Sufficiency is judged per Research Task, not per whole run.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agent.agents.research_agent import (
    ResearchFindings,
    ResearchRequest,
    VerificationItem,
    VerificationResult,
)
from app.agent.bounded_research import (
    WebSearchAction,
    _cap_actions_by_impact,
    classify_research_results,
    evidence_sufficiency,
    run_bounded_research,
)
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


def _items(specs: list[tuple[str, str]]) -> list[VerificationItem]:
    return [
        VerificationItem(
            id=item_id,
            entity=item_id,
            aspect="核验",
            question=f"{item_id} 是否可确认？",
            impact=impact,
        )
        for item_id, impact in specs
    ]


def _request(specs: list[tuple[str, str]]) -> ResearchRequest:
    return ResearchRequest(
        objective="impact 预算核验",
        verification_items=_items(specs),
    )


def _findings(
    request: ResearchRequest,
    resolved: list[tuple[str, str]],
) -> ResearchFindings:
    by_id = dict(resolved)
    has_verified = any(status == "verified" for status in by_id.values())
    return ResearchFindings(
        topic="impact 预算核验",
        verification_results=[
            VerificationResult(
                item_id=item.id,
                summary=(
                    "已核验。"
                    if by_id.get(item.id, "unresolved") in {"verified", "conflicting"}
                    else "未能确认。"
                ),
                source_urls=(
                    ["https://example.com/official"]
                    if by_id.get(item.id, "unresolved") == "verified"
                    else []
                ),
                tool_evidence=(
                    ["search_maps"]
                    if by_id.get(item.id, "unresolved") == "conflicting"
                    else []
                ),
                status=by_id.get(item.id, "unresolved"),  # type: ignore[arg-type]
            )
            for item in request.verification_items
        ],
        sources=(
            [{"title": "官方", "url": "https://example.com/official"}]
            if has_verified
            else []
        ),
        unresolved=[],
    )


# ---------------------------------------------------------------------------
# Host hard cap: Research Task (distinct item) count, not tool call count.
# ---------------------------------------------------------------------------


def _web_action(item_id: str, query: str = "q") -> WebSearchAction:
    return WebSearchAction(
        item_ids=[item_id],
        query=query,
        authoritative=True,
    )


def _maps_action(item_id: str) -> Any:
    from app.agent.bounded_research import RouteAction

    return RouteAction(
        item_ids=[item_id],
        origin="北京北站",
        destination="八达岭",
        mode="transit",
    )


def test_high_impact_over_budget_actions_are_dropped() -> None:
    """Actions serving a 6th high item are dropped; the item stays unresolved."""
    request = _request(
        [
            ("h1", "high"),
            ("h2", "high"),
            ("h3", "high"),
            ("h4", "high"),
            ("h5", "high"),
            ("h6", "high"),
        ]
    )
    actions = [_web_action(f"h{i}") for i in range(1, 7)]
    kept = _cap_actions_by_impact(request, actions)
    assert [a.item_ids[0] for a in kept] == ["h1", "h2", "h3", "h4", "h5"]


def test_medium_impact_over_budget_actions_are_dropped() -> None:
    request = _request(
        [("m1", "medium"), ("m2", "medium"), ("m3", "medium"), ("m4", "medium")]
    )
    kept = _cap_actions_by_impact(request, [_web_action(f"m{i}") for i in range(1, 5)])
    assert [a.item_ids[0] for a in kept] == ["m1", "m2", "m3"]


def test_unknown_impact_shares_high_budget() -> None:
    request = _request(
        [
            ("u1", "unknown"),
            ("h1", "high"),
            ("h2", "high"),
            ("h3", "high"),
            ("h4", "high"),
            ("h5", "high"),
        ]
    )
    actions = [_web_action("u1")] + [_web_action(f"h{i}") for i in range(1, 6)]
    kept = _cap_actions_by_impact(request, actions)
    # u1 (unknown -> high) consumes one of the 5 high slots, so only 4 of the
    # 5 explicit high items survive.
    assert len(kept) == 5
    assert "u1" in [a.item_ids[0] for a in kept]


def test_multiple_actions_for_same_item_share_one_task_slot() -> None:
    """POI + Maps + Web for the SAME item is one Research Task, all preserved."""
    request = _request([("badaling", "high")])
    actions = [_web_action("badaling", query="八达岭 开放"), _maps_action("badaling")]
    kept = _cap_actions_by_impact(request, actions)
    assert len(kept) == 2
    assert all(a.item_ids == ["badaling"] for a in kept)


def test_low_impact_actions_never_consume_budget() -> None:
    request = _request([("low1", "low"), ("high1", "high")])
    kept = _cap_actions_by_impact(
        request,
        [_web_action("low1"), _web_action("high1")],
    )
    assert [a.item_ids[0] for a in kept] == ["high1"]


# ---------------------------------------------------------------------------
# Unresolved triage by impact.
# ---------------------------------------------------------------------------


def test_unresolved_high_impact_blocks() -> None:
    request = _request([("h1", "high"), ("m1", "medium"), ("l1", "low")])
    findings = _findings(request, [])
    statuses = classify_research_results(request, findings)
    by_id = {s.item_id: s for s in statuses}
    assert by_id["h1"].blocked is True
    assert by_id["h1"].warning is False
    assert by_id["m1"].blocked is False
    assert by_id["m1"].warning is True
    assert by_id["l1"].blocked is False
    assert by_id["l1"].warning is False


def test_unresolved_unknown_impact_blocks_like_high() -> None:
    request = _request([("u1", "unknown")])
    statuses = classify_research_results(request, _findings(request, []))
    assert statuses[0].impact == "high"
    assert statuses[0].blocked is True


def test_resolved_high_impact_does_not_block() -> None:
    request = _request([("h1", "high"), ("m1", "medium")])
    findings = _findings(request, [("h1", "verified"), ("m1", "unresolved")])
    statuses = classify_research_results(request, findings)
    by_id = {s.item_id: s for s in statuses}
    assert by_id["h1"].blocked is False
    assert by_id["m1"].blocked is False
    assert by_id["m1"].warning is True


# ---------------------------------------------------------------------------
# Evidence Sufficiency is per Research Task, not per whole run.
# ---------------------------------------------------------------------------


def test_evidence_sufficiency_true_when_only_high_tasks_resolved() -> None:
    request = _request([("h1", "high"), ("m1", "medium"), ("l1", "low")])
    # h1 resolved; m1/l1 unresolved must NOT force more searches.
    findings = _findings(request, [("h1", "verified")])
    assert evidence_sufficiency(request, findings) is True


def test_evidence_sufficiency_false_when_any_high_task_unresolved() -> None:
    request = _request([("h1", "high"), ("h2", "high")])
    findings = _findings(request, [("h1", "verified")])
    assert evidence_sufficiency(request, findings) is False


# ---------------------------------------------------------------------------
# End-to-end: over-budget high item degrades to unresolved inside a run.
# ---------------------------------------------------------------------------


async def test_run_drops_over_budget_high_item_to_unresolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 6th high item has no executed evidence and resolves unresolved."""
    request = _request(
        [
            ("h1", "high"),
            ("h2", "high"),
            ("h3", "high"),
            ("h4", "high"),
            ("h5", "high"),
            ("h6", "high"),
        ]
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
                            "item_ids": [f"h{i}"],
                            "query": f"h{i} 核验",
                            "authoritative": True,
                        }
                        for i in range(1, 7)
                    ]
                },
            )
        return _output(
            info,
            {
                "topic": "impact 预算",
                "summary": "前五项已核验。",
                "verification_results": [
                    {
                        "item_id": f"h{i}",
                        "summary": "已核验。",
                        "source_urls": ["https://example.com/official"],
                        "status": "verified",
                    }
                    for i in range(1, 6)
                ],
                "claims": [],
                "sources": [
                    {
                        "title": "官方",
                        "url": "https://example.com/official",
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
                    "title": "官方",
                    "url": "https://example.com/official",
                    "site_name": "官方",
                    "authority": "very_high",
                    "summary": "已核验。",
                }
            ],
        }

    monkeypatch.setattr("app.agent.bounded_research.search_web", fake_search_web)
    monkeypatch.setattr(
        "app.agent.bounded_research.WebFetchLocalTool",
        lambda **kwargs: None,
    )

    state = ResearchRequestState()
    with bind_research_request_state(state):
        result = await run_bounded_research(request, model=FunctionModel(model))

    by_id = {r.item_id: r for r in result.verification_results}
    # Only 5 distinct high items were served; h6 never executed a tool.
    assert by_id["h6"].status == "unresolved"
    # The 5 in-budget items could verify (their packets executed and are attested).
    assert by_id["h1"].status == "verified"
    assert state.research_runs[0].tool_calls == 5