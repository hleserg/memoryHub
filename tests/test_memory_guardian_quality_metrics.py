"""Tests for HLE-31 — Level-C psychological quality-metric scans."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from atman.adapters.maintenance.in_memory_queue import InMemoryMaintenanceQueue
from atman.adapters.memory.in_memory_divergence_events import (
    InMemoryDivergenceEventStore,
)
from atman.adapters.memory.in_memory_entity_stance import InMemoryEntityStanceStore
from atman.adapters.memory.in_memory_memory_guardian import InMemoryMemoryGuardian
from atman.adapters.storage.in_memory_state_store import InMemoryStateStore
from atman.core.models.entity import EntityStance
from atman.core.models.experience import EmotionalDepth, FeltSense, KeyMoment
from atman.core.models.maintenance import JobName, JobStatus
from atman.core.models.validation import (
    DivergenceEvent,
    DivergenceSeverity,
    DivergenceType,
    FindingType,
)
from atman.core.services.maintenance_worker import MaintenanceWorker


def _moment(
    *,
    incomplete: bool = False,
    when: datetime | None = None,
) -> KeyMoment:
    return KeyMoment(
        what_happened="event",
        when=when or datetime.now(UTC),
        how_i_felt=FeltSense(
            emotional_valence=0.1, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
        ),
        why_it_matters="why",
        incomplete_coloring=incomplete,
    )


# ---- affect_detector_silent ----------------------------------------------


def test_quality_metrics_finds_affect_detector_silent() -> None:
    """5 incomplete-coloring moments out of 10 (>30%) → finding."""
    agent = uuid4()
    store = InMemoryStateStore()
    now = datetime.now(UTC)
    sid = uuid4()
    moments = [_moment(incomplete=i < 5, when=now - timedelta(hours=i)) for i in range(10)]
    store.store_key_moments(sid, moments)

    guardian = InMemoryMemoryGuardian(state_store=store)
    findings = guardian.scan_quality_metrics(agent)

    silent = [f for f in findings if f.finding_type == FindingType.affect_detector_silent]
    assert len(silent) == 1
    assert silent[0].details["incomplete"] == 5
    assert silent[0].details["total"] == 10


def test_quality_metrics_silent_check_below_threshold_is_silent() -> None:
    agent = uuid4()
    store = InMemoryStateStore()
    now = datetime.now(UTC)
    moments = [_moment(incomplete=False, when=now - timedelta(hours=i)) for i in range(10)]
    store.store_key_moments(uuid4(), moments)

    guardian = InMemoryMemoryGuardian(state_store=store)
    findings = guardian.scan_quality_metrics(agent)
    assert not any(f.finding_type == FindingType.affect_detector_silent for f in findings)


# ---- divergence_pattern --------------------------------------------------


def test_quality_metrics_finds_divergence_pattern() -> None:
    """5 events of the same type in the window → one finding for that type."""
    agent = uuid4()
    store = InMemoryDivergenceEventStore()
    for _ in range(5):
        store.write_event(
            DivergenceEvent(
                agent_id=agent,
                divergence_type=DivergenceType.thinking_suppression,
                severity=DivergenceSeverity.notable,
            )
        )
    # Different type — under threshold.
    store.write_event(
        DivergenceEvent(
            agent_id=agent,
            divergence_type=DivergenceType.message_entity_gap,
            severity=DivergenceSeverity.trace,
        )
    )

    guardian = InMemoryMemoryGuardian(divergence_event_store=store)
    findings = guardian.scan_quality_metrics(agent)

    patterns = [f for f in findings if f.finding_type == FindingType.divergence_pattern]
    assert len(patterns) == 1
    assert patterns[0].details["divergence_type"] == "thinking_suppression"
    assert patterns[0].details["count"] == 5


# ---- stance_formation_too_fast -------------------------------------------


def test_quality_metrics_finds_stance_formation_too_fast() -> None:
    """3 stances formed <24h after their backing moments → finding."""
    agent = uuid4()
    state_store = InMemoryStateStore()
    stance_store = InMemoryEntityStanceStore()

    now = datetime.now(UTC)
    moment_ids = []
    for _ in range(3):
        m = _moment(when=now - timedelta(hours=2))
        state_store.store_key_moments(uuid4(), [m])
        moment_ids.append(m.id)

    # Bypass write_stance() so we can pin formed_at — it auto-sets to NOW(),
    # which would still be within the 24h window for our 2h-old moments,
    # but pinning makes the test intent explicit.
    for mid in moment_ids:
        s = EntityStance(
            agent_id=agent,
            entity_id=uuid4(),
            stance_text="t",
            based_on_moment_ids=[mid],
            formed_at=now,
        )
        stance_store._stances[s.id] = s  # type: ignore[attr-defined]

    guardian = InMemoryMemoryGuardian(state_store=state_store, entity_stance_store=stance_store)
    findings = guardian.scan_quality_metrics(agent)

    too_fast = [f for f in findings if f.finding_type == FindingType.stance_formation_too_fast]
    assert len(too_fast) == 1
    assert too_fast[0].details["fast_stance_count"] >= 3


# ---- worker wiring -------------------------------------------------------


def test_maintenance_worker_includes_quality_metrics_in_guardian_scan() -> None:
    """MaintenanceWorker._run_guardian must now call scan_quality_metrics too."""
    agent = uuid4()
    state_store = InMemoryStateStore()
    now = datetime.now(UTC)
    state_store.store_key_moments(
        uuid4(),
        [_moment(incomplete=i < 4, when=now - timedelta(hours=i)) for i in range(5)],
    )

    guardian = InMemoryMemoryGuardian(state_store=state_store)
    queue = InMemoryMaintenanceQueue()
    worker = MaintenanceWorker(queue=queue, memory_guardian=guardian)
    queue.enqueue(JobName.memory_guardian_scan, agent_id=agent, run_key="guardian:1")

    worker.run_once()

    findings = guardian.get_unresolved(agent)
    assert any(f.finding_type == FindingType.affect_detector_silent for f in findings)
    done = queue.list_jobs(status=JobStatus.succeeded)
    assert any(j.job_name == JobName.memory_guardian_scan for j in done)
