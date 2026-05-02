"""
Tests for reflection services.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

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
    SessionExperience,
)
from atman.core.models.identity import Identity, IdentitySnapshot
from atman.core.models.narrative import LayerType, NarrativeDocument, NarrativeLayer
from atman.core.models.reflection import ReflectionEvent, ReflectionLevel
from atman.core.services.reflection_service import (
    DailyReflectionService,
    DeepReflectionService,
    MicroReflectionService,
)


class MockExperienceRepo:
    """Mock experience repository."""

    def __init__(self, experiences: list[SessionExperience]):
        """Initialize with experiences."""
        self.experiences = {exp.id: exp for exp in experiences}

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

    def add_reframing_note(self, experience_id: UUID, note: ReframingNote) -> bool:
        """Add reframing note; return True if the experience existed."""
        exp = self.experiences.get(experience_id)
        if exp is None:
            return False
        exp.add_reframing_note(note)
        return True


class MockIdentityRepo:
    """Mock identity repository."""

    def __init__(self, identity: Identity):
        """Initialize with identity."""
        self.identity = identity

    def get_current(self) -> Identity | None:
        """Get current identity."""
        return self.identity

    def get_snapshot(self, snapshot_id: UUID) -> IdentitySnapshot | None:
        """Get snapshot."""
        return None

    def get_history(self) -> list[IdentitySnapshot]:
        """Get history."""
        return []

    def update(self, identity: Identity) -> None:
        """Update identity."""
        self.identity = identity

    def create_snapshot(
        self, identity: Identity, description: str, change_summary: str
    ) -> IdentitySnapshot:
        """Create snapshot."""
        return IdentitySnapshot(
            identity_id=identity.id,
            identity_snapshot=identity,
            description=description,
            change_summary=change_summary,
        )


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
        self, identity: Identity, description: str, change_summary: str
    ) -> IdentitySnapshot:
        return IdentitySnapshot(
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


class RejectingReframeMockRepo(MockExperienceRepo):
    """Experience repo that never persists reframing notes (audit edge case)."""

    def add_reframing_note(self, experience_id: UUID, note: ReframingNote) -> bool:
        return False


def create_test_experience(session_id: UUID | None = None) -> SessionExperience:
    """Create a test experience."""
    if session_id is None:
        session_id = uuid4()

    return SessionExperience(
        session_id=session_id,
        key_moments=[
            KeyMoment(
                what_happened="Test event",
                how_i_felt=FeltSense(
                    emotional_valence=0.3,
                    emotional_intensity=0.6,
                    depth=EmotionalDepth.MEANINGFUL,
                ),
                why_it_matters="Test importance",
                values_touched=["test_value"],
            )
        ],
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

    service = MicroReflectionService(
        experience_repo=exp_repo,
        narrative_repo=narrative_repo,
        reflection_model=reflection_model,
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

    service = MicroReflectionService(
        experience_repo=exp_repo,
        narrative_repo=narrative_repo,
        reflection_model=reflection_model,
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

    service = MicroReflectionService(
        experience_repo=exp_repo,
        narrative_repo=narrative_repo,
        reflection_model=reflection_model,
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

    service = MicroReflectionService(
        experience_repo=exp_repo,
        narrative_repo=narrative_repo,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    event = service.reflect(session_id)

    assert event.reflection_level == ReflectionLevel.MICRO
    assert event.experiences_analyzed == [exp.id]
    assert "no current narrative" in event.key_insight.lower()
    assert "no_narrative" in event.notes


def test_daily_reflection_detects_patterns() -> None:
    """Test that daily reflection detects patterns."""
    exp1 = create_test_experience()
    exp2 = create_test_experience()

    identity = Identity()

    exp_repo = MockExperienceRepo([exp1, exp2])
    identity_repo = MockIdentityRepo(identity)
    pattern_store = InMemoryPatternStore()
    reflection_model = MockReflectionModel()
    event_store = InMemoryReflectionEventStore()

    service = DailyReflectionService(
        experience_repo=exp_repo,
        identity_repo=identity_repo,
        pattern_store=pattern_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    date = datetime.now(UTC)
    event = service.reflect(date)

    assert event.reflection_level == ReflectionLevel.DAILY
    assert len(event.experiences_analyzed) == 2


def test_daily_reflection_adds_reframing_notes() -> None:
    """Test that daily reflection can add reframing notes."""
    exp1 = create_test_experience()
    exp2 = create_test_experience()

    identity = Identity()

    exp_repo = MockExperienceRepo([exp1, exp2])
    identity_repo = MockIdentityRepo(identity)
    pattern_store = InMemoryPatternStore()
    reflection_model = MockReflectionModel()
    event_store = InMemoryReflectionEventStore()

    service = DailyReflectionService(
        experience_repo=exp_repo,
        identity_repo=identity_repo,
        pattern_store=pattern_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    date = datetime.now(UTC)
    event = service.reflect(date)

    assert event.reflection_level == ReflectionLevel.DAILY
    assert event.reframing_notes_added >= 1


def test_daily_reflection_reframing_count_skips_failed_persist() -> None:
    """Reframing count must not increase when the repo rejects the append."""
    exp1 = create_test_experience()
    exp2 = create_test_experience()

    identity = Identity()

    exp_repo = RejectingReframeMockRepo([exp1, exp2])
    identity_repo = MockIdentityRepo(identity)
    pattern_store = InMemoryPatternStore()
    reflection_model = MockReflectionModel()
    event_store = InMemoryReflectionEventStore()

    service = DailyReflectionService(
        experience_repo=exp_repo,
        identity_repo=identity_repo,
        pattern_store=pattern_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    event = service.reflect(datetime.now(UTC))

    assert event.reflection_level == ReflectionLevel.DAILY
    assert len(event.patterns_detected) >= 1
    assert event.reframing_notes_added == 0


def test_deep_reflection_performs_health_assessment() -> None:
    """Test that deep reflection performs health assessment."""
    exp1 = create_test_experience()
    exp2 = create_test_experience()
    exp3 = create_test_experience()

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
        experience_repo=exp_repo,
        identity_repo=identity_repo,
        narrative_repo=narrative_repo,
        pattern_store=pattern_store,
        health_store=health_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    since = datetime.now(UTC).replace(hour=0, minute=0)
    until = datetime.now(UTC)

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
    exp1 = create_test_experience()
    exp2 = create_test_experience()
    exp3 = create_test_experience()

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
        experience_repo=exp_repo,
        identity_repo=identity_repo,
        narrative_repo=narrative_repo,
        pattern_store=pattern_store,
        health_store=health_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    since = datetime.now(UTC).replace(hour=0, minute=0)
    until = datetime.now(UTC)

    event = service.reflect(since, until)

    assert event.reflection_level == ReflectionLevel.DEEP
    assert event.narrative_changes_proposed != ""
    assert event.identity_changes_proposed != ""
    assert event.reframing_notes_added >= 1
    assert any(len(e.reframing_notes) > 0 for e in (exp1, exp2, exp3))


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
        experience_repo=exp_repo,
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
    exp1 = create_test_experience()
    exp2 = create_test_experience()

    exp_repo = MockExperienceRepo([exp1, exp2])
    identity_repo = NullIdentityRepo()
    pattern_store = InMemoryPatternStore()
    reflection_model = MockReflectionModel()
    event_store = InMemoryReflectionEventStore()

    service = DailyReflectionService(
        experience_repo=exp_repo,
        identity_repo=identity_repo,
        pattern_store=pattern_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    event = service.reflect(datetime.now(UTC))

    assert event.reflection_level == ReflectionLevel.DAILY
    assert set(event.experiences_analyzed) == {exp1.id, exp2.id}
    assert "no_identity" in event.notes
    assert "daily_skipped" in event.notes
    assert "no experiences" not in event.key_insight.lower()


def test_deep_reflection_skipped_no_identity_preserves_experience_ids() -> None:
    exp1 = create_test_experience()
    exp2 = create_test_experience()
    exp3 = create_test_experience()

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
        experience_repo=exp_repo,
        identity_repo=identity_repo,
        narrative_repo=narrative_repo,
        pattern_store=pattern_store,
        health_store=health_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    since = datetime.now(UTC).replace(hour=0, minute=0)
    until = datetime.now(UTC)
    event = service.reflect(since, until)

    assert event.reflection_level == ReflectionLevel.DEEP
    assert set(event.experiences_analyzed) == {exp1.id, exp2.id, exp3.id}
    assert "no_identity" in event.notes
    assert "deep_skipped" in event.notes
    assert health_store.get_all() == []


def test_deep_reflection_persist_failure_links_health_assessment() -> None:
    """If success event persistence fails after health is stored, emit a failed run event."""
    exp1 = create_test_experience()
    exp2 = create_test_experience()
    exp3 = create_test_experience()

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

    service = DeepReflectionService(
        experience_repo=exp_repo,
        identity_repo=identity_repo,
        narrative_repo=narrative_repo,
        pattern_store=pattern_store,
        health_store=health_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    since = datetime.now(UTC).replace(hour=0, minute=0)
    until = datetime.now(UTC)

    with pytest.raises(RuntimeError, match="persist failure"):
        service.reflect(since, until)

    assert len(health_store.get_all()) == 1
    stored_events = event_store.get_all()
    assert len(stored_events) == 1
    failed = stored_events[0]
    assert "deep_failed" in failed.notes
    assert failed.health_assessment_id is not None
    assert failed.health_assessment_id == health_store.get_all()[0].id
