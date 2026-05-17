"""Tests for HLE-31 — Level-C psychological quality-metric scans."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

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
from atman.core.models.session import Session
from atman.core.models.validation import (
    DivergenceEvent,
    DivergenceSeverity,
    DivergenceType,
    FindingType,
)
from atman.core.services.maintenance_worker import MaintenanceWorker


def _session(agent_id: UUID) -> Session:
    return Session(agent_id=agent_id)


def _moment(
    *,
    session_id: UUID,
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
        session_id=session_id,
        incomplete_coloring=incomplete,
    )


# ---- affect_detector_silent ----------------------------------------------


def test_quality_metrics_finds_affect_detector_silent() -> None:
    """5 incomplete-coloring moments out of 10 (>30%) → finding."""
    agent = uuid4()
    store = InMemoryStateStore()
    session = _session(agent)
    store.create_session(session)
    now = datetime.now(UTC)
    moments = [
        _moment(session_id=session.id, incomplete=i < 5, when=now - timedelta(hours=i))
        for i in range(10)
    ]
    store.store_key_moments(session.id, moments)

    guardian = InMemoryMemoryGuardian(state_store=store)
    findings = guardian.scan_quality_metrics(agent)

    silent = [f for f in findings if f.finding_type == FindingType.affect_detector_silent]
    assert len(silent) == 1
    assert silent[0].details["incomplete"] == 5
    assert silent[0].details["total"] == 10


def test_quality_metrics_silent_check_below_threshold_is_silent() -> None:
    agent = uuid4()
    store = InMemoryStateStore()
    session = _session(agent)
    store.create_session(session)
    now = datetime.now(UTC)
    moments = [
        _moment(session_id=session.id, incomplete=False, when=now - timedelta(hours=i))
        for i in range(10)
    ]
    store.store_key_moments(session.id, moments)

    guardian = InMemoryMemoryGuardian(state_store=store)
    findings = guardian.scan_quality_metrics(agent)
    assert not any(f.finding_type == FindingType.affect_detector_silent for f in findings)


def test_quality_metrics_silent_is_scoped_per_agent() -> None:
    """Multi-agent store: high incomplete-coloring on agent A must not
    fire the affect_detector_silent finding for agent B (Devin Review
    ANALYSIS, #598)."""
    agent_a = uuid4()
    agent_b = uuid4()
    store = InMemoryStateStore()
    session_a = _session(agent_a)
    session_b = _session(agent_b)
    store.create_session(session_a)
    store.create_session(session_b)
    now = datetime.now(UTC)
    # Agent A: 80% incomplete — would trip on its own.
    store.store_key_moments(
        session_a.id,
        [
            _moment(session_id=session_a.id, incomplete=i < 8, when=now - timedelta(hours=i))
            for i in range(10)
        ],
    )
    # Agent B: 0% incomplete — should be silent.
    store.store_key_moments(
        session_b.id,
        [
            _moment(session_id=session_b.id, incomplete=False, when=now - timedelta(hours=i))
            for i in range(10)
        ],
    )

    guardian = InMemoryMemoryGuardian(state_store=store)
    a_findings = guardian.scan_quality_metrics(agent_a)
    b_findings = guardian.scan_quality_metrics(agent_b)
    assert any(f.finding_type == FindingType.affect_detector_silent for f in a_findings), (
        "agent A should trip the threshold"
    )
    assert not any(f.finding_type == FindingType.affect_detector_silent for f in b_findings), (
        "agent B should not be affected by agent A's moments"
    )


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
    session = _session(agent)
    state_store.create_session(session)

    now = datetime.now(UTC)
    moment_ids: list[UUID] = []
    for _ in range(3):
        m = _moment(session_id=session.id, when=now - timedelta(hours=2))
        state_store.store_key_moments(session.id, [m])
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
    session = _session(agent)
    state_store.create_session(session)
    now = datetime.now(UTC)
    state_store.store_key_moments(
        session.id,
        [
            _moment(session_id=session.id, incomplete=i < 4, when=now - timedelta(hours=i))
            for i in range(5)
        ],
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
