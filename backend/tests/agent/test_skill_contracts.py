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


def test_skill_routing_defaults_to_main_direct_over_research_agent() -> None:
    content = _TRAVEL_SKILL.read_text(encoding="utf-8")

    required_routing = (
        "Tool 数量 ≠ Agentic Complexity",
        "能预先确定查询集合时，优先 Main 并行 Tool Calls",
        "Isolated Fact → Main 自己核验",
        "禁止为了形式上的多智能体而委托 child",
        "context isolation + compression",
        "Findings 可以高度压缩",
        "只定义“必须从外部世界证明什么”",
        "不定义“怎么查”",
    )
    for phrase in required_routing:
        assert phrase in content


def test_skill_main_owns_cross_topic_path_dependency() -> None:
    content = _TRAVEL_SKILL.read_text(encoding="utf-8")

    # Single bounded research_agent is not a free path-dependent explorer; real
    # Search->Observe->Search-again lives in Main's staged orchestration.
    assert "由 Main 生成新的 Research Topic，不是 child 自己无限 Search-again" in content
    assert "Research A → Main 判断结果 → 再决定是否产生 / 派发 Research B" in content
    assert "Main 根据它决定降级方案" in content


def test_skill_avoids_fake_closed_state_machine() -> None:
    content = _TRAVEL_SKILL.read_text(encoding="utf-8")

    # Findings answering the same scope only require Main to avoid redundant
    # re-investigation; the Skill must not pretend Runtime has a CLOSED state.
    assert "当 ResearchFindings 已充分回答同一 scope 时，Main 应避免无意义重复调查" in content
    assert "只有 conflicting / unresolved、新 evidence 或新出现的 decision-critical Reality Gap 才允许继续查" in content
    assert "视为 CLOSED" not in content
