"""CI contract tests for the routing architecture eval dataset."""

from __future__ import annotations

from tests.agent.routing_eval_cases import (
    EXPECTED_ARCHITECTURES,
    ROUTING_CASES,
    validate_routing_cases,
)


def test_routing_eval_cases_cover_all_three_architectures() -> None:
    covered = {case.expected_architecture for case in ROUTING_CASES}
    assert covered == EXPECTED_ARCHITECTURES


def test_routing_eval_cases_are_well_formed() -> None:
    assert not validate_routing_cases()


def test_single_research_agent_is_bounded_not_path_dependent() -> None:
    delegated = [
        case
        for case in ROUTING_CASES
        if case.expected_architecture == "research_agent"
    ]
    assert [case.id for case in delegated] == ["case-4"]
