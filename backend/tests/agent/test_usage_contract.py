from typing import Any

import pytest

from app.agent.usage import AgentModelCallUsage, AgentTokenUsage, AgentUsage


def _call(
    *,
    call_index: int = 0,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    available: bool = True,
) -> AgentModelCallUsage:
    return AgentModelCallUsage(
        call_index=call_index,
        logical_model="travel-agent-llm",
        token_usage=(
            AgentTokenUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens,
            )
            if available
            else None
        ),
    )


def test_usage_aggregates_multiple_model_calls_without_double_counting_cache() -> None:
    usage = AgentUsage(
        model_calls=(
            _call(input_tokens=100, output_tokens=20, cache_read_tokens=40),
            _call(
                call_index=1,
                input_tokens=50,
                output_tokens=10,
                cache_read_tokens=25,
            ),
        ),
        tool_calls=1,
    )

    assert usage.model_requests == 2
    assert usage.per_call_usage_complete is True
    assert usage.tool_calls == 1
    assert usage.input_tokens == 150
    assert usage.output_tokens == 30
    assert usage.total_tokens == 180
    assert usage.cache_read_tokens == 65
    assert usage.token_usage_available is True


def test_usage_tokens_are_unknown_when_any_model_call_has_no_usage() -> None:
    usage = AgentUsage(
        model_calls=(
            _call(input_tokens=10, output_tokens=2),
            _call(call_index=1, input_tokens=0, output_tokens=0, available=False),
        )
    )

    assert usage.token_usage_available is False
    assert usage.input_tokens is None
    assert usage.output_tokens is None
    assert usage.total_tokens is None


def test_usage_exposes_model_requests_without_per_call_evidence() -> None:
    usage = AgentUsage(unattributed_model_requests=2)

    assert usage.model_requests == 2
    assert usage.model_calls == ()
    assert usage.per_call_usage_complete is False
    assert usage.token_usage_available is False
    assert usage.total_tokens is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"logical_model": ""},
        {"call_index": -1},
    ],
)
def test_model_call_usage_rejects_invalid_business_values(
    kwargs: dict[str, Any],
) -> None:
    values: dict[str, Any] = {
        "call_index": 0,
        "logical_model": "travel-agent-llm",
        "token_usage": AgentTokenUsage(input_tokens=1, output_tokens=1),
    }
    values.update(kwargs)

    with pytest.raises(ValueError):
        AgentModelCallUsage(**values)


@pytest.mark.parametrize("value", [-1])
def test_token_usage_rejects_negative_counters(value: int) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        AgentTokenUsage(input_tokens=value, output_tokens=0)
