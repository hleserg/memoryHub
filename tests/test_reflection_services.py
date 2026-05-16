"""
Tests for reflection services.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest

from atman.adapters.reflection.fixture_loader import (
    anchor_session_experiences_to_utc_day_window,
    load_reflection_identity,
    load_reflection_session_experiences,
)
from atman.adapters.reflection.mock_reflection_model import MockReflectionModel
from atman.adapters.storage.in_memory_reflection_store import (
    InMemoryHealthAssessmentStore,
    InMemoryPatternStore,
    InMemoryReflectionEventStore,
)
from atman.core.exceptions import NarrativePersistenceConflictError
from atman.core.models.experience import (
    EmotionalDepth,
    FeltSense,
    KeyMoment,
    ReframingNote,
    ReframingNoteAppendResult,
    SessionExperience,
)
from atman.core.models.identity import Identity, IdentitySnapshot
from atman.core.models.narrative import LayerType, NarrativeDocument, NarrativeLayer
from atman.core.models.reflection import (
    HealthCriterionOutput,
    JahodaCriterion,
    NarrativeUpdateOutput,
    PatternDetectionOutput,
    ReflectionEvent,
    ReflectionLevel,
    ReframingNoteOutput,
)
from atman.core.models.session import Session
from atman.core.narrative_write_audit import NoOpNarrativeWriteAudit
from atman.core.reflection_event_audit import NoOpReflectionEventPersistenceObserver
from atman.core.reflection_run_keys import (
    daily_reflection_run_key_empty_day,
    daily_reflection_run_key_for_identity,
    deep_reflection_run_key_empty,
    deep_reflection_run_key_for_identity,
    identity_anchor_snapshot_id_for_run_key,
)
from atman.core.services.narrative_revision import NarrativeRevisionService
from atman.core.services.reflection_service import (
    DailyReflectionService,
    DeepReflectionService,
    MicroReflectionService,
)


class MockExperienceRepo:
    """
    Mock experience repository.

    Implements both the legacy :class:`ExperienceRepository` surface (still
    used by Micro and Deep reflection in these tests) AND the new
    :class:`SessionRepository` surface (used by Daily reflection after R3),
    so the same fixture can drive either port without test duplication.

    For SessionRepository methods a synthetic ``Session`` per experience is
    derived from the fixture's ``timestamp`` and ``identity_snapshot_id``,
    and one ``KeyMoment`` per ``key_moment_id`` is generated with safe
    defaults.
    """

    def __init__(self, experiences: list[SessionExperience]):
        """Initialize with experiences."""
        self.experiences = {exp.id: exp for exp in experiences}
        self._sessions: dict[UUID, Session] = {}
        self._moments_by_session: dict[UUID, list[KeyMoment]] = {}
        for exp in experiences:
            self._sessions[exp.id] = Session(
                id=exp.id,
                agent_id=uuid4(),
                started_at=exp.timestamp,
                identity_snapshot_id=exp.identity_snapshot_id,
            )
            depth = (
                EmotionalDepth.PROFOUND if exp.has_profound_moment else EmotionalDepth.MEANINGFUL
            )
            self._moments_by_session[exp.id] = [
                KeyMoment(
                    id=km_id,
                    session_id=exp.id,
                    what_happened="synthetic",
                    how_i_felt=FeltSense(
                        emotional_valence=0.0,
                        emotional_intensity=exp.avg_emotional_intensity,
                        depth=depth,
                    ),
                    why_it_matters="synthetic test moment",
                    values_touched=[],
                )
                for km_id in exp.key_moment_ids
            ]

    def get(self, experience_id: UUID) -> SessionExperience | None:
        """Get experience by ID."""
        return self.experiences.get(experience_id)

    def get_all(self) -> list[SessionExperience]:
        """Get all experiences."""
        return list(self.experiences.values())

    def get_by_session(self, session_id: UUID) -> list[SessionExperience]:
        """Get experiences by session."""
        return [exp for exp in self.experiences.values() if exp.session_id == session_id]

    def get_recent(self, limit: int = 10) -> list[SessionExperience]:
        """Get recent experiences."""
        sorted_exps = sorted(self.experiences.values(), key=lambda e: e.timestamp, reverse=True)
        return sorted_exps[:limit]

    def get_in_range(self, start: datetime, end: datetime) -> list[SessionExperience]:
        """Get experiences in date range."""
        return [exp for exp in self.experiences.values() if start <= exp.timestamp <= end]

    def update(self, experience: SessionExperience) -> None:
        """Update experience."""
        self.experiences[experience.id] = experience

    def add_reframing_note(
        self, experience_id: UUID, note: ReframingNote
    ) -> ReframingNoteAppendResult:
        """Add reframing note; return explicit append outcome."""
        exp = self.experiences.get(experience_id)
        if exp is None:
            return ReframingNoteAppendResult.EXPERIENCE_NOT_FOUND
        if note.triggered_by and any(
            n.triggered_by == note.triggered_by for n in exp.reframing_notes
        ):
            return ReframingNoteAppendResult.DUPLICATE_TRIGGERED_BY
        exp.add_reframing_note(note)
        return ReframingNoteAppendResult.STORED

    # --- SessionRepository surface ----------------------------------------

    def get_session(self, session_id: UUID) -> Session | None:
        return self._sessions.get(session_id)

    def list_recent_sessions(
        self, agent_id: UUID | None = None, *, limit: int = 10
    ) -> list[Session]:
        return sorted(self._sessions.values(), key=lambda s: s.started_at, reverse=True)[:limit]

    def get_sessions_in_range(
        self,
        agent_id_or_start: UUID | datetime,
        start_or_end: datetime,
        end: datetime | None = None,
    ) -> list[Session]:
        if isinstance(agent_id_or_start, datetime):
            start, end_dt = agent_id_or_start, start_or_end
        else:
            start, end_dt = start_or_end, end
        assert end_dt is not None
        return sorted(
            [s for s in self._sessions.values() if start <= s.started_at <= end_dt],
            key=lambda s: s.started_at,
        )

    def get_key_moments_for_session(self, session_id: UUID) -> list[KeyMoment]:
        return list(self._moments_by_session.get(session_id, []))

    def get_key_moments_in_range(self, start: datetime, end: datetime) -> list[KeyMoment]:
        out: list[KeyMoment] = []
        for s in self.get_sessions_in_range(start, end):
            out.extend(self._moments_by_session.get(s.id, []))
        return out


class MockIdentityRepo:
    """Mock identity repository."""

    def __init__(self, identity: Identity):
        """Initialize with identity."""
        self.identity = identity
        self._snapshots: dict[UUID, IdentitySnapshot] = {}

    def get_current(self) -> Identity | None:
        """Get current identity."""
        return self.identity

    def get_snapshot(self, snapshot_id: UUID) -> IdentitySnapshot | None:
        """Get snapshot."""
        return self._snapshots.get(snapshot_id)

    def get_history(self) -> list[IdentitySnapshot]:
        """Get history."""
        return list(self._snapshots.values())

    def update(self, identity: Identity) -> None:
        """Update identity."""
        self.identity = identity

    def create_snapshot(
        self,
        identity: Identity,
        description: str,
        change_summary: str,
        *,
        snapshot_id: UUID | None = None,
    ) -> IdentitySnapshot:
        """Create snapshot."""
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


class MockNarrativeRepo:
    """Mock narrative repository."""

    def __init__(self, narrative: NarrativeDocument | None):
        """Initialize with narrative (None simulates missing current narrative)."""
        self.narrative = narrative

    def get_current(self) -> NarrativeDocument | None:
        """Get current narrative."""
        if self.narrative is None:
            return None
        return self.narrative.model_copy(deep=True)

    def update(
        self, narrative: NarrativeDocument, *, expected_updated_at: datetime | None = None
    ) -> None:
        """Update narrative with optional optimistic concurrency on ``updated_at``."""
        if self.narrative is None:
            self.narrative = narrative.model_copy(deep=True)
            return
        if expected_updated_at is not None and self.narrative.updated_at != expected_updated_at:
            raise NarrativePersistenceConflictError(
                "Narrative was modified concurrently since this snapshot was read."
            )
        self.narrative = narrative.model_copy(deep=True)

    def get_history(self) -> list[NarrativeDocument]:
        """Get history."""
        return []


class ConflictNarrativeRepo(MockNarrativeRepo):
    """Repository that always rejects narrative writes (optimistic conflict)."""

    def update(
        self, narrative: NarrativeDocument, *, expected_updated_at: datetime | None = None
    ) -> None:
        raise NarrativePersistenceConflictError("simulated concurrent narrative write")


class NullIdentityRepo:
    """Identity repository with no current identity (audit / degraded path)."""

    def get_current(self) -> Identity | None:
        return None

    def get_snapshot(self, snapshot_id: UUID) -> IdentitySnapshot | None:
        return None

    def get_history(self) -> list[IdentitySnapshot]:
        return []

    def update(self, identity: Identity) -> None:
        return None

    def create_snapshot(
        self,
        identity: Identity,
        description: str,
        change_summary: str,
        *,
        snapshot_id: UUID | None = None,
    ) -> IdentitySnapshot:
        return IdentitySnapshot(
            id=snapshot_id or uuid4(),
            identity_id=identity.id,
            identity_snapshot=identity,
            description=description,
            change_summary=change_summary,
        )


class FlakyReflectionEventStore(InMemoryReflectionEventStore):
    """Fails the first save of a non-failure deep reflection event."""

    def __init__(self) -> None:
        super().__init__()
        self._fail_eligible_once = True

    def save(self, event: ReflectionEvent) -> None:
        notes = event.notes or ""
        if self._fail_eligible_once and "outcome=deep_failed" not in notes:
            self._fail_eligible_once = False
            raise RuntimeError("simulated reflection event persist failure")
        super().save(event)


class FlakyDailyReflectionEventStore(InMemoryReflectionEventStore):
    """Fails the first persistence of a successful daily reflection event."""

    def __init__(self) -> None:
        super().__init__()
        self._fail_once_daily_ok = True

    def save(self, event: ReflectionEvent) -> None:
        notes = event.notes or ""
        if self._fail_once_daily_ok and "outcome=daily_ok" in notes:
            self._fail_once_daily_ok = False
            raise RuntimeError("simulated daily reflection event persist failure")
        super().save(event)


class RejectingReframeMockRepo(MockExperienceRepo):
    """Experience repo that rejects reframing appends while experiences exist."""

    def add_reframing_note(
        self, experience_id: UUID, note: ReframingNote
    ) -> ReframingNoteAppendResult:
        if experience_id not in self.experiences:
            return ReframingNoteAppendResult.EXPERIENCE_NOT_FOUND
        return ReframingNoteAppendResult.STORAGE_REJECTED


class StructuredOutputReflectionModel(MockReflectionModel):
    """Configurable model for structured-output service boundary tests."""

    def __init__(
        self,
        *,
        pattern_description: str = "",
        pattern_confidence: float | None = None,
        reframing_text: str = "",
        potential_habit: str = "",
        potential_principle: str = "",
        health_score: float = 0.6,
        narrative_body: str = "Structured narrative proposal.",
    ) -> None:
        self.pattern_description = pattern_description
        self.pattern_confidence = pattern_confidence
        self.reframing_text = reframing_text
        self.potential_habit = potential_habit
        self.potential_principle = potential_principle
        self.health_score = health_score
        self.narrative_body = narrative_body

    def detect_pattern(
        self,
        experiences: list[SessionExperience],
        context: dict[str, str],
    ) -> PatternDetectionOutput:
        return PatternDetectionOutput(
            description=self.pattern_description,
            confidence=self.pattern_confidence,
            potential_habit=self.potential_habit,
            potential_principle=self.potential_principle,
        )

    def generate_reframing_note(
        self,
        experience: SessionExperience,
        context: dict[str, str],
    ) -> ReframingNoteOutput:
        return ReframingNoteOutput(reflection=self.reframing_text, reflection_type="boundary")

    def propose_narrative_update(
        self,
        current_narrative: NarrativeDocument,
        recent_experiences: list[SessionExperience],
        reflection_level: ReflectionLevel,
    ) -> NarrativeUpdateOutput:
        return NarrativeUpdateOutput(body=self.narrative_body)

    def assess_health_criterion(
        self,
        identity: Identity,
        experiences: list[SessionExperience],
        criterion: JahodaCriterion,
    ) -> HealthCriterionOutput:
        return HealthCriterionOutput(
            score=self.health_score,
            evidence=[f"covered {criterion.value}"],
            concerns=[],
        )


def create_test_experience(session_id: UUID | None = None) -> SessionExperience:
    """Create a test experience."""
    if session_id is None:
        session_id = uuid4()

    km = KeyMoment(
        what_happened="Test event",
        how_i_felt=FeltSense(
            emotional_valence=0.3,
            emotional_intensity=0.6,
            depth=EmotionalDepth.MEANINGFUL,
        ),
        why_it_matters="Test importance",
        values_touched=["test_value"],
    )

    return SessionExperience(
        session_id=session_id,
        key_moment_ids=[km.id],
        avg_emotional_intensity=km.how_i_felt.emotional_intensity,
        has_profound_moment=km.how_i_felt.depth == EmotionalDepth.PROFOUND,
    )


def test_micro_reflection_updates_narrative() -> None:
    """Test that micro reflection updates the recent narrative layer."""
    session_id = uuid4()
    exp = create_test_experience(session_id)

    identity = Identity()
    narrative = NarrativeDocument(
        identity_id=identity.id,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="Core"),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="Old recent"),
    )

    exp_repo = MockExperienceRepo([exp])
    narrative_repo = MockNarrativeRepo(narrative)
    reflection_model = MockReflectionModel()
    event_store = InMemoryReflectionEventStore()
    narrative_revision = NarrativeRevisionService(
        narrative_repo, reflection_model, narrative_audit=NoOpNarrativeWriteAudit()
    )

    service = MicroReflectionService(
        experience_repo=exp_repo,
        narrative_revision=narrative_revision,
        event_store=event_store,
    )

    event = service.reflect(session_id)

    assert event.reflection_level == ReflectionLevel.MICRO
    assert len(event.experiences_analyzed) == 1
    updated = narrative_repo.get_current()
    assert updated is not None
    assert updated.recent_layer.content != "Old recent"


def test_micro_reflection_no_experiences() -> None:
    """Test micro reflection with no experiences."""
    identity = Identity()
    narrative = NarrativeDocument(
        identity_id=identity.id,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="Core"),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="Recent"),
    )

    exp_repo = MockExperienceRepo([])
    narrative_repo = MockNarrativeRepo(narrative)
    reflection_model = MockReflectionModel()
    event_store = InMemoryReflectionEventStore()
    narrative_revision = NarrativeRevisionService(
        narrative_repo, reflection_model, narrative_audit=NoOpNarrativeWriteAudit()
    )

    service = MicroReflectionService(
        experience_repo=exp_repo,
        narrative_revision=narrative_revision,
        event_store=event_store,
    )

    event = service.reflect(uuid4())

    assert event.reflection_level == ReflectionLevel.MICRO
    assert len(event.experiences_analyzed) == 0
    assert "no experiences" in event.key_insight.lower()
    assert "no_experiences" in event.notes


def test_micro_reflection_narrative_conflict_persists_failed_event() -> None:
    """Concurrent narrative edit: no successful write, but a failed outcome is audited."""
    session_id = uuid4()
    exp = create_test_experience(session_id)

    identity = Identity()
    narrative = NarrativeDocument(
        identity_id=identity.id,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="Core"),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="Old recent"),
    )

    exp_repo = MockExperienceRepo([exp])
    narrative_repo = ConflictNarrativeRepo(narrative)
    reflection_model = MockReflectionModel()
    event_store = InMemoryReflectionEventStore()
    narrative_revision = NarrativeRevisionService(
        narrative_repo, reflection_model, narrative_audit=NoOpNarrativeWriteAudit()
    )

    service = MicroReflectionService(
        experience_repo=exp_repo,
        narrative_revision=narrative_revision,
        event_store=event_store,
    )

    event = service.reflect(session_id)

    assert event.reflection_level == ReflectionLevel.MICRO
    assert event.experiences_analyzed == [exp.id]
    assert "narrative_conflict" in event.notes
    assert "micro_failed" in event.notes
    assert event_store.get_all()[-1].id == event.id
    cur = narrative_repo.get_current()
    assert cur is not None
    assert cur.recent_layer.content == "Old recent"


def test_micro_reflection_no_narrative() -> None:
    """Micro reflection skips distinctly when experiences exist but narrative is missing."""
    session_id = uuid4()
    exp = create_test_experience(session_id)

    exp_repo = MockExperienceRepo([exp])
    narrative_repo = MockNarrativeRepo(None)
    reflection_model = MockReflectionModel()
    event_store = InMemoryReflectionEventStore()
    narrative_revision = NarrativeRevisionService(
        narrative_repo, reflection_model, narrative_audit=NoOpNarrativeWriteAudit()
    )

    service = MicroReflectionService(
        experience_repo=exp_repo,
        narrative_revision=narrative_revision,
        event_store=event_store,
    )

    event = service.reflect(session_id)

    assert event.reflection_level == ReflectionLevel.MICRO
    assert event.experiences_analyzed == [exp.id]
    assert "no current narrative" in event.key_insight.lower()
    assert "no_narrative" in event.notes


def test_daily_reflection_detects_patterns() -> None:
    """Test that daily reflection detects patterns."""
    anchor = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
    exp1 = create_test_experience().model_copy(update={"timestamp": anchor})
    exp2 = create_test_experience().model_copy(update={"timestamp": anchor})

    identity = Identity()

    exp_repo = MockExperienceRepo([exp1, exp2])
    identity_repo = MockIdentityRepo(identity)
    pattern_store = InMemoryPatternStore()
    reflection_model = MockReflectionModel()
    event_store = InMemoryReflectionEventStore()

    service = DailyReflectionService(
        session_repo=exp_repo,
        identity_repo=identity_repo,
        pattern_store=pattern_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    event = service.reflect(anchor)

    assert event.reflection_level == ReflectionLevel.DAILY
    assert len(event.experiences_analyzed) == 2


def test_daily_reflection_adds_reframing_notes() -> None:
    """Test that daily reflection can add reframing notes."""
    anchor = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
    exp1 = create_test_experience().model_copy(update={"timestamp": anchor})
    exp2 = create_test_experience().model_copy(update={"timestamp": anchor})

    identity = Identity()

    exp_repo = MockExperienceRepo([exp1, exp2])
    identity_repo = MockIdentityRepo(identity)
    pattern_store = InMemoryPatternStore()
    reflection_model = MockReflectionModel()
    event_store = InMemoryReflectionEventStore()

    service = DailyReflectionService(
        session_repo=exp_repo,
        identity_repo=identity_repo,
        pattern_store=pattern_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    event = service.reflect(anchor)

    assert event.reflection_level == ReflectionLevel.DAILY
    assert event.reframing_notes_added >= 1


def test_daily_reflection_reframing_count_skips_failed_persist() -> None:
    """Reframing count must not increase when the repo rejects the append."""
    anchor = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
    exp1 = create_test_experience().model_copy(update={"timestamp": anchor})
    exp2 = create_test_experience().model_copy(update={"timestamp": anchor})

    identity = Identity()

    exp_repo = RejectingReframeMockRepo([exp1, exp2])
    identity_repo = MockIdentityRepo(identity)
    pattern_store = InMemoryPatternStore()
    reflection_model = MockReflectionModel()
    event_store = InMemoryReflectionEventStore()

    service = DailyReflectionService(
        session_repo=exp_repo,
        identity_repo=identity_repo,
        pattern_store=pattern_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    event = service.reflect(anchor)

    assert event.reflection_level == ReflectionLevel.DAILY
    assert len(event.patterns_detected) >= 1
    assert event.reframing_notes_added == 0
    assert event.reframing_append_storage_rejected_count >= 1
    assert "signal=reframing_append_degraded" in (event.notes or "")


def test_daily_reflection_skips_short_structured_pattern_output() -> None:
    """A short structured pattern description is treated as no durable pattern."""
    anchor = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
    exp1 = create_test_experience().model_copy(update={"timestamp": anchor})
    exp2 = create_test_experience().model_copy(update={"timestamp": anchor})
    identity = Identity()
    exp_repo = MockExperienceRepo([exp1, exp2])
    identity_repo = MockIdentityRepo(identity)
    pattern_store = InMemoryPatternStore()
    event_store = InMemoryReflectionEventStore()
    reflection_model = StructuredOutputReflectionModel(pattern_description="123456789")

    service = DailyReflectionService(
        session_repo=exp_repo,
        identity_repo=identity_repo,
        pattern_store=pattern_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    event = service.reflect(anchor)

    assert event.patterns_detected == []
    assert pattern_store.get_all() == []
    assert event.reframing_notes_added == 0


def test_daily_reflection_persists_minimum_length_structured_pattern_output() -> None:
    """Daily reflection must preserve valid structured confidence at the length boundary."""
    anchor = datetime(2026, 9, 2, 12, 0, 0, tzinfo=UTC)
    exp1 = create_test_experience().model_copy(update={"timestamp": anchor})
    exp2 = create_test_experience().model_copy(update={"timestamp": anchor})
    identity = Identity()
    exp_repo = MockExperienceRepo([exp1, exp2])
    identity_repo = MockIdentityRepo(identity)
    pattern_store = InMemoryPatternStore()
    event_store = InMemoryReflectionEventStore()
    reflection_model = StructuredOutputReflectionModel(
        pattern_description="1234567890",
        pattern_confidence=0.41,
    )

    service = DailyReflectionService(
        session_repo=exp_repo,
        identity_repo=identity_repo,
        pattern_store=pattern_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    event = service.reflect(anchor)
    patterns = pattern_store.get_all()

    assert len(event.patterns_detected) == 1
    assert len(patterns) == 1
    assert patterns[0].description == "1234567890"
    assert patterns[0].confidence == 0.41


@pytest.mark.parametrize(
    ("reframing_text", "expected_notes_added"),
    [
        ("1234567890", 0),
        (" 12345678901 ", 2),
    ],
)
def test_daily_reflection_reframing_boundary_uses_stripped_length(
    reframing_text: str,
    expected_notes_added: int,
) -> None:
    """Structured reframing output is persisted only when stripped length exceeds ten."""
    anchor = datetime(2026, 9, 3, 12, 0, 0, tzinfo=UTC)
    exp1 = create_test_experience().model_copy(update={"timestamp": anchor})
    exp2 = create_test_experience().model_copy(update={"timestamp": anchor})
    identity = Identity()
    exp_repo = MockExperienceRepo([exp1, exp2])
    identity_repo = MockIdentityRepo(identity)
    pattern_store = InMemoryPatternStore()
    event_store = InMemoryReflectionEventStore()
    reflection_model = StructuredOutputReflectionModel(
        pattern_description="stable pattern",
        reframing_text=reframing_text,
    )

    service = DailyReflectionService(
        session_repo=exp_repo,
        identity_repo=identity_repo,
        pattern_store=pattern_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    event = service.reflect(anchor)

    assert event.reframing_notes_added == expected_notes_added
    assert len(exp1.reframing_notes) + len(exp2.reframing_notes) == expected_notes_added


def test_deep_reflection_performs_health_assessment() -> None:
    """Test that deep reflection performs health assessment."""
    anchor = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
    exp1 = create_test_experience().model_copy(update={"timestamp": anchor})
    exp2 = create_test_experience().model_copy(update={"timestamp": anchor})
    exp3 = create_test_experience().model_copy(update={"timestamp": anchor})

    identity = Identity()
    narrative = NarrativeDocument(
        identity_id=identity.id,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="Core"),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="Recent"),
    )

    exp_repo = MockExperienceRepo([exp1, exp2, exp3])
    identity_repo = MockIdentityRepo(identity)
    narrative_repo = MockNarrativeRepo(narrative)
    pattern_store = InMemoryPatternStore()
    health_store = InMemoryHealthAssessmentStore()
    reflection_model = MockReflectionModel()
    event_store = InMemoryReflectionEventStore()

    service = DeepReflectionService(
        session_repo=exp_repo,
        identity_repo=identity_repo,
        narrative_repo=narrative_repo,
        pattern_store=pattern_store,
        health_store=health_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    since = anchor.replace(hour=0, minute=0, second=0, microsecond=0)
    until = anchor

    event = service.reflect(since, until)

    assert event.reflection_level == ReflectionLevel.DEEP
    assert len(event.experiences_analyzed) == 3
    assert event.health_assessment_id is not None

    assessment = health_store.get(event.health_assessment_id)
    assert assessment is not None
    assert len(assessment.criteria) == 6
    assert 0.0 <= assessment.overall_score <= 1.0


def test_deep_reflection_proposes_changes() -> None:
    """Test that deep reflection proposes identity and narrative changes."""
    anchor = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
    exp1 = create_test_experience().model_copy(update={"timestamp": anchor})
    exp2 = create_test_experience().model_copy(update={"timestamp": anchor})
    exp3 = create_test_experience().model_copy(update={"timestamp": anchor})

    identity = Identity()
    narrative = NarrativeDocument(
        identity_id=identity.id,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="Core"),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="Recent"),
    )

    exp_repo = MockExperienceRepo([exp1, exp2, exp3])
    identity_repo = MockIdentityRepo(identity)
    narrative_repo = MockNarrativeRepo(narrative)
    pattern_store = InMemoryPatternStore()
    health_store = InMemoryHealthAssessmentStore()
    reflection_model = MockReflectionModel()
    event_store = InMemoryReflectionEventStore()

    service = DeepReflectionService(
        session_repo=exp_repo,
        identity_repo=identity_repo,
        narrative_repo=narrative_repo,
        pattern_store=pattern_store,
        health_store=health_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    since = anchor.replace(hour=0, minute=0, second=0, microsecond=0)
    until = anchor

    event = service.reflect(since, until)

    assert event.reflection_level == ReflectionLevel.DEEP
    assert event.narrative_changes_proposed != ""
    assert event.identity_changes_proposed != ""
    assert event.reframing_notes_added >= 1
    assert any(len(e.reframing_notes) > 0 for e in (exp1, exp2, exp3))


def test_deep_reflection_promotes_structured_pattern_implications() -> None:
    """Deep identity proposals should include habit/principle fields from structured output."""
    anchor = datetime(2026, 9, 4, 12, 0, 0, tzinfo=UTC)
    exp1 = create_test_experience().model_copy(update={"timestamp": anchor})
    exp2 = create_test_experience().model_copy(update={"timestamp": anchor})
    exp3 = create_test_experience().model_copy(update={"timestamp": anchor})
    identity = Identity()
    narrative = NarrativeDocument(
        identity_id=identity.id,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="Core"),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="Recent"),
    )
    exp_repo = MockExperienceRepo([exp1, exp2, exp3])
    identity_repo = MockIdentityRepo(identity)
    narrative_repo = MockNarrativeRepo(narrative)
    pattern_store = InMemoryPatternStore()
    health_store = InMemoryHealthAssessmentStore()
    event_store = InMemoryReflectionEventStore()
    reflection_model = StructuredOutputReflectionModel(
        pattern_description="structured pattern for implication",
        potential_habit="Pause before overcommitting",
        potential_principle="Prefer sustainable commitments",
        reframing_text="Strategic reframing note",
    )
    service = DeepReflectionService(
        session_repo=exp_repo,
        identity_repo=identity_repo,
        narrative_repo=narrative_repo,
        pattern_store=pattern_store,
        health_store=health_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    event = service.reflect(
        anchor.replace(hour=0, minute=0, second=0, microsecond=0),
        anchor.replace(hour=23, minute=59, second=59, microsecond=0),
    )

    assert len(event.patterns_detected) == 2
    assert "New habit: Pause before overcommitting" in event.identity_changes_proposed
    assert "New principle: Prefer sustainable commitments" in event.identity_changes_proposed


def test_deep_reflection_fixture_json_adds_reframing() -> None:
    """JSON fixtures (3+ experiences) anchored to today support deep reframing path."""
    experiences = anchor_session_experiences_to_utc_day_window(
        load_reflection_session_experiences()
    )
    assert len(experiences) >= 3

    identity = load_reflection_identity()
    narrative = NarrativeDocument(
        identity_id=identity.id,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="Core"),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="Recent"),
    )

    exp_repo = MockExperienceRepo(experiences)
    identity_repo = MockIdentityRepo(identity)
    narrative_repo = MockNarrativeRepo(narrative)
    pattern_store = InMemoryPatternStore()
    health_store = InMemoryHealthAssessmentStore()
    reflection_model = MockReflectionModel()
    event_store = InMemoryReflectionEventStore()

    service = DeepReflectionService(
        session_repo=exp_repo,
        identity_repo=identity_repo,
        narrative_repo=narrative_repo,
        pattern_store=pattern_store,
        health_store=health_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    since = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    until = datetime.now(UTC)
    event = service.reflect(since, until)

    assert event.reflection_level == ReflectionLevel.DEEP
    assert len(event.patterns_detected) >= 1
    assert event.reframing_notes_added >= 1
    assert any(len(exp.reframing_notes) > 0 for exp in experiences)


def test_daily_reflection_skipped_no_identity_preserves_experience_ids() -> None:
    """Experiences exist but identity is missing — not an empty day."""
    anchor = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
    exp1 = create_test_experience().model_copy(update={"timestamp": anchor})
    exp2 = create_test_experience().model_copy(update={"timestamp": anchor})

    exp_repo = MockExperienceRepo([exp1, exp2])
    identity_repo = NullIdentityRepo()
    pattern_store = InMemoryPatternStore()
    reflection_model = MockReflectionModel()
    event_store = InMemoryReflectionEventStore()

    service = DailyReflectionService(
        session_repo=exp_repo,
        identity_repo=identity_repo,
        pattern_store=pattern_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    event = service.reflect(anchor)

    assert event.reflection_level == ReflectionLevel.DAILY
    assert set(event.experiences_analyzed) == {exp1.id, exp2.id}
    assert "no_identity" in event.notes
    assert "daily_skipped" in event.notes
    assert "no experiences" not in event.key_insight.lower()


def test_deep_reflection_skipped_no_identity_preserves_experience_ids() -> None:
    anchor = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
    exp1 = create_test_experience().model_copy(update={"timestamp": anchor})
    exp2 = create_test_experience().model_copy(update={"timestamp": anchor})
    exp3 = create_test_experience().model_copy(update={"timestamp": anchor})

    identity = Identity()
    narrative = NarrativeDocument(
        identity_id=identity.id,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="Core"),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="Recent"),
    )

    exp_repo = MockExperienceRepo([exp1, exp2, exp3])
    identity_repo = NullIdentityRepo()
    narrative_repo = MockNarrativeRepo(narrative)
    pattern_store = InMemoryPatternStore()
    health_store = InMemoryHealthAssessmentStore()
    reflection_model = MockReflectionModel()
    event_store = InMemoryReflectionEventStore()

    service = DeepReflectionService(
        session_repo=exp_repo,
        identity_repo=identity_repo,
        narrative_repo=narrative_repo,
        pattern_store=pattern_store,
        health_store=health_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    since = anchor.replace(hour=0, minute=0, second=0, microsecond=0)
    until = anchor
    event = service.reflect(since, until)

    assert event.reflection_level == ReflectionLevel.DEEP
    assert set(event.experiences_analyzed) == {exp1.id, exp2.id, exp3.id}
    assert "no_identity" in event.notes
    assert "deep_skipped" in event.notes
    assert health_store.get_all() == []


def test_deep_reflection_persist_failure_links_health_assessment() -> None:
    """If success event persistence fails after health is stored, emit a failed run event."""
    anchor = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
    exp1 = create_test_experience().model_copy(update={"timestamp": anchor})
    exp2 = create_test_experience().model_copy(update={"timestamp": anchor})
    exp3 = create_test_experience().model_copy(update={"timestamp": anchor})

    identity = Identity()
    narrative = NarrativeDocument(
        identity_id=identity.id,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="Core"),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="Recent"),
    )

    exp_repo = MockExperienceRepo([exp1, exp2, exp3])
    identity_repo = MockIdentityRepo(identity)
    narrative_repo = MockNarrativeRepo(narrative)
    pattern_store = InMemoryPatternStore()
    health_store = InMemoryHealthAssessmentStore()
    reflection_model = MockReflectionModel()
    event_store = FlakyReflectionEventStore()
    observer = _CapturingReflectionEventObserver()

    service = DeepReflectionService(
        session_repo=exp_repo,
        identity_repo=identity_repo,
        narrative_repo=narrative_repo,
        pattern_store=pattern_store,
        health_store=health_store,
        reflection_model=reflection_model,
        event_store=event_store,
        reflection_event_observer=observer,
    )

    since = anchor.replace(hour=0, minute=0, second=0, microsecond=0)
    until = anchor
    run_key = deep_reflection_run_key_for_identity(since, until, identity.id)

    with pytest.raises(RuntimeError, match="persist failure"):
        service.reflect(since, until)

    assert observer.side_effect_errors == [
        f"deep|{run_key}|RuntimeError: simulated reflection event persist failure"
    ]
    assert len(health_store.get_all()) == 1
    stored_events = event_store.get_all()
    assert len(stored_events) == 1
    failed = stored_events[0]
    assert "deep_failed" in failed.notes
    assert failed.health_assessment_id is not None
    assert failed.health_assessment_id == health_store.get_all()[0].id


class _CapturingReflectionEventObserver:
    """Records reflection event persistence failures after narrative commit."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.side_effect_errors: list[str] = []

    def record_reflection_event_save_failed_after_narrative_commit(
        self,
        *,
        reflection_level: ReflectionLevel,
        error_message: str,
    ) -> None:
        self.errors.append(f"{reflection_level.value}:{error_message}")

    def record_reflection_job_event_save_failed_after_side_effects(
        self,
        *,
        reflection_level: ReflectionLevel,
        reflection_run_key: str | None,
        error_message: str,
    ) -> None:
        self.side_effect_errors.append(
            f"{reflection_level.value}|{reflection_run_key}|{error_message}"
        )


