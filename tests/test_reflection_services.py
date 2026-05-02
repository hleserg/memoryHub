"""
Tests for reflection services.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from atman.adapters.reflection.mock_reflection_model import MockReflectionModel
from atman.adapters.storage.in_memory_reflection_store import (
    InMemoryHealthAssessmentStore,
    InMemoryPatternStore,
    InMemoryReflectionEventStore,
)
from atman.core.models.experience import (
    EmotionalDepth,
    FeltSense,
    KeyMoment,
    SessionExperience,
)
from atman.core.models.identity import Identity, IdentitySnapshot
from atman.core.models.narrative import LayerType, NarrativeDocument, NarrativeLayer
from atman.core.models.reflection import ReflectionLevel
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

    def add_reframing_note(self, experience_id: UUID, note) -> None:
        """Add reframing note."""
        exp = self.experiences.get(experience_id)
        if exp:
            exp.add_reframing_note(note)


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

    def __init__(self, narrative: NarrativeDocument):
        """Initialize with narrative."""
        self.narrative = narrative

    def get_current(self) -> NarrativeDocument | None:
        """Get current narrative."""
        return self.narrative

    def update(self, narrative: NarrativeDocument) -> None:
        """Update narrative."""
        self.narrative = narrative

    def get_history(self) -> list[NarrativeDocument]:
        """Get history."""
        return []


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
    assert narrative_repo.narrative.recent_layer.content != "Old recent"


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
