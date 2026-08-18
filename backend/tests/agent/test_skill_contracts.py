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


def test_travel_skill_owns_topic_research_routing_contract() -> None:
    content = _TRAVEL_SKILL.read_text(encoding="utf-8")

    required = (
        "Candidate Plan First",
        "Reality Gap",
        "Research Topic",
        "Main 拆 Research Topic；research_agent 把 Topic 压缩成一个最小、bounded 的 evidence batch",
        "Isolated Fact → Main 自己核验",
        "一次规划允许 0..N 个 Research Topics",
        "独立 Topics 并行；有依赖 Topics 分阶段",
        "ResearchFindings",
        "verification_items",
        "verification_results",
        "动态精确事实",
        "calculate_budget",
        "references/markdown-contract.md",
    )
    for phrase in required:
        assert phrase in content

    forbidden_legacy_contracts = (
        "每次最多一次 research_agent",
        "single complex research run",
        "固定 worker 数量",
        "固定研究轴",
    )
    for phrase in forbidden_legacy_contracts:
        assert phrase not in content
