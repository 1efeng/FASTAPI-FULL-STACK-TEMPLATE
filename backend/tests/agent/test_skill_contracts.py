"""Static contracts for domain-neutral Main and Skill-owned travel planning."""

from __future__ import annotations

from pathlib import Path

from app.agent.prompts import MAIN_AGENT_INSTRUCTIONS

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_TRAVEL_SKILL = (
    _BACKEND_ROOT / "app" / "agent" / "skills" / "travel-planning" / "SKILL.md"
)


def test_main_instructions_remain_domain_neutral() -> None:
    forbidden_travel_sop = (
        "Candidate Plan",
        "Reality Gap",
        "research_agent",
        "普通三日游",
        "景点当前预约",
        "住宿区域",
        "完整旅行计划",
        "Pass",
    )

    for phrase in forbidden_travel_sop:
        assert phrase not in MAIN_AGENT_INSTRUCTIONS

    assert "Skill 提供领域 SOP" in MAIN_AGENT_INSTRUCTIONS
    assert "最终回答" in MAIN_AGENT_INSTRUCTIONS
    assert "Runtime" in MAIN_AGENT_INSTRUCTIONS


def test_travel_skill_owns_specific_bounded_research_contract() -> None:
    content = _TRAVEL_SKILL.read_text(encoding="utf-8")

    required = (
        "只搜索会改变决策的信息",
        "具体问题",
        "research_agent",
        "objective",
        "calculate_budget",
        "references/markdown-contract.md",
        "动态精确事实",
        "不得用记忆补写",
        "证据足够支撑当前决策即停止",
        "不为「资料更完整」换 query 重跑",
    )
    for phrase in required:
        assert phrase in content

    forbidden_legacy_contracts = (
        "verification_items",
        "verification_results",
        "impact",
        "Evidence Sufficiency",
        "fixed worker",
        "固定 worker 数量",
        "固定研究轴",
    )
    for phrase in forbidden_legacy_contracts:
        assert phrase not in content


def test_skill_splits_structured_main_direct_from_web_research_agent() -> None:
    content = _TRAVEL_SKILL.read_text(encoding="utf-8")

    required_routing = (
        "结构化工具",
        "不委托子 agent",
        "多个独立主题",
        "先用 A 的结果判断再派 B",
        "不验证事实、不生成行程、不决定取舍",
    )
    for phrase in required_routing:
        assert phrase in content


def test_skill_reference_search_is_bounded_to_itinerary_recommendations() -> None:
    content = _TRAVEL_SKILL.read_text(encoding="utf-8")

    required = (
        "行程/路线推荐",
        "只搜行程推荐",
        "不捎带查",
    )
    for phrase in required:
        assert phrase in content


def test_skill_avoids_fake_closed_state_machine() -> None:
    content = _TRAVEL_SKILL.read_text(encoding="utf-8")

    # Evidence sufficiency is judged per topic, not a fake CLOSED runtime state.
    assert "证据足够支撑当前决策即停止" in content
    assert "视为 CLOSED" not in content


def test_skill_keeps_product_guardrails_and_limitations() -> None:
    content = _TRAVEL_SKILL.read_text(encoding="utf-8")

    required = (
        "边界情况",
        "预算过低",
        "带老人小孩",
        "目的地不熟",
        "局限",
        "以实际为准",
    )
    for phrase in required:
        assert phrase in content
