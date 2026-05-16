"""
Reflection overload monitor.

Detects when reflection cadence is abnormally high and emits alerts so the
operator can recalibrate thresholds. The monitor does **not** try to fix
anything itself — overload is a signal, not a fault to suppress.

Rules (from REFLECTION_FUTURE §7):

- Daily reflection ran more than once per day on each of the last 3 days
  → ``WARNING`` ("calibrate thresholds").
- Deep reflection ran more than once in the last 3 days
  → ``CRITICAL``.

Both rules require that there were events to count: an empty window is not
itself an overload.
"""

from __future__ import annotations

import contextlib
from datetime import date, datetime, timedelta

from atman.core.clock_impl import SystemClock
from atman.core.models.reflection import ReflectionEvent, ReflectionLevel
from atman.core.ports.clock import ClockPort
from atman.core.ports.reflection import ReflectionEventStore
from atman.core.ports.reflection_overload_alert import (
    ReflectionOverloadAlertSink,
    ReflectionOverloadSeverity,
)


# PLAYBOOK-START
# id: sliding-window-cadence-anomaly-detection
# category: design-patterns
# title: Sliding-Window Cadence Anomaly Detection with Failure-Suppressed Alerting
# status: draft
#
# Pattern: maintain configurable sliding-window counters over recent
# operations, compare counts to per-window thresholds, and emit alerts as
# advisory signals — not as control-flow exceptions. Alert sink failures
# are suppressed so the monitor never breaks the producer it observes.
# An empty window is explicitly excluded from "anomaly" — silence is not
# overload.
#
# Why generalizable: any system needs cheap, in-process detection of
# "this is happening too often" without standing up a full metrics
# pipeline. Suppressing sink failures keeps the monitor a pure observer;
# excluding empty windows prevents a quiet system from being mistaken
# for a stuck one.
#
# Trade-offs: thresholds are static and must be tuned per deployment;
# windows are coarse (day/hour buckets) so short bursts inside a bucket
# do not fire until the bucket fills.
# PLAYBOOK-END
class ReflectionOverloadMonitor:
    """Inspects ReflectionEventStore for excessive cadence and emits alerts."""

    def __init__(
        self,
        event_store: ReflectionEventStore,
        alert_sink: ReflectionOverloadAlertSink,
        *,
        clock: ClockPort | None = None,
        daily_window_days: int = 3,
        deep_window_days: int = 3,
        daily_per_day_threshold: int = 1,
        deep_per_window_threshold: int = 1,
        scan_event_limit: int = 500,
    ) -> None:
        self._store = event_store
        self._sink = alert_sink
        self._clock = clock or SystemClock()
        self._daily_window_days = daily_window_days
        self._deep_window_days = deep_window_days
        self._daily_per_day_threshold = daily_per_day_threshold
        self._deep_per_window_threshold = deep_per_window_threshold
        self._scan_event_limit = scan_event_limit

    def check(self) -> None:
        """Inspect recent reflection history and emit alerts if thresholds exceeded."""
        now = self._clock.now()
        events = self._store.get_recent(limit=self._scan_event_limit)

        daily_alert = self._check_daily(events, now)
        if daily_alert is not None:
            severity, message, details = daily_alert
            self._safely_record(severity, message, details)

        deep_alert = self._check_deep(events, now)
        if deep_alert is not None:
            severity, message, details = deep_alert
            self._safely_record(severity, message, details)

    # ----- daily -----

    def _check_daily(
        self, events: list[ReflectionEvent], now: datetime
    ) -> tuple[ReflectionOverloadSeverity, str, dict] | None:
        window_start = now - timedelta(days=self._daily_window_days)
        relevant = [
            e
            for e in events
            if e.reflection_level == ReflectionLevel.DAILY and e.timestamp >= window_start
        ]
        if not relevant:
            return None

        by_day: dict[date, int] = {}
        for event in relevant:
            by_day[event.timestamp.date()] = by_day.get(event.timestamp.date(), 0) + 1

        # Need to see >threshold runs on *every* day of the window.
        days_in_window = [(now - timedelta(days=i)).date() for i in range(self._daily_window_days)]
        if not all(by_day.get(d, 0) > self._daily_per_day_threshold for d in days_in_window):
            return None

        return (
            ReflectionOverloadSeverity.WARNING,
            (
                f"Daily reflection ran more than {self._daily_per_day_threshold} time(s) "
                f"on each of the last {self._daily_window_days} days. "
                "Recommend recalibrating daily reflection thresholds — do NOT respond by "
                "increasing reflection frequency."
            ),
            {
                "rule": "daily_overload",
                "window_days": self._daily_window_days,
                "per_day_threshold": self._daily_per_day_threshold,
                "counts_by_day": {d.isoformat(): by_day.get(d, 0) for d in days_in_window},
            },
        )

    # ----- deep -----

    def _check_deep(
        self, events: list[ReflectionEvent], now: datetime
    ) -> tuple[ReflectionOverloadSeverity, str, dict] | None:
        window_start = now - timedelta(days=self._deep_window_days)
        relevant = [
            e
            for e in events
            if e.reflection_level == ReflectionLevel.DEEP and e.timestamp >= window_start
        ]
        if len(relevant) <= self._deep_per_window_threshold:
            return None
        return (
            ReflectionOverloadSeverity.CRITICAL,
            (
                f"Deep reflection ran {len(relevant)} time(s) in the last "
                f"{self._deep_window_days} days, expected at most "
                f"{self._deep_per_window_threshold}. Recommend pausing deep reflection "
                "and recalibrating triggers."
            ),
            {
                "rule": "deep_overload",
                "window_days": self._deep_window_days,
                "per_window_threshold": self._deep_per_window_threshold,
                "deep_count": len(relevant),
                "deep_event_ids": [str(e.id) for e in relevant],
            },
        )

    def _safely_record(
        self, severity: ReflectionOverloadSeverity, message: str, details: dict
    ) -> None:
        # An alert sink failure is itself an observability problem, but we never
        # want it to crash the monitor and silently block other checks.
        with contextlib.suppress(Exception):
            self._sink.record_overload(severity=severity, message=message, details=details)
