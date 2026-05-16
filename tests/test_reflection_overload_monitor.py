"""
Tests for :class:`ReflectionOverloadMonitor`.

The monitor reads ReflectionEventStore and emits alerts to an
ReflectionOverloadAlertSink. We never try to "fix" overload — only signal it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from atman.adapters.observability.in_memory_overload_alert_sink import (
    InMemoryOverloadAlertSink,
)
from atman.adapters.storage.in_memory_reflection_store import InMemoryReflectionEventStore
from atman.core.models.reflection import ReflectionEvent, ReflectionLevel
from atman.core.ports.reflection_overload_alert import ReflectionOverloadSeverity
from atman.core.services.reflection_overload_monitor import ReflectionOverloadMonitor


class _FixedClock:
    def __init__(self, when: datetime) -> None:
        self._when = when

    def now(self) -> datetime:
        return self._when


def _event(*, level: ReflectionLevel, when: datetime) -> ReflectionEvent:
    return ReflectionEvent(
        id=uuid4(),
        timestamp=when,
        reflection_level=level,
        identity_snapshot_id=uuid4(),
    )


def _store_with(events: list[ReflectionEvent]) -> InMemoryReflectionEventStore:
    store = InMemoryReflectionEventStore()
    for e in events:
        store.save(e)
    return store


# ---------------------------------------------------------------------------
# Daily overload
# ---------------------------------------------------------------------------


def test_no_alert_when_history_empty():
    sink = InMemoryOverloadAlertSink()
    monitor = ReflectionOverloadMonitor(
        InMemoryReflectionEventStore(),
        sink,
        clock=_FixedClock(datetime(2026, 5, 16, 18, tzinfo=UTC)),
    )
    monitor.check()
    assert sink.alerts == []


def test_daily_overload_triggers_warning_when_every_day_exceeds_threshold():
    now = datetime(2026, 5, 16, 23, tzinfo=UTC)
    # Two daily runs on each of the last 3 days (today + 2 prior)
    events: list[ReflectionEvent] = []
    for offset in range(3):
        day = now - timedelta(days=offset)
        events.append(_event(level=ReflectionLevel.DAILY, when=day.replace(hour=8)))
        events.append(_event(level=ReflectionLevel.DAILY, when=day.replace(hour=21)))

    sink = InMemoryOverloadAlertSink()
    monitor = ReflectionOverloadMonitor(_store_with(events), sink, clock=_FixedClock(now))
    monitor.check()

    daily_alerts = [a for a in sink.alerts if a.details.get("rule") == "daily_overload"]
    assert len(daily_alerts) == 1
    assert daily_alerts[0].severity == ReflectionOverloadSeverity.WARNING
    counts = daily_alerts[0].details["counts_by_day"]
    assert all(v >= 2 for v in counts.values())


def test_daily_not_triggered_if_one_day_below_threshold():
    now = datetime(2026, 5, 16, 23, tzinfo=UTC)
    events: list[ReflectionEvent] = []
    # day 0: 2 runs, day 1: 1 run, day 2: 2 runs — middle day below threshold
    events.append(_event(level=ReflectionLevel.DAILY, when=now.replace(hour=8)))
    events.append(_event(level=ReflectionLevel.DAILY, when=now.replace(hour=21)))
    events.append(
        _event(level=ReflectionLevel.DAILY, when=(now - timedelta(days=1)).replace(hour=12))
    )
    events.append(
        _event(level=ReflectionLevel.DAILY, when=(now - timedelta(days=2)).replace(hour=8))
    )
    events.append(
        _event(level=ReflectionLevel.DAILY, when=(now - timedelta(days=2)).replace(hour=20))
    )

    sink = InMemoryOverloadAlertSink()
    monitor = ReflectionOverloadMonitor(_store_with(events), sink, clock=_FixedClock(now))
    monitor.check()
    assert not any(a.details.get("rule") == "daily_overload" for a in sink.alerts)


def test_daily_alert_ignores_events_outside_window():
    now = datetime(2026, 5, 16, 23, tzinfo=UTC)
    events: list[ReflectionEvent] = []
    # Many runs 10 days ago — should not matter
    for _ in range(5):
        events.append(_event(level=ReflectionLevel.DAILY, when=now - timedelta(days=10)))
    # Only one run today, none yesterday/day before
    events.append(_event(level=ReflectionLevel.DAILY, when=now.replace(hour=12)))

    sink = InMemoryOverloadAlertSink()
    monitor = ReflectionOverloadMonitor(_store_with(events), sink, clock=_FixedClock(now))
    monitor.check()
    assert sink.alerts == []


# ---------------------------------------------------------------------------
# Deep overload
# ---------------------------------------------------------------------------


def test_deep_overload_triggers_critical_when_more_than_one_in_window():
    now = datetime(2026, 5, 16, 23, tzinfo=UTC)
    events = [
        _event(level=ReflectionLevel.DEEP, when=now - timedelta(days=1)),
        _event(level=ReflectionLevel.DEEP, when=now - timedelta(hours=3)),
    ]
    sink = InMemoryOverloadAlertSink()
    monitor = ReflectionOverloadMonitor(_store_with(events), sink, clock=_FixedClock(now))
    monitor.check()

    deep_alerts = [a for a in sink.alerts if a.details.get("rule") == "deep_overload"]
    assert len(deep_alerts) == 1
    assert deep_alerts[0].severity == ReflectionOverloadSeverity.CRITICAL
    assert deep_alerts[0].details["deep_count"] == 2


def test_deep_alert_not_triggered_at_threshold():
    now = datetime(2026, 5, 16, 23, tzinfo=UTC)
    events = [_event(level=ReflectionLevel.DEEP, when=now - timedelta(days=1))]
    sink = InMemoryOverloadAlertSink()
    monitor = ReflectionOverloadMonitor(_store_with(events), sink, clock=_FixedClock(now))
    monitor.check()
    assert sink.alerts == []


def test_deep_alert_window_excludes_old_events():
    now = datetime(2026, 5, 16, 23, tzinfo=UTC)
    events = [
        _event(level=ReflectionLevel.DEEP, when=now - timedelta(days=10)),
        _event(level=ReflectionLevel.DEEP, when=now - timedelta(days=5)),
    ]
    sink = InMemoryOverloadAlertSink()
    monitor = ReflectionOverloadMonitor(_store_with(events), sink, clock=_FixedClock(now))
    monitor.check()
    assert sink.alerts == []


def test_micro_events_are_ignored_for_both_rules():
    now = datetime(2026, 5, 16, 23, tzinfo=UTC)
    events = [_event(level=ReflectionLevel.MICRO, when=now - timedelta(hours=h)) for h in range(50)]
    sink = InMemoryOverloadAlertSink()
    monitor = ReflectionOverloadMonitor(_store_with(events), sink, clock=_FixedClock(now))
    monitor.check()
    assert sink.alerts == []


def test_monitor_swallows_sink_exceptions():
    class _BrokenSink:
        def record_overload(self, **_kwargs) -> None:
            raise RuntimeError("sink down")

    now = datetime(2026, 5, 16, 23, tzinfo=UTC)
    events = [
        _event(level=ReflectionLevel.DEEP, when=now - timedelta(hours=1)),
        _event(level=ReflectionLevel.DEEP, when=now - timedelta(hours=2)),
    ]
    monitor = ReflectionOverloadMonitor(
        _store_with(events),
        _BrokenSink(),  # type: ignore[arg-type]
        clock=_FixedClock(now),
    )
    # Should not raise
    monitor.check()


def test_thresholds_are_configurable():
    now = datetime(2026, 5, 16, 23, tzinfo=UTC)
    # 1 deep event in 3 days
    events = [_event(level=ReflectionLevel.DEEP, when=now - timedelta(hours=1))]
    sink = InMemoryOverloadAlertSink()
    monitor = ReflectionOverloadMonitor(
        _store_with(events),
        sink,
        clock=_FixedClock(now),
        deep_per_window_threshold=0,  # any event triggers
    )
    monitor.check()
    deep_alerts = [a for a in sink.alerts if a.details.get("rule") == "deep_overload"]
    assert len(deep_alerts) == 1
