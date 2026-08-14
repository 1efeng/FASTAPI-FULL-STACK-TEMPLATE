"""Framework-neutral absolute deadline helpers."""

from datetime import UTC, datetime


def remaining_deadline_seconds(
    deadline_at: datetime,
    *,
    now: datetime | None = None,
) -> float:
    """Return the non-negative budget remaining before an absolute deadline."""
    if deadline_at.tzinfo is None:
        raise ValueError("deadline_at must be timezone-aware")

    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return max(0.0, (deadline_at - current).total_seconds())

