"""Phase 1 contracts for the iterative research_agent."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.agent.agents.research_agent import (
    RESEARCH_AGENT_NAME,
    EvidenceClaim,
    EvidenceSource,
    ResearchFindings,
    ResearchRequest,
    VerificationItem,
    VerificationResult,
    build_research_agent,
)
from app.agent.research_runtime import ResearchRequestState, bind_research_request_state


def _structured_output(info: AgentInfo, payload: dict[str, Any]) -> ModelResponse:
    assert info.output_tools, "ResearchFindings must use structured output"
    return ModelResponse(
        parts=[
            ToolCallPart(
                tool_name=info.output_tools[0].name,
                args=payload,
                tool_call_id="research-agent-final",
            )
        ]
    )


def test_research_request_requires_verification_items() -> None:
    # Runtime contract: an empty checklist is invalid. The type checker can't see
    # this because the field constraint is expressed via Field(min_length=1).
    with pytest.raises(ValidationError):
        ResearchRequest(objective="比较东京到箱根交通 Pass")  # type: ignore[call-arg]


def test_research_request_accepts_atomic_checklist_and_rejects_duplicate_ids() -> None:
    item = VerificationItem(
        id="pass-price",
        entity="箱根周游券",
        aspect="当前票价",
        question="当前成人票价是多少？",
    )
    request = ResearchRequest(
        title="箱根交通 Pass 比较",
        objective="比较东京到箱根交通 Pass",
        verification_items=[item],
    )

    assert request.title == "箱根交通 Pass 比较"
    assert request.verification_items[0].id == "pass-price"
    assert request.verification_items[0].impact == "unknown"

    with pytest.raises(ValidationError, match="verification item ids must be unique"):
        ResearchRequest(
            objective="重复 checklist",
            verification_items=[item, item.model_copy()],
        )


def test_verification_item_defaults_to_unknown_and_accepts_all_levels() -> None:
    defaulted = VerificationItem(
        id="opening",
        entity="故宫博物院",
        aspect="开放",
        question="指定日期是否开放？",
    )
    assert defaulted.impact == "unknown"

    medium = VerificationItem(
        id="restaurant",
        entity="某餐厅",
        aspect="体验",
        question="哪家餐厅更适合情侣晚餐？",
        impact="medium",
    )
    assert medium.impact == "medium"

    low = VerificationItem(
        id="photo",
        entity="夜景机位",
        aspect="拍照角度",
        question="哪个机位适合情侣打卡？",
        impact="low",
    )
    assert low.impact == "low"

    with pytest.raises(ValidationError, match="impact"):
        VerificationItem(
            id="bad",
            entity="x",
            aspect="y",
            question="z",
            impact="critical",  # type: ignore[arg-type]
        )


def test_verified_claim_still_requires_evidence() -> None:
    with pytest.raises(ValidationError, match="verified claims require"):
        EvidenceClaim(claim="当前票价为 X", status="verified")

    claim = EvidenceClaim(
        claim="官方页面确认当前规则",
        status="verified",
        source_urls=["https://official.example/rule"],
    )
    with pytest.raises(ValidationError, match="missing from sources"):
        ResearchFindings(topic="规则", claims=[claim])


def test_verification_result_requires_evidence_when_resolved() -> None:
    with pytest.raises(ValidationError, match="verification results require evidence"):
        VerificationResult(
            item_id="palace-price",
            summary="旺季票价已确认",
            status="verified",
        )

    unresolved = VerificationResult(
        item_id="palace-price",
        summary="暂未找到可靠当前价格",
        status="unresolved",
    )
    assert unresolved.status == "unresolved"


def test_research_findings_adds_summary_without_weakening_evidence_contract() -> None:
    url = "https://official.example/pass"
    findings = ResearchFindings(
        topic="交通 Pass",
        summary="当前可选方案已经核验到足以供 Main 比较。",
        verification_results=[
            VerificationResult(
                item_id="pass-scope",
                summary="官方页面列出该 Pass 的覆盖范围",
                status="verified",
                source_urls=[url],
            )
        ],
        claims=[
            EvidenceClaim(
                claim="官方页面列出该 Pass 的覆盖范围",
                status="verified",
                source_urls=[url],
            )
        ],
        sources=[EvidenceSource(title="Official Pass", url=url, source_type="official")],
    )

    assert findings.summary is not None
    assert findings.verification_results[0].status == "verified"
    assert findings.claims[0].status == "verified"


async def test_build_research_agent_has_host_owned_search_and_no_native_web_search() -> None:
    observed: dict[str, set[str]] = {}

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages
        observed["function_tools"] = {tool.name for tool in info.function_tools}
        observed["native_tools"] = {
            type(tool).__name__ for tool in info.model_request_parameters.native_tools
        }
        return _structured_output(
            info,
            {
                "topic": "箱根交通",
                "summary": "证据足够供 Main 决策。",
                "claims": [],
                "sources": [],
                "media": [],
                "unresolved": [],
            },
        )

    agent = build_research_agent(model=FunctionModel(model))
    result = await agent.run("研究东京到箱根交通方案")

    assert agent.name == RESEARCH_AGENT_NAME == "research_agent"
    assert result.output.topic == "箱根交通"
    assert observed["function_tools"] == {
        "search_web",
        "web_fetch",
        "search_poi",
        "get_poi_detail",
        "search_nearby",
        "search_maps",
        "get_weather",
    }
    assert observed["native_tools"] == set()
    assert "calculate_budget" not in observed["function_tools"]
    assert "convert_currency" not in observed["function_tools"]
    assert "research_agent" not in observed["function_tools"]


async def test_research_agent_preserves_host_evidence_attestation() -> None:
    invented_url = "https://official.example/invented"

    def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        del messages
        return _structured_output(
            info,
            {
                "topic": "预约规则",
                "summary": "模型尝试引用未实际观察到的 URL。",
                "claims": [
                    {
                        "claim": "当前预约规则已经确认",
                        "status": "verified",
                        "source_urls": [invented_url],
                        "tool_evidence": [],
                    }
                ],
                "sources": [
                    {
                        "title": "Invented source",
                        "url": invented_url,
                        "source_type": "official",
                    }
                ],
                "media": [],
                "unresolved": [],
            },
        )

    agent = build_research_agent(model=FunctionModel(model))
    state = ResearchRequestState()
    with bind_research_request_state(state):
        result = await agent.run("核验当前预约规则")

    assert result.output.claims[0].status == "unresolved"
    assert result.output.claims[0].source_urls == []
    assert result.output.sources == []
    assert any("Host evidence validation failed" in item for item in result.output.unresolved)
    assert state.research_requests == result.usage.requests


def test_build_research_agent_requires_explicit_model() -> None:
    with pytest.raises(ValueError, match="research_agent requires an explicit model"):
        build_research_agent()
