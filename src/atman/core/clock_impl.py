"""Default and test clock implementations."""

from datetime import UTC, datetime


class SystemClock:
    """Wall-clock implementation (UTC)."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FrozenClock:
    """Fixed instant for deterministic tests."""

    def __init__(self, frozen: datetime) -> None:
        self._frozen = frozen if frozen.tzinfo is not None else frozen.replace(tzinfo=UTC)

    def now(self) -> datetime:
        return self._frozen


def ensure_utc(dt: datetime) -> datetime:
    """
    Normalize datetimes to UTC for stable comparisons and range queries.

    Naive values are treated as **already in UTC** (wall time), not local time.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
