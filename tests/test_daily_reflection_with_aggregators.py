"""Integration test: DailyReflectionService + DivergenceAggregator + FindingsTriage."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from atman.adapters.memory.in_memory_divergence_events import InMemoryDivergenceEventStore
from atman.adapters.reflection.mock_reflection_model import MockReflectionModel
from atman.adapters.storage.in_memory_reflection_store import (
    InMemoryPatternStore,
    InMemoryReflectionEventStore,
)
from atman.core.models.experience import (
    EmotionalDepth,
    FeltSense,
    KeyMoment,
    ReframingNote,
    ReframingNoteAppendResult,
)
from atman.core.models.identity import Identity, IdentitySnapshot
from atman.core.models.session import Session
from atman.core.models.validation import (
    DivergenceEvent,
    DivergenceSeverity,
    DivergenceType,
    FindingSeverity,
    FindingType,
    ResolutionStatus,
    ValidationFinding,
)
from atman.core.ports.memory_guardian import MemoryGuardian
from atman.core.services.divergence_aggregator import DivergenceAggregator
from atman.core.services.findings_triage import FindingsTriage
from atman.core.services.reflection_service import DailyReflectionService

AGENT_ID = UUID("00000000-0000-4000-8000-0000000000aa")


class _SessionRepo:
    def __init__(self, sessions, moments):
        self._sessions = {s.id: s for s in sessions}
        self._moments = moments

    def get_session(self, session_id):  # pragma: no cover
        return self._sessions.get(session_id)

    def list_recent_sessions(self, agent_id=None, *, limit=10):  # pragma: no cover
        return list(self._sessions.values())[:limit]

    def get_sessions_in_range(self, agent_id_or_start, start_or_end, end=None):
        if isinstance(agent_id_or_start, datetime):
            start, end_dt = agent_id_or_start, start_or_end
        else:
            start, end_dt = start_or_end, end
        assert end_dt is not None
        return [s for s in self._sessions.values() if start <= s.started_at <= end_dt]

    def get_key_moments_for_session(self, session_id):
        return list(self._moments.get(session_id, []))

    def get_key_moments_in_range(self, start, end):  # pragma: no cover
        out = []
        for s in self.get_sessions_in_range(start, end):
            out.extend(self._moments.get(s.id, []))
        return out

    def add_reframing_note(
        self, session_id: UUID, note: ReframingNote, /
    ) -> ReframingNoteAppendResult:  # pragma: no cover
        return ReframingNoteAppendResult.STORED


class _IdentityRepo:
    def __init__(self, identity):
        self._identity = identity
        self._snapshots: dict[UUID, IdentitySnapshot] = {}

    def get_current(self):
        return self._identity

    def get_snapshot(self, snapshot_id):
        return self._snapshots.get(snapshot_id)

    def create_snapshot(self, identity, description, change_summary, *, snapshot_id=None):
        sid = snapshot_id or uuid4()
        snap = IdentitySnapshot(
            id=sid,
            identity_id=identity.id,
            identity_snapshot=identity.model_copy(deep=True),
            description=description,
            change_summary=change_summary,
        )
        self._snapshots[sid] = snap
        return snap

    def get_history(self):  # pragma: no cover
        return list(self._snapshots.values())

    def update(self, identity):  # pragma: no cover
        self._identity = identity


class _Guardian(MemoryGuardian):
    def __init__(self, findings):
        self._findings = {f.id: f for f in findings}

    def scan_orphan_entities(self, agent_id):  # pragma: no cover
        return []

    def scan_merge_candidates(self, agent_id, *, similarity_threshold=0.92):  # pragma: no cover
        return []

    def scan_stale_moments(self, agent_id, *, days_threshold=90):  # pragma: no cover
        return []

    def scan_embedding_gaps(self, agent_id):  # pragma: no cover
        return []

    def write_finding(self, finding):  # pragma: no cover
        self._findings[finding.id] = finding
        return finding

    def get_unresolved(self, agent_id, severity=None):
        out = [f for f in self._findings.values() if not f.is_resolved]
        if severity is not None:
            out = [f for f in out if f.severity.value == severity]
        return out

    def resolve_finding(self, finding_id, *, resolution, resolved_by, note=""):
        f = self._findings.get(finding_id)
        if f is None:
            return None
        resolved = f.model_copy(
            update={
                "resolution": ResolutionStatus(resolution),
                "resolved_at": datetime.now(UTC),
                "resolved_by": resolved_by,
                "resolution_note": note,
            }
        )
        self._findings[finding_id] = resolved
        return resolved


def _session_and_moments(anchor):
    sid = uuid4()
    session = Session(id=sid, agent_id=AGENT_ID, started_at=anchor)
    moments = [
        KeyMoment(
            session_id=sid,
            what_happened=f"e{i}",
            when=anchor + timedelta(minutes=i),
            how_i_felt=FeltSense(
                emotional_valence=0.0,
                emotional_intensity=0.5,
                depth=EmotionalDepth.MEANINGFUL,
            ),
            why_it_matters="t",
        )
        for i in range(3)
    ]
    return session, moments


def test_daily_with_divergences_and_findings_triage():
    anchor = datetime(2026, 5, 16, 12, 0, 0, tzinfo=UTC)
    session, moments = _session_and_moments(anchor)

    # Three thinking_suppression divergences in the day + one rupture.
    estore = InMemoryDivergenceEventStore()
    for i in range(3):
        estore.write_event(
            DivergenceEvent(
                agent_id=AGENT_ID,
                session_id=session.id,
                key_moment_id=moments[0].id,
                divergence_type=DivergenceType.thinking_suppression,
                severity=DivergenceSeverity.notable,
                created_at=anchor + timedelta(hours=i),
            )
        )
    estore.write_event(
        DivergenceEvent(
            agent_id=AGENT_ID,
            session_id=session.id,
            key_moment_id=moments[1].id,
            divergence_type=DivergenceType.message_entity_gap,
            severity=DivergenceSeverity.rupture,
            created_at=anchor + timedelta(hours=4),
        )
    )

    pattern_store = InMemoryPatternStore()
    div_agg = DivergenceAggregator(estore, pattern_store, min_count=3)

    # Findings: one orphan (should resolve), one critical (should skip).
    findings = [
        ValidationFinding(
            agent_id=AGENT_ID,
            finding_type=FindingType.orphan_entity,
            severity=FindingSeverity.warning,
            target_table="entities",
            target_id=uuid4(),
            detected_at=datetime.now(UTC),
            detected_by="test",
        ),
        ValidationFinding(
            agent_id=AGENT_ID,
            finding_type=FindingType.affect_detector_silent,
            severity=FindingSeverity.critical,
            target_table="moments",
            target_id=uuid4(),
            detected_at=datetime.now(UTC),
            detected_by="test",
        ),
    ]
    guardian = _Guardian(findings)
    triage = FindingsTriage(guardian)

    service = DailyReflectionService(
        session_repo=_SessionRepo([session], {session.id: moments}),
        identity_repo=_IdentityRepo(Identity()),
        pattern_store=pattern_store,
        reflection_model=MockReflectionModel(),
        event_store=InMemoryReflectionEventStore(),
        divergence_aggregator=div_agg,
        findings_triage=triage,
        agent_id=AGENT_ID,
    )

    event = service.reflect(anchor)

    # Divergence pattern recorded + rupture surfaced.
    div_patterns = [p for p in pattern_store.get_all() if "divergence" in p.description]
    assert len(div_patterns) == 1
    assert div_patterns[0].id in event.patterns_detected
    assert "Ruptures observed" in (event.key_insight or "")
    assert "divergence_patterns=1" in (event.notes or "")
    assert "divergence_ruptures=1" in (event.notes or "")

    # Findings: orphan resolved; critical left unresolved.
    assert "findings_triage_resolved=1" in (event.notes or "")
    assert "findings_triage_attention=0" in (event.notes or "")
    # Guardian state mirrors that.
    remaining = guardian.get_unresolved(AGENT_ID)
    assert len(remaining) == 1
    assert remaining[0].finding_type == FindingType.affect_detector_silent


def test_daily_without_aggregator_or_triage_behaves_normally():
    anchor = datetime(2026, 5, 16, 12, 0, 0, tzinfo=UTC)
    session, moments = _session_and_moments(anchor)

    service = DailyReflectionService(
        session_repo=_SessionRepo([session], {session.id: moments}),
        identity_repo=_IdentityRepo(Identity()),
        pattern_store=InMemoryPatternStore(),
        reflection_model=MockReflectionModel(),
        event_store=InMemoryReflectionEventStore(),
    )
    event = service.reflect(anchor)
    notes = event.notes or ""
    assert "divergence_patterns" not in notes
    assert "findings_triage" not in notes
