"""Tests for NarrativeRevisionService."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from atman.adapters.reflection.mock_reflection_model import MockReflectionModel
from atman.core.exceptions import GovernanceRejectedError, NarrativePersistenceConflictError
from atman.core.models.experience import (
    EmotionalDepth,
    FeltSense,
    KeyMoment,
    SessionExperience,
)
from atman.core.models.governance import GovernanceDecision, GovernanceMode
from atman.core.models.identity import CoreValue, Identity
from atman.core.models.narrative import (
    LayerType,
    NarrativeDocument,
    NarrativeLayer,
)
from atman.core.models.reflection import PatternCandidate, PatternType, ReflectionLevel
from atman.core.narrative_write_audit import NoOpNarrativeWriteAudit
from atman.core.services.narrative_revision import NarrativeRevisionService


class _StubNarrativeRepo:
    """Minimal NarrativeRepository for tests."""

    def __init__(self, initial: NarrativeDocument | None) -> None:
        self._current = initial.model_copy(deep=True) if initial is not None else None

    def get_current(self) -> NarrativeDocument | None:
        if self._current is None:
            return None
        return self._current.model_copy(deep=True)

    def update(
        self, narrative: NarrativeDocument, *, expected_updated_at: datetime | None = None
    ) -> None:
        if self._current is None:
            self._current = narrative.model_copy(deep=True)
            return
        if expected_updated_at is not None and self._current.updated_at != expected_updated_at:
            raise NarrativePersistenceConflictError(
                "Narrative was modified concurrently since this snapshot was read."
            )
        self._current = narrative.model_copy(deep=True)

    def get_history(self) -> list[NarrativeDocument]:
        return []

    def bump_committed_timestamp(self) -> None:
        """Simulate another writer advancing ``updated_at`` on the stored document."""
        if self._current is None:
            return
        self._current = self._current.model_copy(deep=True)
        self._current.updated_at = self._current.updated_at + timedelta(seconds=30)


class _AuditSink:
    """Captures :class:`NarrativeWriteAuditPort` calls for assertions."""

    def __init__(self) -> None:
        self.kinds: list[str] = []
        self.failures: list[tuple[str, str]] = []

    def record_narrative_commit(
        self,
        *,
        change_kind: str,
        narrative_id: UUID,
        identity_id: UUID,
        reason_or_summary: str,
    ) -> None:
        self.kinds.append(change_kind)

    def record_narrative_commit_audit_failure(
        self,
        *,
        change_kind: str,
        narrative_id: UUID,
        identity_id: UUID,
        committed_summary: str,
        error_message: str,
    ) -> None:
        self.failures.append((change_kind, error_message))


class _FlakyAuditSink(_AuditSink):
    """Primary audit raises; failure path must still run."""

    def record_narrative_commit(
        self,
        *,
        change_kind: str,
        narrative_id: UUID,
        identity_id: UUID,
        reason_or_summary: str,
    ) -> None:
        raise RuntimeError("audit sink unavailable")


class _DoubleFaultAuditSink(_FlakyAuditSink):
    """Both primary and failure recorders raise (exercises warning path)."""

    def record_narrative_commit_audit_failure(
        self,
        *,
        change_kind: str,
        narrative_id: UUID,
        identity_id: UUID,
        committed_summary: str,
        error_message: str,
    ) -> None:
        raise OSError("failure recorder also broken")


def _minimal_narrative() -> NarrativeDocument:
    iid = uuid4()
    return NarrativeDocument(
        identity_id=iid,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="I am core."),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="I am recent."),
        threads=[],
    )


def _sample_experience() -> SessionExperience:
    km = KeyMoment(
        what_happened="Happened",
        how_i_felt=FeltSense(
            emotional_valence=0.2,
            emotional_intensity=0.5,
            depth=EmotionalDepth.MEANINGFUL,
        ),
        why_it_matters="Matters",
    )
    return SessionExperience(
        session_id=uuid4(),
        key_moment_ids=[km.id],
        avg_emotional_intensity=km.how_i_felt.emotional_intensity,
        has_profound_moment=km.how_i_felt.depth == EmotionalDepth.PROFOUND,
    )


def test_update_recent_layer_no_narrative() -> None:
    svc = NarrativeRevisionService(
        _StubNarrativeRepo(None), MockReflectionModel(), narrative_audit=NoOpNarrativeWriteAudit()
    )
    assert svc.update_recent_layer([], ReflectionLevel.MICRO) == "No narrative to update"


def test_update_recent_layer_updates_repo() -> None:
    doc = _minimal_narrative()
    repo = _StubNarrativeRepo(doc)
    svc = NarrativeRevisionService(
        repo, MockReflectionModel(), narrative_audit=NoOpNarrativeWriteAudit()
    )
    out = svc.update_recent_layer([_sample_experience()], ReflectionLevel.MICRO)
    assert len(out) > 0
    cur = repo.get_current()
    assert cur is not None
    assert cur.recent_layer.content == out


def test_update_core_layer_no_narrative() -> None:
    svc = NarrativeRevisionService(
        _StubNarrativeRepo(None), MockReflectionModel(), narrative_audit=NoOpNarrativeWriteAudit()
    )
    ident = Identity(self_description="Me")
    gov = GovernanceDecision(mode=GovernanceMode.REVIEW, review_approved=True)
    assert svc.update_core_layer(ident, [], "reason", gov) == "No narrative to update"


def test_update_core_layer_minimal_identity_low_confidence_patterns() -> None:
    doc = _minimal_narrative()
    repo = _StubNarrativeRepo(doc)
    svc = NarrativeRevisionService(
        repo, MockReflectionModel(), narrative_audit=NoOpNarrativeWriteAudit()
    )
    ident = Identity()
    pat = PatternCandidate(
        pattern_type=PatternType.COGNITIVE,
        description="Low confidence",
        detected_by=ReflectionLevel.DAILY,
        confidence=0.2,
    )
    gov = GovernanceDecision(mode=GovernanceMode.REVIEW, review_approved=True)
    text = svc.update_core_layer(ident, [pat], "only reason", gov)
    assert "only reason" in text


def test_update_core_layer_with_identity_and_patterns() -> None:
    doc = _minimal_narrative()
    repo = _StubNarrativeRepo(doc)
    svc = NarrativeRevisionService(
        repo, MockReflectionModel(), narrative_audit=NoOpNarrativeWriteAudit()
    )
    ident = Identity(
        self_description="I grow.",
        core_values=[CoreValue(name="honesty", description="truth", confidence=0.9)],
    )
    pat = PatternCandidate(
        pattern_type=PatternType.EMOTIONAL,
        description="High confidence pattern text.",
        detected_by=ReflectionLevel.DAILY,
        confidence=0.9,
    )
    gov = GovernanceDecision(mode=GovernanceMode.REVIEW, review_approved=True)
    text = svc.update_core_layer(ident, [pat], "deep review", gov)
    assert "honesty" in text
    assert "deep review" in text
    cur = repo.get_current()
    assert cur is not None
    assert cur.core_layer.content == text
    assert "High confidence" in text


def test_open_thread_raises_without_narrative() -> None:
    svc = NarrativeRevisionService(
        _StubNarrativeRepo(None), MockReflectionModel(), narrative_audit=NoOpNarrativeWriteAudit()
    )
    with pytest.raises(ValueError, match="No narrative document"):
        svc.open_thread("t", "d")


def test_update_thread_and_close_without_narrative() -> None:
    svc = NarrativeRevisionService(
        _StubNarrativeRepo(None), MockReflectionModel(), narrative_audit=NoOpNarrativeWriteAudit()
    )
    assert svc.update_thread(str(uuid4()), "x") is None
    assert svc.close_thread(str(uuid4()), "reason") is False


def test_open_update_close_thread_flow() -> None:
    doc = _minimal_narrative()
    repo = _StubNarrativeRepo(doc)
    svc = NarrativeRevisionService(
        repo, MockReflectionModel(), narrative_audit=NoOpNarrativeWriteAudit()
    )

    thread = svc.open_thread("Topic", "About topic", context="Started")
    assert thread.title == "Topic"

    cur = repo.get_current()
    assert cur is not None
    assert len(cur.threads) == 1

    updated = svc.update_thread(str(thread.id), "New state", add_moment="A moment")
    assert updated is not None
    assert updated.current_state == "New state"
    assert "A moment" in updated.key_moments

    assert svc.update_thread("not-a-uuid", "x") is None
    assert svc.update_thread(str(uuid4()), "x") is None

    assert svc.close_thread(str(thread.id), "done") is True
    assert svc.close_thread("bad", "r") is False
    assert svc.close_thread(str(uuid4()), "r") is False

    svc2 = NarrativeRevisionService(
        repo, MockReflectionModel(), narrative_audit=NoOpNarrativeWriteAudit()
    )
    t2 = svc2.open_thread("T2", "D2")
    assert svc2.close_thread(str(t2.id), "") is False


def test_repo_update_rejects_stale_concurrency_token() -> None:
    doc = _minimal_narrative()
    repo = _StubNarrativeRepo(doc)
    token = doc.updated_at
    repo.bump_committed_timestamp()
    fresh = repo.get_current()
    assert fresh is not None
    with pytest.raises(NarrativePersistenceConflictError):
        repo.update(fresh, expected_updated_at=token)


def test_update_core_layer_records_audit_when_configured() -> None:
    doc = _minimal_narrative()
    repo = _StubNarrativeRepo(doc)
    audit = _AuditSink()
    svc = NarrativeRevisionService(repo, MockReflectionModel(), narrative_audit=audit)
    ident = Identity(self_description="Audited")
    gov = GovernanceDecision(mode=GovernanceMode.REVIEW, review_approved=True)
    svc.update_core_layer(ident, [], "reason", gov)
    assert audit.kinds == ["core_layer"]


def test_open_thread_records_audit_when_configured() -> None:
    doc = _minimal_narrative()
    repo = _StubNarrativeRepo(doc)
    audit = _AuditSink()
    svc = NarrativeRevisionService(repo, MockReflectionModel(), narrative_audit=audit)
    svc.open_thread("T", "D")
    assert audit.kinds == ["thread_open"]


def test_audit_primary_failure_records_degraded_audit_row() -> None:
    doc = _minimal_narrative()
    repo = _StubNarrativeRepo(doc)
    audit = _FlakyAuditSink()
    svc = NarrativeRevisionService(repo, MockReflectionModel(), narrative_audit=audit)

    before = repo.get_current()
    assert before is not None
    svc.update_recent_layer([_sample_experience()], ReflectionLevel.MICRO)

    assert audit.kinds == []
    assert len(audit.failures) == 1
    assert audit.failures[0][0] == "recent_layer"
    assert "RuntimeError" in audit.failures[0][1]

    after = repo.get_current()
    assert after is not None
    assert after.recent_layer.content != before.recent_layer.content


def test_update_core_layer_rejects_auto_governance() -> None:
    doc = _minimal_narrative()
    repo = _StubNarrativeRepo(doc)
    svc = NarrativeRevisionService(
        repo, MockReflectionModel(), narrative_audit=NoOpNarrativeWriteAudit()
    )
    ident = Identity(self_description="X")
    gov = GovernanceDecision(mode=GovernanceMode.AUTO, review_approved=False)
    with pytest.raises(GovernanceRejectedError, match="governance approval"):
        svc.update_core_layer(ident, [], "reason", gov)


def test_update_core_layer_allows_experimental_with_review_approval() -> None:
    doc = _minimal_narrative()
    repo = _StubNarrativeRepo(doc)
    svc = NarrativeRevisionService(
        repo, MockReflectionModel(), narrative_audit=NoOpNarrativeWriteAudit()
    )
    ident = Identity(self_description="Exp")
    pat = PatternCandidate(
        pattern_type=PatternType.EMOTIONAL,
        description="High confidence pattern text.",
        detected_by=ReflectionLevel.DAILY,
        confidence=0.9,
    )
    gov = GovernanceDecision(mode=GovernanceMode.EXPERIMENTAL, review_approved=True)
    text = svc.update_core_layer(ident, [pat], "lab run", gov)
    assert "lab run" in text


def test_update_core_layer_rejects_review_without_approval() -> None:
    doc = _minimal_narrative()
    repo = _StubNarrativeRepo(doc)
    svc = NarrativeRevisionService(
        repo, MockReflectionModel(), narrative_audit=NoOpNarrativeWriteAudit()
    )
    ident = Identity(self_description="X")
    gov = GovernanceDecision(mode=GovernanceMode.REVIEW, review_approved=False)
    with pytest.raises(GovernanceRejectedError, match="governance approval"):
        svc.update_core_layer(ident, [], "reason", gov)


def test_update_thread_uses_injected_clock() -> None:
    from atman.core.clock_impl import FrozenClock

    fixed = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
    doc = _minimal_narrative()
    repo = _StubNarrativeRepo(doc)
    svc = NarrativeRevisionService(
        repo,
        MockReflectionModel(),
        narrative_audit=NoOpNarrativeWriteAudit(),
        clock=FrozenClock(fixed),
    )
    t = svc.open_thread("A", "B")
    svc.update_thread(str(t.id), "next")
    cur = repo.get_current()
    assert cur is not None
    updated_t = next(x for x in cur.threads if x.id == t.id)
    assert updated_t.last_updated == fixed


def test_audit_double_fault_emits_warning() -> None:
    doc = _minimal_narrative()
    repo = _StubNarrativeRepo(doc)
    audit = _DoubleFaultAuditSink()
    svc = NarrativeRevisionService(repo, MockReflectionModel(), narrative_audit=audit)

    with pytest.warns(RuntimeWarning, match="persisted but audit failed"):
        svc.update_recent_layer([_sample_experience()], ReflectionLevel.MICRO)


# --- SYSTEM_MAP §4.4 / §5.3: GovernanceMode.LOCKED rejection ---


def test_governance_mode_locked_raises_governance_rejected_error() -> None:
    """SYSTEM_MAP §4.4: ``GovernanceMode.LOCKED`` blocks any core-layer commit, even with review."""
    doc = _minimal_narrative()
    repo = _StubNarrativeRepo(doc)
    svc = NarrativeRevisionService(
        repo, MockReflectionModel(), narrative_audit=NoOpNarrativeWriteAudit()
    )
    ident = Identity(self_description="Me")
    locked = GovernanceDecision(mode=GovernanceMode.LOCKED, review_approved=True)

    with pytest.raises(GovernanceRejectedError, match="locked"):
        svc.update_core_layer(ident, [], "reason", locked)
