"""Routing eval dataset: Main Direct vs research_agent architecture cases.

This is an architecture eval dataset only. It records the expected routing
architecture for representative Reality Gap shapes without running a real model,
so it never blocks CI on model behavior. The same five canonical cases are what a
future offline routing eval should use to score real Main routing.

Expected values:
- ``main_direct``: predetermined / lightweight fact work stays on Main parallel tools.
- ``research_agent``: one bounded, evidence-heavy research topic delegated once.
- ``main_orchestrated_research``: Research A -> Main -> Research B path dependence.

Single research_agent is never a free Search->Observe->Search-again explorer;
that dynamic path belongs to Main orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoutingCase:
    id: str
    scenario: str
    expected_architecture: str


EXPECTED_ARCHITECTURES = frozenset(
    {"main_direct", "research_agent", "main_orchestrated_research"}
)

ROUTING_CASES: tuple[RoutingCase, ...] = (
    RoutingCase(
        id="case-1",
        scenario="single current fact (八达岭 8 月 28 日是否开放)",
        expected_architecture="main_direct",
    ),
    RoutingCase(
        id="case-2",
        scenario="several predetermined independent facts (故宫开放、天坛票价、颐和园预约)",
        expected_architecture="main_direct",
    ),
    RoutingCase(
        id="case-3",
        scenario="deterministic route feasibility (开放、铁路、路线、时间余量可在开始前明确规划)",
        expected_architecture="main_direct",
    ),
    RoutingCase(
        id="case-4",
        scenario=(
            "bounded evidence-heavy Pass comparison "
            "(全国 JR Pass、区域 Pass 与单买组合的价格/覆盖/关键组合)"
        ),
        expected_architecture="research_agent",
    ),
    RoutingCase(
        id="case-5",
        scenario="Research A 结果产生新 Reality Gap（关西段覆盖不理想）→ Research B",
        expected_architecture="main_orchestrated_research",
    ),
)


def validate_routing_cases() -> list[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()
    for case in ROUTING_CASES:
        if not case.id:
            errors.append("case id must not be empty")
        if case.id in seen_ids:
            errors.append(f"duplicate case id: {case.id}")
        seen_ids.add(case.id)
        if not case.scenario:
            errors.append(f"{case.id}: scenario must not be empty")
        if case.expected_architecture not in EXPECTED_ARCHITECTURES:
            errors.append(
                f"{case.id}: unknown expected_architecture "
                f"{case.expected_architecture!r}"
            )
    return errors
