"""Core clock utilities.

`SystemClock` is the default `ClockPort` implementation. It lives in core
because it is a zero-dependency wrapper over stdlib `datetime.now(UTC)` —
no external service, no I/O, no need to inject through an adapter. Tests
and demos that want a deterministic clock import `FrozenClock` from
`atman.adapters.clock`, which is the actual "test-fixture" adapter.

`ensure_utc` is a pure timezone-normalisation helper used throughout the
reflection / session code; it has no time-source dependency.
"""

from datetime import UTC, datetime

__all__ = ["SystemClock", "ensure_utc"]


class SystemClock:
    """Default wall-clock implementation of `ClockPort` (UTC)."""

    def now(self) -> datetime:
        return datetime.now(UTC)


def ensure_utc(dt: datetime) -> datetime:
    """
    Normalize datetimes to UTC for stable comparisons and range queries.

    Naive values are treated as **already in UTC** (wall time), not local time.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