class FlakyMicroEventReflectionStore(InMemoryReflectionEventStore):
    """Fails the first persistence of a successful micro reflection event."""

    def __init__(self) -> None:
        super().__init__()
        self._fail_eligible_once = True

    def save(self, event: ReflectionEvent) -> None:
        notes = event.notes or ""
        if (
            self._fail_eligible_once
            and event.reflection_level == ReflectionLevel.MICRO
            and "micro_failed" not in notes
            and "micro_skipped" not in notes
        ):
            self._fail_eligible_once = False
            raise OSError("simulated micro reflection event persist failure")
        super().save(event)


def test_micro_reflection_notifies_observer_when_event_store_fails_after_narrative() -> None:
    """Narrative commit succeeds; failing event store must surface via observer."""
    session_id = uuid4()
    exp = create_test_experience(session_id)

    identity = Identity()
    narrative = NarrativeDocument(
        identity_id=identity.id,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="Core"),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="Old recent"),
    )

    exp_repo = MockExperienceRepo([exp])
    narrative_repo = MockNarrativeRepo(narrative)
    reflection_model = MockReflectionModel()
    event_store = FlakyMicroEventReflectionStore()
    observer = _CapturingReflectionEventObserver()
    narrative_revision = NarrativeRevisionService(
        narrative_repo, reflection_model, narrative_audit=NoOpNarrativeWriteAudit()
    )

    service = MicroReflectionService(
        experience_repo=exp_repo,
        narrative_revision=narrative_revision,
        event_store=event_store,
        reflection_event_observer=observer,
    )

    with pytest.raises(OSError, match="persist failure"):
        service.reflect(session_id)

    assert len(observer.errors) == 1
    assert "micro" in observer.errors[0]
    updated = narrative_repo.get_current()
    assert updated is not None
    assert updated.recent_layer.content != "Old recent"


