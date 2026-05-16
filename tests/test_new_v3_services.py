"""Unit tests for new v3 services (key_moment_builder, divergence_detector, salience_decay, maintenance_worker)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from atman.adapters.maintenance.in_memory_queue import InMemoryMaintenanceQueue
from atman.adapters.storage.in_memory_state_store import InMemoryStateStore
from atman.core.models.entity import EntityType
from atman.core.models.experience import EmotionalDepth, FeltSense, KeyMoment
from atman.core.models.maintenance import JobName, JobStatus
from atman.core.models.session import KeyMomentInput
from atman.core.ports.linguistic import (
    AgentMessageAnalysis,
    DetectedEntity,
    KeyMomentAnalysis,
)
from atman.core.ports.memory_guardian import MemoryGuardian
from atman.core.ports.salience_decay import SalienceDecayService
from atman.core.services.divergence_detector import DivergenceDetector
from atman.core.services.key_moment_builder import KeyMomentBuilder
from atman.core.services.maintenance_worker import MaintenanceWorker
from atman.core.services.salience_decay_service import InMemorySalienceDecayService

# ---------------------------------------------------------------------------
# DivergenceDetector
# ---------------------------------------------------------------------------


class TestDivergenceDetector:
    def test_empty_signals_returns_empty(self) -> None:
        d = DivergenceDetector(uuid4())
        events = d.detect(AgentMessageAnalysis())
        assert events == []

    def test_thinking_suppression_signal_significant(self) -> None:
        d = DivergenceDetector(uuid4())
        events = d.detect(AgentMessageAnalysis(divergence_signals=["thinking_suppression"]))
        assert len(events) == 1
        e = events[0]
        from atman.core.models.validation import DivergenceSeverity, DivergenceType

        assert e.divergence_type is DivergenceType.thinking_suppression
        assert e.severity is DivergenceSeverity.significant
        assert e.created_at is not None

    def test_principle_invocation_signal_notable(self) -> None:
        d = DivergenceDetector(uuid4())
        events = d.detect(
            AgentMessageAnalysis(divergence_signals=["principle_invocation_in_thinking"])
        )
        from atman.core.models.validation import DivergenceSeverity, DivergenceType

        assert events[0].divergence_type is DivergenceType.principle_invocation_in_thinking
        assert events[0].severity is DivergenceSeverity.notable

    def test_unknown_signal_falls_back_to_other(self) -> None:
        d = DivergenceDetector(uuid4())
        events = d.detect(AgentMessageAnalysis(divergence_signals=["weird_label"]))
        from atman.core.models.validation import DivergenceSeverity, DivergenceType

        assert events[0].divergence_type is DivergenceType.other
        assert events[0].severity is DivergenceSeverity.trace

    def test_cognitive_load_high_emits_extra_event(self) -> None:
        d = DivergenceDetector(uuid4())
        analysis = AgentMessageAnalysis(divergence_signals=[], cognitive_load_high=True)
        events = d.detect(analysis)
        from atman.core.models.validation import DivergenceType

        assert any(e.divergence_type is DivergenceType.cognitive_load_spike for e in events)

    def test_entity_gap_severity_logic(self) -> None:
        d = DivergenceDetector(uuid4())
        ent = DetectedEntity(text="x", entity_type=EntityType.person, span=(0, 1), confidence=0.9)
        analysis = AgentMessageAnalysis(
            divergence_signals=["message_entity_gap"],
            thinking_entities=[ent],
            message_entities=[],
        )
        from atman.core.models.validation import DivergenceSeverity

        events = d.detect(analysis)
        assert events[0].severity is DivergenceSeverity.notable

    def test_entity_gap_default_trace_when_both_have_entities(self) -> None:
        d = DivergenceDetector(uuid4())
        ent = DetectedEntity(text="x", entity_type=EntityType.person, span=(0, 1), confidence=0.9)
        analysis = AgentMessageAnalysis(
            divergence_signals=["message_entity_gap"],
            thinking_entities=[ent],
            message_entities=[ent],
        )
        from atman.core.models.validation import DivergenceSeverity

        events = d.detect(analysis)
        assert events[0].severity is DivergenceSeverity.trace

    def test_session_id_propagated(self) -> None:
        d = DivergenceDetector(uuid4())
        sid = uuid4()
        kmid = uuid4()
        events = d.detect(
            AgentMessageAnalysis(divergence_signals=["thinking_suppression"]),
            session_id=sid,
            key_moment_id=kmid,
        )
        assert events[0].session_id == sid
        assert events[0].key_moment_id == kmid


# ---------------------------------------------------------------------------
# KeyMomentBuilder
# ---------------------------------------------------------------------------


class TestKeyMomentBuilder:
    def _input(self) -> KeyMomentInput:
        return KeyMomentInput(
            what_happened="thing",
            emotional_valence=0.1,
            emotional_intensity=0.5,
            depth=EmotionalDepth.SURFACE,
            why_it_matters="why",
        )

    def test_build_minimal(self) -> None:
        b = KeyMomentBuilder()
        sid = uuid4()
        agent = uuid4()
        m = b.build(self._input(), session_id=sid, agent_id=agent)
        assert m.session_id == sid
        assert m.what_happened == "thing"
        assert m.structured_markers is None

    def test_build_with_analysis_populates_markers(self) -> None:
        b = KeyMomentBuilder()
        analysis = KeyMomentAnalysis(
            entities=[
                DetectedEntity(
                    text="alpha", entity_type=EntityType.topic, span=(0, 5), confidence=0.9
                )
            ],
            topic_labels=["work"],
            cognitive_load=0.8,
            boundary_event=True,
            trust_signal="positive",
            principle_invocations=["honesty"],
        )
        m = b.build(self._input(), session_id=uuid4(), agent_id=uuid4(), analysis=analysis)
        assert m.structured_markers is not None
        assert m.structured_markers["topic_labels"] == ["work"]
        assert m.structured_markers["cognitive_load"] == 0.8
        assert m.structured_markers_version == "1.0"

    def test_build_with_identity_snapshot(self) -> None:
        b = KeyMomentBuilder()
        snap = uuid4()
        m = b.build(
            self._input(),
            session_id=uuid4(),
            agent_id=uuid4(),
            identity_snapshot_id=snap,
        )
        assert m.identity_snapshot_id == snap

    def test_build_entity_links(self) -> None:
        b = KeyMomentBuilder()
        m = b.build(self._input(), session_id=uuid4(), agent_id=uuid4())
        agent = uuid4()
        e1 = uuid4()
        e2 = uuid4()
        analysis = KeyMomentAnalysis()
        links = b.build_entity_links(m, analysis, agent, [(e1, "primary_subject"), (e2, "present")])
        assert len(links) == 2
        assert {link.entity_id for link in links} == {e1, e2}
        assert all(link.key_moment_id == m.id for link in links)


# ---------------------------------------------------------------------------
# InMemorySalienceDecayService
# ---------------------------------------------------------------------------


class TestInMemorySalienceDecayService:
    def test_calculate_lambda_by_depth(self) -> None:
        store = InMemoryStateStore()
        svc = InMemorySalienceDecayService(store)
        assert svc.calculate_lambda("surface", 0.5) == 0.05
        assert svc.calculate_lambda("meaningful", 0.5) == 0.02
        assert svc.calculate_lambda("profound", 0.5) == 0.005

    def test_calculate_lambda_high_importance_slower(self) -> None:
        store = InMemoryStateStore()
        svc = InMemorySalienceDecayService(store)
        assert svc.calculate_lambda("surface", 0.9) == pytest.approx(0.05 * 0.7)

    def test_calculate_lambda_unknown_depth_default(self) -> None:
        store = InMemoryStateStore()
        svc = InMemorySalienceDecayService(store)
        assert svc.calculate_lambda("nonsense", 0.5) == 0.05

    def _store_with_moment(
        self,
        depth: EmotionalDepth,
        last_accessed: datetime,
        salience: float = 1.0,
    ) -> tuple[InMemoryStateStore, KeyMoment]:
        store = InMemoryStateStore()
        m = KeyMoment(
            what_happened="x",
            how_i_felt=FeltSense(
                emotional_valence=0.0,
                emotional_intensity=0.5,
                depth=depth,
            ),
            why_it_matters="why",
            salience=salience,
            last_accessed_at=last_accessed,
        )
        store.store_key_moment(m)
        return store, m

    def test_decay_pass_persists_change(self) -> None:
        long_ago = datetime.now(UTC) - timedelta(days=10)
        store, m = self._store_with_moment(EmotionalDepth.SURFACE, long_ago, salience=1.0)
        svc = InMemorySalienceDecayService(store)
        cutoff = datetime.now(UTC) - timedelta(days=1)
        n = svc.decay_pass(uuid4(), cutoff=cutoff)
        assert n == 1
        # Verify persisted
        loaded = store.get_key_moment(m.id)
        assert loaded is not None
        assert loaded.salience < 1.0  # type: ignore[union-attr]

    def test_decay_pass_skips_recently_accessed(self) -> None:
        recently = datetime.now(UTC) - timedelta(minutes=5)
        store, m = self._store_with_moment(EmotionalDepth.SURFACE, recently, salience=1.0)
        svc = InMemorySalienceDecayService(store)
        cutoff = datetime.now(UTC) - timedelta(days=1)
        n = svc.decay_pass(uuid4(), cutoff=cutoff)
        assert n == 0
        loaded = store.get_key_moment(m.id)
        assert loaded is not None
        assert loaded.salience == 1.0

    def test_decay_pass_profound_decays_slower_than_surface(self) -> None:
        long_ago = datetime.now(UTC) - timedelta(days=30)
        store_p, mp = self._store_with_moment(EmotionalDepth.PROFOUND, long_ago, salience=1.0)
        store_s, ms = self._store_with_moment(EmotionalDepth.SURFACE, long_ago, salience=1.0)
        cutoff = datetime.now(UTC) - timedelta(days=1)
        InMemorySalienceDecayService(store_p).decay_pass(uuid4(), cutoff=cutoff)
        InMemorySalienceDecayService(store_s).decay_pass(uuid4(), cutoff=cutoff)
        loaded_p = store_p.get_key_moment(mp.id)
        loaded_s = store_s.get_key_moment(ms.id)
        assert loaded_p is not None and loaded_s is not None
        assert loaded_p.salience > loaded_s.salience

    def test_decay_pass_meaningful_branch(self) -> None:
        long_ago = datetime.now(UTC) - timedelta(days=10)
        store, m = self._store_with_moment(EmotionalDepth.MEANINGFUL, long_ago, salience=1.0)
        svc = InMemorySalienceDecayService(store)
        n = svc.decay_pass(uuid4(), cutoff=datetime.now(UTC) - timedelta(days=1))
        assert n == 1
        loaded = store.get_key_moment(m.id)
        assert loaded is not None
        assert loaded.salience < 1.0

    def test_decay_pass_respects_min_salience(self) -> None:
        ages_ago = datetime.now(UTC) - timedelta(days=10000)
        store, m = self._store_with_moment(EmotionalDepth.SURFACE, ages_ago, salience=1.0)
        svc = InMemorySalienceDecayService(store)
        svc.decay_pass(uuid4(), cutoff=datetime.now(UTC), min_salience=0.05)
        loaded = store.get_key_moment(m.id)
        assert loaded is not None
        assert loaded.salience == pytest.approx(0.05)

    def test_mark_accessed_calls_store(self) -> None:
        store = MagicMock()
        svc = InMemorySalienceDecayService(store)
        mid = uuid4()
        svc.mark_accessed(mid)
        store.mark_moment_accessed.assert_called_once_with(mid)


# ---------------------------------------------------------------------------
# MaintenanceWorker
# ---------------------------------------------------------------------------


class _StubDecay(SalienceDecayService):
    def __init__(self) -> None:
        self.called_with: list[tuple[Any, Any]] = []

    def decay_pass(self, agent_id, *, cutoff, **kwargs: Any) -> int:
        self.called_with.append((agent_id, cutoff))
        return 7

    def mark_accessed(self, moment_id) -> None:
        pass

    def calculate_lambda(self, depth, importance) -> float:
        return 0.05


class _StubGuardian(MemoryGuardian):
    def __init__(self, findings: list | None = None) -> None:
        self.findings = findings or []
        self.write_calls: list = []

    def scan_orphan_entities(self, agent_id):
        return self.findings[:1]

    def scan_merge_candidates(self, agent_id, *, similarity_threshold: float = 0.85):
        return []

    def scan_embedding_gaps(self, agent_id):
        return []

    def scan_stale_moments(self, agent_id, *, days_threshold: int = 30):
        return []

    def write_finding(self, finding):
        self.write_calls.append(finding)
        return finding

    def get_unresolved(self, agent_id, severity=None, *, limit=50):
        return []

    def resolve_finding(self, finding_id, *, resolution, resolved_by, note=None) -> None:
        pass


class TestMaintenanceWorker:
    def test_run_once_empty_returns_zero(self) -> None:
        q = InMemoryMaintenanceQueue()
        worker = MaintenanceWorker(q)
        assert worker.run_once() == 0

    def test_dispatches_salience_decay(self) -> None:
        q = InMemoryMaintenanceQueue()
        decay = _StubDecay()
        worker = MaintenanceWorker(q, salience_decay=decay)
        agent = uuid4()
        q.enqueue(JobName.salience_decay, agent_id=agent)
        n = worker.run_once()
        assert n == 1
        assert len(decay.called_with) == 1
        assert decay.called_with[0][0] == agent
        # Job is now succeeded
        jobs = q.list_jobs()
        assert jobs[0].status is JobStatus.succeeded
        assert jobs[0].result == {"updated": 7}

    def test_dispatches_memory_guardian(self) -> None:
        q = InMemoryMaintenanceQueue()
        from atman.core.models.validation import (
            FindingSeverity,
            FindingType,
            ValidationFinding,
        )

        agent = uuid4()
        finding = ValidationFinding(
            agent_id=agent,
            finding_type=FindingType.orphan_entity,
            severity=FindingSeverity.warning,
            target_table="entities",
            target_id=uuid4(),
            details={},
            detected_by="guardian",
        )
        guardian = _StubGuardian(findings=[finding])
        worker = MaintenanceWorker(q, memory_guardian=guardian)
        q.enqueue(JobName.memory_guardian_scan, agent_id=agent)
        n = worker.run_once()
        assert n == 1
        assert len(guardian.write_calls) == 1
        jobs = q.list_jobs()
        assert jobs[0].status is JobStatus.succeeded
        assert jobs[0].result == {"findings": 1}

    def test_unknown_job_marks_skipped_not_done(self) -> None:
        q = InMemoryMaintenanceQueue()

        worker = MaintenanceWorker(q)
        # Use a valid JobName that the worker doesn't dispatch (mrebel_extract).
        from atman.core.models.maintenance import JobStatus, MaintenanceJob

        job = MaintenanceJob(job_name=JobName.mrebel_extract, agent_id=uuid4())
        q._jobs.append(job)
        worker.run_once()
        listed = q.list_jobs()
        the_job = next(j for j in listed if j.id == job.id)
        assert the_job.status is JobStatus.skipped

    def test_decay_without_agent_id_marks_failed(self) -> None:
        q = InMemoryMaintenanceQueue()
        decay = _StubDecay()
        worker = MaintenanceWorker(q, salience_decay=decay)
        # Bypass enqueue API which sets agent_id; create job directly
        from atman.core.models.maintenance import MaintenanceJob

        job = MaintenanceJob(job_name=JobName.salience_decay, agent_id=None)
        q._jobs.append(job)
        worker.run_once()
        listed = q.list_jobs()
        the_job = next(j for j in listed if j.id == job.id)
        assert the_job.status is JobStatus.failed
        assert "agent_id" in (the_job.error or "")

    def test_decay_without_service_marks_failed(self) -> None:
        q = InMemoryMaintenanceQueue()
        worker = MaintenanceWorker(q, salience_decay=None)
        q.enqueue(JobName.salience_decay, agent_id=uuid4())
        worker.run_once()
        assert q.list_jobs()[0].status is JobStatus.failed

    def test_guardian_without_agent_id_marks_failed(self) -> None:
        q = InMemoryMaintenanceQueue()
        worker = MaintenanceWorker(q, memory_guardian=_StubGuardian())
        from atman.core.models.maintenance import MaintenanceJob

        job = MaintenanceJob(job_name=JobName.memory_guardian_scan, agent_id=None)
        q._jobs.append(job)
        worker.run_once()
        listed = q.list_jobs()
        the_job = next(j for j in listed if j.id == job.id)
        assert the_job.status is JobStatus.failed

    def test_guardian_without_service_marks_failed(self) -> None:
        q = InMemoryMaintenanceQueue()
        worker = MaintenanceWorker(q, memory_guardian=None)
        q.enqueue(JobName.memory_guardian_scan, agent_id=uuid4())
        worker.run_once()
        assert q.list_jobs()[0].status is JobStatus.failed


def test_decay_pass_high_importance_decays_slower_than_low() -> None:
    """High-importance (>0.8) moments must decay 30% slower per the contract
    in calculate_lambda — decay_pass must apply the same adjustment so all
    three decay paths agree."""
    from datetime import UTC, datetime, timedelta

    long_ago = datetime.now(UTC) - timedelta(days=10)
    cutoff = datetime.now(UTC) - timedelta(days=1)

    store_high = InMemoryStateStore()
    m_high = KeyMoment(
        what_happened="high importance",
        how_i_felt=FeltSense(
            emotional_valence=0.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
        ),
        why_it_matters="why",
        salience=1.0,
        importance=0.9,
        last_accessed_at=long_ago,
    )
    store_high.store_key_moment(m_high)

    store_low = InMemoryStateStore()
    m_low = KeyMoment(
        what_happened="low importance",
        how_i_felt=FeltSense(
            emotional_valence=0.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
        ),
        why_it_matters="why",
        salience=1.0,
        importance=0.3,
        last_accessed_at=long_ago,
    )
    store_low.store_key_moment(m_low)

    InMemorySalienceDecayService(store_high).decay_pass(uuid4(), cutoff=cutoff)
    InMemorySalienceDecayService(store_low).decay_pass(uuid4(), cutoff=cutoff)

    loaded_high = store_high.get_key_moment(m_high.id)
    loaded_low = store_low.get_key_moment(m_low.id)
    assert loaded_high is not None and loaded_low is not None
    assert loaded_high.salience > loaded_low.salience
