from datetime import UTC, datetime

import pytest

from app.agents.travel.middleware import runtime_clock_context


def test_runtime_clock_uses_configured_timezone() -> None:
    context = runtime_clock_context(
        now=datetime(2026, 8, 10, 16, 5, 6, tzinfo=UTC),
        timezone_name="Asia/Shanghai",
    )

    assert "当前日期：2026-08-11" in context
    assert "当前星期：星期二" in context
    assert "当前时间：00:05:06" in context
    assert "当前时区：Asia/Shanghai" in context
    assert "当前年份：2026" in context


def test_runtime_clock_converts_to_requested_timezone() -> None:
    context = runtime_clock_context(
        now=datetime(2026, 1, 1, 1, 30, tzinfo=UTC),
        timezone_name="America/Los_Angeles",
    )

    assert "当前日期：2025-12-31" in context
    assert "当前时间：17:30:00" in context
    assert "当前时区：America/Los_Angeles" in context
    assert "当前年份：2025" in context


def test_runtime_clock_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        runtime_clock_context(now=datetime(2026, 8, 10, 12, 0))