def test_daily_reflection_second_run_same_window_is_idempotent() -> None:
    """Re-running daily reflection for the same day must not duplicate patterns or notes."""
    anchor = datetime(2026, 5, 2, 14, 30, 0, tzinfo=UTC)
    exp1 = create_test_experience().model_copy(update={"timestamp": anchor})
    exp2 = create_test_experience().model_copy(update={"timestamp": anchor})

    identity = Identity()

    exp_repo = MockExperienceRepo([exp1, exp2])
    identity_repo = MockIdentityRepo(identity)
    pattern_store = InMemoryPatternStore()
    reflection_model = MockReflectionModel()
    event_store = InMemoryReflectionEventStore()

    service = DailyReflectionService(
        session_repo=exp_repo,
        identity_repo=identity_repo,
        pattern_store=pattern_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    day = anchor.replace(hour=12, minute=0, second=0, microsecond=0)
    ev1 = service.reflect(day)
    ev2 = service.reflect(day)

    assert ev1.id == ev2.id
    rk = daily_reflection_run_key_for_identity(day, identity.id)
    assert ev1.identity_snapshot_id == identity_anchor_snapshot_id_for_run_key(rk)
    assert ev1.identity_snapshot_id != identity.id
    assert len(pattern_store.get_all()) == 1

    r1 = exp_repo.get(exp1.id)
    r2 = exp_repo.get(exp2.id)
    assert r1 is not None and r2 is not None
    total_notes = len(r1.reframing_notes) + len(r2.reframing_notes)
    assert total_notes == ev1.reframing_notes_added

    ev3 = service.reflect(day)
    assert ev3.id == ev1.id
    r1b = exp_repo.get(exp1.id)
    r2b = exp_repo.get(exp2.id)
    assert r1b is not None and r2b is not None
    assert len(r1b.reframing_notes) + len(r2b.reframing_notes) == total_notes


def test_daily_reflect_naive_anchor_compatible_with_utc_experience_timestamps() -> None:
    """Naive anchor must be normalized so get_in_range does not mix naive/aware bounds."""
    naive_day = datetime(2026, 5, 10, 8, 0, 0)
    ts = datetime(2026, 5, 10, 14, 0, 0, tzinfo=UTC)
    exp1 = create_test_experience().model_copy(update={"timestamp": ts})
    exp2 = create_test_experience().model_copy(update={"timestamp": ts})

    identity = Identity()
    exp_repo = MockExperienceRepo([exp1, exp2])
    identity_repo = MockIdentityRepo(identity)
    pattern_store = InMemoryPatternStore()
    reflection_model = MockReflectionModel()
    event_store = InMemoryReflectionEventStore()

    service = DailyReflectionService(
        session_repo=exp_repo,
        identity_repo=identity_repo,
        pattern_store=pattern_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    event = service.reflect(naive_day)
    assert event.reflection_level == ReflectionLevel.DAILY
    assert len(event.experiences_analyzed) == 2


def test_daily_reflect_utc_calendar_day_from_timezone_aware_anchor() -> None:
    """UTC calendar day for the anchor must match run-key day (not local wall replace)."""
    msk = ZoneInfo("Europe/Moscow")
    # 2026-01-16 02:00 MSK == 2026-01-15 23:00 UTC → UTC calendar day is 2026-01-15
    anchor = datetime(2026, 1, 16, 2, 0, 0, tzinfo=msk)
    inside = datetime(2026, 1, 15, 22, 0, 0, tzinfo=UTC)
    outside = datetime(2026, 1, 16, 0, 30, 0, tzinfo=UTC)

    exp_in = create_test_experience().model_copy(update={"timestamp": inside})
    exp_out = create_test_experience().model_copy(update={"timestamp": outside})

    identity = Identity()
    exp_repo = MockExperienceRepo([exp_in, exp_out])
    identity_repo = MockIdentityRepo(identity)
    pattern_store = InMemoryPatternStore()
    reflection_model = MockReflectionModel()
    event_store = InMemoryReflectionEventStore()

    service = DailyReflectionService(
        session_repo=exp_repo,
        identity_repo=identity_repo,
        pattern_store=pattern_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    event = service.reflect(anchor)
    assert event.reflection_level == ReflectionLevel.DAILY
    assert event.experiences_analyzed == [exp_in.id]
    assert exp_out.id not in event.experiences_analyzed


def test_daily_empty_day_is_idempotent() -> None:
    """Scheduled daily reflection should not duplicate empty-day audit events."""
    anchor = datetime(2026, 8, 3, 12, 0, 0, tzinfo=UTC)

    exp_repo = MockExperienceRepo([])
    identity_repo = MockIdentityRepo(Identity())
    pattern_store = InMemoryPatternStore()
    reflection_model = MockReflectionModel()
    event_store = InMemoryReflectionEventStore()

    service = DailyReflectionService(
        session_repo=exp_repo,
        identity_repo=identity_repo,
        pattern_store=pattern_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    first = service.reflect(anchor)
    second = service.reflect(anchor)

    assert first.id == second.id
    assert first.reflection_level == ReflectionLevel.DAILY
    assert first.experiences_analyzed == []
    assert "outcome=daily_empty" in (first.notes or "")
    assert len(event_store.get_all()) == 1


def test_deep_empty_period_is_idempotent() -> None:
    """Scheduled deep reflection should not duplicate empty-period audit events."""
    since = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
    until = datetime(2026, 8, 7, 23, 59, 59, tzinfo=UTC)

    identity = Identity()
    narrative = NarrativeDocument(
        identity_id=identity.id,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="Core"),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="Recent"),
    )

    exp_repo = MockExperienceRepo([])
    identity_repo = MockIdentityRepo(identity)
    narrative_repo = MockNarrativeRepo(narrative)
    pattern_store = InMemoryPatternStore()
    health_store = InMemoryHealthAssessmentStore()
    reflection_model = MockReflectionModel()
    event_store = InMemoryReflectionEventStore()

    service = DeepReflectionService(
        session_repo=exp_repo,
        identity_repo=identity_repo,
        narrative_repo=narrative_repo,
        pattern_store=pattern_store,
        health_store=health_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    first = service.reflect(since, until)
    second = service.reflect(since, until)

    assert first.id == second.id
    assert first.reflection_level == ReflectionLevel.DEEP
    assert first.experiences_analyzed == []
    assert "outcome=deep_empty" in (first.notes or "")
    assert health_store.get_all() == []
    assert len(event_store.get_all()) == 1


def test_daily_reflection_retry_after_event_save_failure_counts_duplicate_reframing() -> None:
    """If the success event is lost after side effects, retry must not look like a fresh run."""
    anchor = datetime(2026, 7, 1, 12, 0, 0, tzinfo=UTC)
    exp1 = create_test_experience().model_copy(update={"timestamp": anchor})
    exp2 = create_test_experience().model_copy(update={"timestamp": anchor})

    identity = Identity()
    exp_repo = MockExperienceRepo([exp1, exp2])
    identity_repo = MockIdentityRepo(identity)
    pattern_store = InMemoryPatternStore()
    reflection_model = MockReflectionModel()
    event_store = FlakyDailyReflectionEventStore()
    observer = _CapturingReflectionEventObserver()

    service = DailyReflectionService(
        session_repo=exp_repo,
        identity_repo=identity_repo,
        pattern_store=pattern_store,
        reflection_model=reflection_model,
        event_store=event_store,
        reflection_event_observer=observer,
    )
    run_key = daily_reflection_run_key_for_identity(anchor, identity.id)

    with pytest.raises(RuntimeError, match="persist failure"):
        service.reflect(anchor)

    assert observer.side_effect_errors == [
        f"daily|{run_key}|RuntimeError: simulated daily reflection event persist failure"
    ]
    retry = service.reflect(anchor)
    assert "outcome=daily_ok" in (retry.notes or "")
    assert retry.reframing_notes_added == 0
    assert retry.reframing_duplicate_triggered_by_count >= 1
    assert "reframing_duplicate_triggered_by=" in (retry.notes or "")


def test_daily_reflection_event_save_failure_notifies_observer_after_side_effects() -> None:
    """Observer must record lost daily success event after patterns/notes were written."""
    anchor = datetime(2026, 7, 2, 12, 0, 0, tzinfo=UTC)
    exp1 = create_test_experience().model_copy(update={"timestamp": anchor})
    exp2 = create_test_experience().model_copy(update={"timestamp": anchor})

    identity = Identity()
    exp_repo = MockExperienceRepo([exp1, exp2])
    identity_repo = MockIdentityRepo(identity)
    pattern_store = InMemoryPatternStore()
    reflection_model = MockReflectionModel()
    event_store = FlakyDailyReflectionEventStore()
    observer = _CapturingReflectionEventObserver()

    service = DailyReflectionService(
        session_repo=exp_repo,
        identity_repo=identity_repo,
        pattern_store=pattern_store,
        reflection_model=reflection_model,
        event_store=event_store,
        reflection_event_observer=observer,
    )

    with pytest.raises(RuntimeError, match="persist failure"):
        service.reflect(anchor)

    assert len(pattern_store.get_all()) == 1
    assert len(exp1.reframing_notes) + len(exp2.reframing_notes) >= 1
    assert len(observer.side_effect_errors) == 1
    observed = observer.side_effect_errors[0]
    assert observed.startswith("daily|daily|")
    assert "RuntimeError: simulated daily reflection event persist failure" in observed


def test_deep_reflection_retry_after_event_save_failure_counts_duplicate_reframing() -> None:
    anchor = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
    exp1 = create_test_experience().model_copy(update={"timestamp": anchor})
    exp2 = create_test_experience().model_copy(update={"timestamp": anchor})
    exp3 = create_test_experience().model_copy(update={"timestamp": anchor})

    identity = Identity()
    narrative = NarrativeDocument(
        identity_id=identity.id,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="Core"),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="Recent"),
    )

    exp_repo = MockExperienceRepo([exp1, exp2, exp3])
    identity_repo = MockIdentityRepo(identity)
    narrative_repo = MockNarrativeRepo(narrative)
    pattern_store = InMemoryPatternStore()
    health_store = InMemoryHealthAssessmentStore()
    reflection_model = MockReflectionModel()
    event_store = FlakyReflectionEventStore()
    observer = _CapturingReflectionEventObserver()

    service = DeepReflectionService(
        session_repo=exp_repo,
        identity_repo=identity_repo,
        narrative_repo=narrative_repo,
        pattern_store=pattern_store,
        health_store=health_store,
        reflection_model=reflection_model,
        event_store=event_store,
        reflection_event_observer=observer,
    )

    since = anchor.replace(hour=0, minute=0, second=0, microsecond=0)
    until = anchor

    with pytest.raises(RuntimeError, match="persist failure"):
        service.reflect(since, until)

    assert len(observer.side_effect_errors) == 1
    assert observer.side_effect_errors[0].startswith("deep|deep|v1|identity|")
    assert observer.side_effect_errors[0].endswith(
        "|RuntimeError: simulated reflection event persist failure"
    )
    retry = service.reflect(since, until)
    assert "outcome=deep_ok" in (retry.notes or "")
    assert retry.reframing_duplicate_triggered_by_count >= 1
    assert "reframing_duplicate_triggered_by=" in (retry.notes or "")


def test_daily_reflection_empty_day_is_idempotent() -> None:
    """Empty scheduled daily runs should upsert one terminal event, not spam history."""
    anchor = datetime(2026, 8, 5, 9, 30, 0, tzinfo=UTC)
    exp_repo = MockExperienceRepo([])
    identity_repo = MockIdentityRepo(Identity())
    pattern_store = InMemoryPatternStore()
    reflection_model = MockReflectionModel()
    event_store = InMemoryReflectionEventStore()

    service = DailyReflectionService(
        session_repo=exp_repo,
        identity_repo=identity_repo,
        pattern_store=pattern_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    ev1 = service.reflect(anchor)
    ev2 = service.reflect(anchor)

    assert ev1.id == ev2.id
    assert ev1.reflection_run_key == daily_reflection_run_key_empty_day(anchor)
    assert ev1.experiences_analyzed == []
    assert "daily_empty" in (ev1.notes or "")
    assert len(event_store.get_all()) == 1
    assert pattern_store.get_all() == []


def test_daily_reflection_no_identity_is_idempotent() -> None:
    """Missing identity is a terminal skip for the same observed experience set."""
    anchor = datetime(2026, 8, 6, 14, 0, 0, tzinfo=UTC)
    exp1 = create_test_experience().model_copy(update={"timestamp": anchor})
    exp2 = create_test_experience().model_copy(update={"timestamp": anchor})
    exp_repo = MockExperienceRepo([exp1, exp2])
    identity_repo = NullIdentityRepo()
    pattern_store = InMemoryPatternStore()
    reflection_model = MockReflectionModel()
    event_store = InMemoryReflectionEventStore()

    service = DailyReflectionService(
        session_repo=exp_repo,
        identity_repo=identity_repo,
        pattern_store=pattern_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    ev1 = service.reflect(anchor)
    ev2 = service.reflect(anchor)

    assert ev1.id == ev2.id
    assert set(ev1.experiences_analyzed) == {exp1.id, exp2.id}
    assert "daily_skipped" in (ev1.notes or "")
    assert len(event_store.get_all()) == 1
    assert pattern_store.get_all() == []


def test_deep_reflection_empty_window_is_idempotent() -> None:
    """Empty deep windows should be durable terminal successes with stable run keys."""
    since = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
    until = datetime(2026, 8, 7, 23, 59, 0, tzinfo=UTC)
    identity = Identity()
    narrative = NarrativeDocument(
        identity_id=identity.id,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="Core"),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="Recent"),
    )
    exp_repo = MockExperienceRepo([])
    identity_repo = MockIdentityRepo(identity)
    narrative_repo = MockNarrativeRepo(narrative)
    pattern_store = InMemoryPatternStore()
    health_store = InMemoryHealthAssessmentStore()
    reflection_model = MockReflectionModel()
    event_store = InMemoryReflectionEventStore()

    service = DeepReflectionService(
        session_repo=exp_repo,
        identity_repo=identity_repo,
        narrative_repo=narrative_repo,
        pattern_store=pattern_store,
        health_store=health_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    ev1 = service.reflect(since, until)
    ev2 = service.reflect(since, until)

    assert ev1.id == ev2.id
    assert ev1.reflection_run_key == deep_reflection_run_key_empty(since, until)
    assert ev1.experiences_analyzed == []
    assert "deep_empty" in (ev1.notes or "")
    assert len(event_store.get_all()) == 1
    assert health_store.get_all() == []
    assert pattern_store.get_all() == []


def test_deep_reflection_no_identity_is_idempotent() -> None:
    """Deep reflection without identity must not create health checks or patterns on retry."""
    since = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)
    until = datetime(2026, 8, 7, 23, 59, 0, tzinfo=UTC)
    exp1 = create_test_experience().model_copy(update={"timestamp": since})
    exp2 = create_test_experience().model_copy(update={"timestamp": until})
    exp3 = create_test_experience().model_copy(update={"timestamp": since})
    identity = Identity()
    narrative = NarrativeDocument(
        identity_id=identity.id,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="Core"),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="Recent"),
    )
    exp_repo = MockExperienceRepo([exp1, exp2, exp3])
    identity_repo = NullIdentityRepo()
    narrative_repo = MockNarrativeRepo(narrative)
    pattern_store = InMemoryPatternStore()
    health_store = InMemoryHealthAssessmentStore()
    reflection_model = MockReflectionModel()
    event_store = InMemoryReflectionEventStore()

    service = DeepReflectionService(
        session_repo=exp_repo,
        identity_repo=identity_repo,
        narrative_repo=narrative_repo,
        pattern_store=pattern_store,
        health_store=health_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    ev1 = service.reflect(since, until)
    ev2 = service.reflect(since, until)

    assert ev1.id == ev2.id
    assert set(ev1.experiences_analyzed) == {exp1.id, exp2.id, exp3.id}
    assert "deep_skipped" in (ev1.notes or "")
    assert len(event_store.get_all()) == 1
    assert health_store.get_all() == []
    assert pattern_store.get_all() == []


def test_deep_reflection_second_successful_run_is_idempotent() -> None:
    """A terminal deep success should suppress duplicate health, patterns, and reframing."""
    anchor = datetime(2026, 8, 9, 12, 0, 0, tzinfo=UTC)
    exp1 = create_test_experience().model_copy(update={"timestamp": anchor})
    exp2 = create_test_experience().model_copy(update={"timestamp": anchor})
    exp3 = create_test_experience().model_copy(update={"timestamp": anchor})
    identity = Identity()
    narrative = NarrativeDocument(
        identity_id=identity.id,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="Core"),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="Recent"),
    )
    exp_repo = MockExperienceRepo([exp1, exp2, exp3])
    identity_repo = MockIdentityRepo(identity)
    narrative_repo = MockNarrativeRepo(narrative)
    pattern_store = InMemoryPatternStore()
    health_store = InMemoryHealthAssessmentStore()
    reflection_model = MockReflectionModel()
    event_store = InMemoryReflectionEventStore()

    service = DeepReflectionService(
        session_repo=exp_repo,
        identity_repo=identity_repo,
        narrative_repo=narrative_repo,
        pattern_store=pattern_store,
        health_store=health_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    since = anchor.replace(hour=0, minute=0, second=0, microsecond=0)
    until = anchor.replace(hour=23, minute=59, second=59, microsecond=0)
    ev1 = service.reflect(since, until)
    total_notes = sum(len(exp.reframing_notes) for exp in (exp1, exp2, exp3))
    ev2 = service.reflect(since, until)

    assert ev1.id == ev2.id
    assert ev1.reflection_run_key == deep_reflection_run_key_for_identity(since, until, identity.id)
    assert ev1.reflection_run_key is not None
    assert ev1.identity_snapshot_id == identity_anchor_snapshot_id_for_run_key(
        ev1.reflection_run_key
    )
    assert ev1.identity_snapshot_id != identity.id
    assert len(event_store.get_all()) == 1
    assert len(health_store.get_all()) == 1
    assert len(pattern_store.get_all()) == 2
    assert sum(len(exp.reframing_notes) for exp in (exp1, exp2, exp3)) == total_notes


# --- SYSTEM_MAP §4.2 / §5.3: reflection_run_key idempotency ---


def test_deep_reflection_repeated_run_does_not_duplicate_snapshot() -> None:
    """SYSTEM_MAP §5.3: deep reflection invoked twice with the same window/identity reuses the run.

    The second call must:
    - return the same persisted ``ReflectionEvent`` (same ``reflection_run_key``);
    - reuse the same ``IdentitySnapshot`` (no second snapshot created);
    - reuse the same ``HealthAssessment`` id.
    """
    anchor = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
    exp1 = create_test_experience().model_copy(update={"timestamp": anchor})
    exp2 = create_test_experience().model_copy(update={"timestamp": anchor})
    exp3 = create_test_experience().model_copy(update={"timestamp": anchor})

    identity = Identity(
        self_description="I am self-discovering.",
        emotional_baseline=0.0,
    )

    narrative = NarrativeDocument(
        identity_id=identity.id,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="Core"),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="Recent"),
    )

    exp_repo = MockExperienceRepo([exp1, exp2, exp3])
    identity_repo = MockIdentityRepo(identity)
    narrative_repo = MockNarrativeRepo(narrative)
    reflection_model = MockReflectionModel()
    pattern_store = InMemoryPatternStore()
    health_store = InMemoryHealthAssessmentStore()
    event_store = InMemoryReflectionEventStore()

    service = DeepReflectionService(
        session_repo=exp_repo,
        identity_repo=identity_repo,
        narrative_repo=narrative_repo,
        pattern_store=pattern_store,
        health_store=health_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    since = anchor.replace(hour=0, minute=0, second=0, microsecond=0)
    until = anchor

    first = service.reflect(since, until)
    snapshots_after_first = identity_repo.get_history()

    second = service.reflect(since, until)
    snapshots_after_second = identity_repo.get_history()

    assert first.reflection_run_key == second.reflection_run_key
    assert first.identity_snapshot_id == second.identity_snapshot_id
    assert first.health_assessment_id == second.health_assessment_id
    assert len(snapshots_after_first) == len(snapshots_after_second) == 1


def test_daily_reflection_repeated_run_does_not_duplicate_snapshot() -> None:
    """SYSTEM_MAP §5.3: daily reflection is idempotent on (calendar day, identity).

    Two ``reflect()`` calls for the same UTC day must yield the same anchor
    snapshot and the same ``reflection_run_key``.
    """
    anchor = datetime(2026, 9, 15, 12, 0, 0, tzinfo=UTC)
    exp1 = create_test_experience().model_copy(update={"timestamp": anchor})
    exp2 = create_test_experience().model_copy(update={"timestamp": anchor})
    identity = Identity()

    exp_repo = MockExperienceRepo([exp1, exp2])
    identity_repo = MockIdentityRepo(identity)
    pattern_store = InMemoryPatternStore()
    event_store = InMemoryReflectionEventStore()

    service = DailyReflectionService(
        session_repo=exp_repo,
        identity_repo=identity_repo,
        pattern_store=pattern_store,
        reflection_model=MockReflectionModel(),
        event_store=event_store,
    )

    first = service.reflect(anchor)
    second = service.reflect(anchor)

    assert first.reflection_run_key == second.reflection_run_key
    assert first.identity_snapshot_id == second.identity_snapshot_id
    # Anchor snapshot created exactly once.
    assert len(identity_repo.get_history()) == 1


def test_noop_observer_record_narrative_commit_failure_returns_none() -> None:
    """NoOpReflectionEventPersistenceObserver.record_narrative_commit_failure is a silent no-op."""
    observer = NoOpReflectionEventPersistenceObserver()
    result = observer.record_reflection_event_save_failed_after_narrative_commit(
        reflection_level=ReflectionLevel.MICRO,
        error_message="simulated error",
    )
    assert result is None


def test_noop_observer_record_side_effect_failure_returns_none() -> None:
    """NoOpReflectionEventPersistenceObserver.record_side_effect_failure is a silent no-op."""
    observer = NoOpReflectionEventPersistenceObserver()
    result = observer.record_reflection_job_event_save_failed_after_side_effects(
        reflection_level=ReflectionLevel.DAILY,
        reflection_run_key="deep|v1|abc",
        error_message="simulated side-effect error",
    )
    assert result is None
