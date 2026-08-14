from datetime import UTC, datetime, timedelta

import pytest

from app.agent.context.deadline import remaining_deadline_seconds


def test_remaining_deadline_seconds_deducts_elapsed_time() -> None:
    now = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)

    assert remaining_deadline_seconds(
        now + timedelta(seconds=7.5),
        now=now,
    ) == 7.5


def test_remaining_deadline_seconds_clamps_expired_deadline() -> None:
    now = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)

    assert remaining_deadline_seconds(
        now - timedelta(seconds=1),
        now=now,
    ) == 0.0


def test_remaining_deadline_seconds_rejects_naive_values() -> None:
    aware = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)
    naive = datetime(2026, 8, 13, 12, 0)

    with pytest.raises(ValueError, match="deadline_at"):
        remaining_deadline_seconds(naive, now=aware)
    with pytest.raises(ValueError, match="now"):
        remaining_deadline_seconds(aware, now=naive)

