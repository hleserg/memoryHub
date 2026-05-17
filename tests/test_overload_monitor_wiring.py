"""Tests for HLE-30 — reflection_overload_check job dispatch + sinks."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from atman.adapters.maintenance.in_memory_queue import InMemoryMaintenanceQueue
from atman.adapters.observability.composite_overload_alert_sink import (
    CompositeOverloadAlertSink,
)
from atman.adapters.observability.in_memory_overload_alert_sink import (
    InMemoryOverloadAlertSink,
)
from atman.adapters.observability.logging_overload_alert_sink import (
    LoggingOverloadAlertSink,
)
from atman.adapters.storage.in_memory_reflection_store import (
    InMemoryReflectionEventStore,
)
from atman.core.models.maintenance import JobName, JobStatus
from atman.core.models.reflection import ReflectionEvent, ReflectionLevel
from atman.core.ports.clock import ClockPort
from atman.core.ports.reflection_overload_alert import ReflectionOverloadSeverity
from atman.core.services.maintenance_worker import MaintenanceWorker
from atman.core.services.reflection_overload_monitor import ReflectionOverloadMonitor


class _FrozenClock(ClockPort):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:  # type: ignore[override]
        return self._now


def _seed_daily_events(
    store: InMemoryReflectionEventStore, now: datetime, days: int, per_day: int
) -> None:
    """Populate the event store with enough DAILY events to trip the rule."""
    for d in range(days):
        for k in range(per_day):
            store.save(
                ReflectionEvent(
                    reflection_level=ReflectionLevel.DAILY,
                    timestamp=now - timedelta(days=d, hours=k),
                )
            )


def test_worker_runs_overload_check_via_monitor() -> None:
    """Enqueue reflection_overload_check → worker claims it → monitor.check()
    fires → wired sink captures the WARNING alert. End-to-end vertical slice."""
    now = datetime(2026, 5, 17, 12, 0, tzinfo=UTC)
    store = InMemoryReflectionEventStore()
    # Daily ran twice per day on each of the last 3 days → WARNING.
    _seed_daily_events(store, now, days=3, per_day=2)

    sink = InMemoryOverloadAlertSink()
    monitor = ReflectionOverloadMonitor(
        event_store=store,
        alert_sink=sink,
        clock=_FrozenClock(now),
    )

    queue = InMemoryMaintenanceQueue()
    worker = MaintenanceWorker(queue=queue, reflection_overload_monitor=monitor)
    queue.enqueue(JobName.reflection_overload_check, run_key="overload:2026-05-17")

    processed = worker.run_once()
    assert processed == 1
    assert any(a.severity is ReflectionOverloadSeverity.WARNING for a in sink.alerts)

    done = queue.list_jobs(status=JobStatus.succeeded)
    assert any(j.job_name == JobName.reflection_overload_check for j in done)


def test_worker_skips_overload_check_when_monitor_not_configured() -> None:
    queue = InMemoryMaintenanceQueue()
    worker = MaintenanceWorker(queue=queue)
    queue.enqueue(JobName.reflection_overload_check, run_key="overload:noop")

    worker.run_once()

    skipped = queue.list_jobs(status=JobStatus.skipped)
    assert len(skipped) == 1
    assert skipped[0].job_name == JobName.reflection_overload_check


def test_factory_exposes_overload_inspect_sink_for_admin_access(tmp_path) -> None:
    """build_deps should expose the in-memory tap as deps.overload_alert_inspect
    so admin UIs / integration tests can read captured alerts without reaching
    into the monitor's private _sink._sinks chain (Devin Review ANALYSIS, #596)."""
    from uuid import uuid4

    from atman.adapters.agent.factory import build_deps
    from atman.adapters.observability.in_memory_overload_alert_sink import (
        InMemoryOverloadAlertSink,
    )

    deps, _sm, _store = build_deps(tmp_path, uuid4())
    assert deps.reflection_overload_monitor is not None
    assert isinstance(deps.overload_alert_inspect, InMemoryOverloadAlertSink)
    # The tap is the same instance that the composite fans into — anything the
    # monitor emits lands here without further wiring.
    deps.reflection_overload_monitor._sink.record_overload(  # type: ignore[attr-defined]
        severity=ReflectionOverloadSeverity.WARNING, message="t", details={}
    )
    assert len(deps.overload_alert_inspect.alerts) == 1


def test_composite_sink_fans_out_to_all_children() -> None:
    a = InMemoryOverloadAlertSink()
    b = InMemoryOverloadAlertSink()
    composite = CompositeOverloadAlertSink([a, b])

    composite.record_overload(
        severity=ReflectionOverloadSeverity.WARNING,
        message="msg",
        details={"k": 1},
    )

    assert len(a.alerts) == 1 and len(b.alerts) == 1
    assert a.alerts[0].message == "msg"
    assert a.alerts[0].details == {"k": 1}


def test_composite_sink_swallows_individual_sink_failures() -> None:
    class _Boom:
        def record_overload(self, *_a, **_kw):  # type: ignore[no-untyped-def]
            raise RuntimeError("nope")

    captured = InMemoryOverloadAlertSink()
    composite = CompositeOverloadAlertSink([_Boom(), captured])  # type: ignore[list-item]

    composite.record_overload(
        severity=ReflectionOverloadSeverity.CRITICAL,
        message="still delivered",
        details={},
    )
    # The healthy sink must still receive the alert.
    assert len(captured.alerts) == 1


def test_logging_sink_maps_severity_to_log_level() -> None:
    """LoggingOverloadAlertSink: CRITICAL severity → logging.CRITICAL,
    WARNING severity → logging.WARNING. Drive the standard library logger
    directly via a captured handler — no pytest caplog fixture so the
    test runs identically inside and outside pytest."""
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:  # type: ignore[override]
            records.append(record)

    cap = _Capture(level=logging.DEBUG)
    log = logging.getLogger("atman.reflection.overload")
    log.addHandler(cap)
    log.setLevel(logging.DEBUG)
    sink = LoggingOverloadAlertSink()
    try:
        sink.record_overload(
            severity=ReflectionOverloadSeverity.CRITICAL,
            message="too deep",
            details={"deep_count": 5},
        )
        sink.record_overload(
            severity=ReflectionOverloadSeverity.WARNING,
            message="too daily",
            details={"per_day": 2},
        )
    finally:
        log.removeHandler(cap)

    levels = [r.levelno for r in records]
    assert logging.CRITICAL in levels
    assert logging.WARNING in levels
