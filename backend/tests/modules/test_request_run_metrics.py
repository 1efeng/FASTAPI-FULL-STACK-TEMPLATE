"""Mapping tests for RequestRun runtime metric persistence."""

from __future__ import annotations

from app.agent.usage import AgentModelCallUsage, AgentTokenUsage, AgentUsage
from app.modules.chat.service import _request_run_metrics


def _usage_with_tokens() -> AgentUsage:
    call = AgentModelCallUsage(
        call_index=0,
        logical_model="travel-agent-llm",
        token_usage=AgentTokenUsage(
            input_tokens=150,
            output_tokens=30,
            cache_read_tokens=65,
            cache_write_tokens=10,
        ),
    )
    return AgentUsage(model_calls=(call,), tool_calls=3, research_runs=1)


def test_request_run_metrics_maps_full_usage() -> None:
    metrics = _request_run_metrics(
        usage=_usage_with_tokens(),
        enable_web_search=True,
        enable_thinking=False,
    )

    assert metrics["model_requests"] == 1
    assert metrics["tool_calls"] == 3
    assert metrics["research_runs"] == 1
    assert metrics["input_tokens"] == 150
    assert metrics["output_tokens"] == 30
    assert metrics["total_tokens"] == 180
    assert metrics["cache_read_tokens"] == 65
    assert metrics["cache_write_tokens"] == 10
    assert metrics["enable_web_search"] is True
    assert metrics["enable_thinking"] is False


def test_request_run_metrics_omits_unknown_tokens() -> None:
    usage = AgentUsage(
        model_calls=(
            AgentModelCallUsage(
                call_index=0,
                logical_model="travel-agent-llm",
                token_usage=None,
            ),
        ),
        unattributed_model_requests=1,
    )
    metrics = _request_run_metrics(
        usage=usage,
        enable_web_search=None,
        enable_thinking=None,
    )

    assert metrics["model_requests"] == 2
    assert "input_tokens" not in metrics
    assert "output_tokens" not in metrics
    assert "total_tokens" not in metrics
    assert "cache_read_tokens" not in metrics
    assert "cache_write_tokens" not in metrics
    assert "enable_web_search" not in metrics
    assert "enable_thinking" not in metrics


def test_request_run_metrics_empty_when_no_usage() -> None:
    assert _request_run_metrics(
        usage=None,
        enable_web_search=None,
        enable_thinking=None,
    ) == {}