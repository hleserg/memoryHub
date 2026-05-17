"""Composite sink — fan out reflection overload alerts to multiple sinks.

When a deployment wants alerts both in-memory (for tests/admin UI) and in
the log stream (for ops), wrap the individual sinks in this composite.
The composite catches per-sink failures so a misconfigured sink can't
block delivery to the rest.
"""

from __future__ import annotations

import contextlib
from collections.abc import Sequence

from atman.core.ports.reflection_overload_alert import (
    ReflectionOverloadAlertSink,
    ReflectionOverloadSeverity,
)


class CompositeOverloadAlertSink(ReflectionOverloadAlertSink):
    """Fan-out wrapper over an ordered collection of sinks.

    Each downstream ``record_overload`` call is wrapped in a
    ``contextlib.suppress(Exception)`` block so a flaky sink can never
    short-circuit delivery to the remaining sinks. Per the port contract,
    sinks themselves are expected to not raise — but we belt-and-brace
    here because the monitor's own ``_safely_record`` also suppresses, and
    we don't want the composite to be the leak point.
    """

    def __init__(self, sinks: Sequence[ReflectionOverloadAlertSink]) -> None:
        self._sinks = list(sinks)

    def record_overload(
        self,
        *,
        severity: ReflectionOverloadSeverity,
        message: str,
        details: dict,
    ) -> None:
        for sink in self._sinks:
            with contextlib.suppress(Exception):
                sink.record_overload(severity=severity, message=message, details=details)
