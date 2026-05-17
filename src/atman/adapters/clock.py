"""Test-fixture clock adapter.

`FrozenClock` lives here because it is a test-only `ClockPort`
implementation — a fixture, not a real time source. The default
`SystemClock` (zero-dep stdlib wrapper) lives in
`atman.core.clock_impl` next to the port contract.
"""

from datetime import UTC, datetime


class FrozenClock:
    """Fixed instant for deterministic tests."""

    def __init__(self, frozen: datetime) -> None:
        self._frozen = frozen if frozen.tzinfo is not None else frozen.replace(tzinfo=UTC)

    def now(self) -> datetime:
        return self._frozen
