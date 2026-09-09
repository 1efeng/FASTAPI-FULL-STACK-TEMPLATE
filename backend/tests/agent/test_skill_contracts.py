"""Static contracts for the L3-enabled travel planning Skill."""

from pathlib import Path

from pydantic_ai_harness.skills import Skills

from app.agent.prompts import MAIN_AGENT_INSTRUCTIONS

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_SKILL_ROOT = _BACKEND_ROOT / "app" / "agent" / "skills" / "travel-plan-skill"
_TRAVEL_SKILL = _SKILL_ROOT / "SKILL.md"


def test_main_instructions_remain_domain_neutral() -> None:
    for phrase in (
        "web_search",
        "web_fetch",
        "tavily_search",
        "deep_research",
        "research_agent",
        "完整旅行计划",
    ):
        assert phrase not in MAIN_AGENT_INSTRUCTIONS

    assert "Skill 提供领域 SOP" in MAIN_AGENT_INSTRUCTIONS
    assert "最终回答" in MAIN_AGENT_INSTRUCTIONS


def test_skill_exposes_standard_name_and_discriminating_description() -> None:
    skills = Skills[object](_SKILL_ROOT.parent, include={"travel-plan-skill"})
    leaves = []
    skills.apply(leaves.append)

    assert len(leaves) == 1
    skill = leaves[0]
    assert skill.id == "travel-plan-skill"
    assert skill.description is not None
    assert "多日路线" in skill.description
    assert "单项天气" in skill.description


def test_skill_defines_planning_scope_and_safety() -> None:
    content = _TRAVEL_SKILL.read_text(encoding="utf-8")

    for phrase in (
        "你的目标不是罗列景点",
        "时间合理性",
        "路线合理性",
        "预算合理性",
        "编造票价",
        "本 Skill 不负责",
        "实际购买",
        "预订操作",
        "不要只写“上午 / 中午 / 下午 / 晚上”",
        "时间待确认",
        "雨天 / 延误备选",
        "出发前确认",
        "注意事项与风险",
        "住宿策略",
        "住宿：区域 / 城市",
        "纵向时间线",
        "不使用宽表格",
        "表格仅用于预算、简短对比",
    ):
        assert phrase in content

    assert len(content.splitlines()) < 500


def test_skill_routes_standard_level_three_resources() -> None:
    assert {
        path.relative_to(_SKILL_ROOT).as_posix()
        for path in (_SKILL_ROOT / "references").rglob("*")
        if path.is_file()
    } == {
        "references/examples/家庭旅行案例.md",
        "references/examples/情侣旅行案例.md",
        "references/schemas/travel_plan.yaml",
    }

    content = _TRAVEL_SKILL.read_text(encoding="utf-8")
    assert "name: travel-plan-skill" in content
    assert "description:" in content
    assert "read_skill_resource" in content
    assert "references/examples/情侣旅行案例.md" in content
    assert "references/schemas/travel_plan.yaml" in content
