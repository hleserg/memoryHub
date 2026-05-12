"""
Tests for mock reflection model.
"""

from uuid import UUID

from atman.adapters.reflection.mock_reflection_model import MockReflectionModel
from atman.core.models.experience import (
    EmotionalDepth,
    FeltSense,
    KeyMoment,
    SessionExperience,
)
from atman.core.models.identity import Goal, Habit, HelpfulnessLevel, Identity, Principle
from atman.core.models.narrative import LayerType, NarrativeDocument, NarrativeLayer
from atman.core.models.reflection import JahodaCriterion, ReflectionLevel

_SID = UUID("123e4567-e89b-12d3-a456-426614174000")
_SID2 = UUID("223e4567-e89b-12d3-a456-426614174000")


def _exp(session_id: UUID, km: KeyMoment) -> SessionExperience:
    return SessionExperience(
        session_id=session_id,
        key_moment_ids=[km.id],
        avg_emotional_intensity=km.how_i_felt.emotional_intensity,
        has_profound_moment=km.how_i_felt.depth == EmotionalDepth.PROFOUND,
    )


def _km(
    what: str = "Test",
    *,
    valence: float = 0.3,
    intensity: float = 0.6,
    depth: EmotionalDepth = EmotionalDepth.MEANINGFUL,
    why: str = "Test",
) -> KeyMoment:
    return KeyMoment(
        what_happened=what,
        how_i_felt=FeltSense(
            emotional_valence=valence,
            emotional_intensity=intensity,
            depth=depth,
        ),
        why_it_matters=why,
    )


def test_generate_reframing_note_with_patterns() -> None:
    """Test generating reframing note with patterns."""
    model = MockReflectionModel()
    exp = _exp(_SID, _km())
    out = model.generate_reframing_note(exp, {"patterns": "test pattern"})
    assert "pattern" in out.reflection.lower()


def test_generate_reframing_note_without_patterns() -> None:
    """Test generating reframing note without patterns."""
    model = MockReflectionModel()
    exp = _exp(_SID, _km())
    out = model.generate_reframing_note(exp, {})
    assert len(out.reflection) > 0


def test_detect_pattern_positive() -> None:
    """Test detecting positive pattern."""
    model = MockReflectionModel()

    experiences = [
        _exp(_SID, _km(valence=0.5, intensity=0.9, depth=EmotionalDepth.PROFOUND)),
        _exp(_SID2, _km(what="Test 2", valence=0.6, intensity=0.95, depth=EmotionalDepth.PROFOUND)),
    ]

    detection = model.detect_pattern(experiences, {})
    desc = detection.description
    assert "positive" in desc.lower() or "curiosity" in desc.lower()


def test_detect_pattern_negative() -> None:
    """Test detecting negative pattern (low arousal → negative valence estimate in mock)."""
    model = MockReflectionModel()

    experiences = [
        _exp(_SID, _km(valence=-0.5, intensity=0.2, depth=EmotionalDepth.PROFOUND)),
        _exp(
            _SID2, _km(what="Test 2", valence=-0.6, intensity=0.15, depth=EmotionalDepth.PROFOUND)
        ),
    ]

    detection = model.detect_pattern(experiences, {})
    desc = detection.description
    assert "uncertain" in desc.lower() or "concerned" in desc.lower()


def test_detect_pattern_single_experience() -> None:
    """Test that pattern detection requires multiple experiences."""
    model = MockReflectionModel()

    exp = _exp(_SID, _km(valence=0.5, intensity=0.6))
    detection = model.detect_pattern([exp], {})
    assert detection.description == ""


def test_propose_narrative_update_micro() -> None:
    """Test proposing narrative update for micro reflection."""
    model = MockReflectionModel()

    identity = Identity()
    narrative = NarrativeDocument(
        identity_id=identity.id,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="Core"),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="Recent"),
    )

    exp = _exp(
        _SID,
        _km(what="Test event", why="Test importance"),
    )

    proposed = model.propose_narrative_update(narrative, [exp], ReflectionLevel.MICRO)
    assert "session" in proposed.body.lower()


def test_assess_health_all_criteria() -> None:
    """Test assessing all health criteria."""
    model = MockReflectionModel()

    identity = Identity(
        self_description="Test",
        goals=[Goal(content="Test goal")],
        principles=[Principle(statement="Test principle", chosen_consciously=True)],
        habits=[Habit(statement="Test habit", helpfulness=HelpfulnessLevel.HELPFUL)],
    )

    experiences = [_exp(_SID, _km(valence=0.5, intensity=0.6))]

    for criterion in JahodaCriterion:
        hc = model.assess_health_criterion(identity, experiences, criterion)

        assert 0.0 <= hc.score <= 1.0
        assert isinstance(hc.evidence, list)
        assert isinstance(hc.concerns, list)


def test_assess_health_positive_self_attitude() -> None:
    """Test positive self-attitude assessment."""
    model = MockReflectionModel()

    identity = Identity(self_description="I am learning")

    hc = model.assess_health_criterion(identity, [], JahodaCriterion.POSITIVE_SELF_ATTITUDE)

    assert hc.score >= 0.5
    assert len(hc.evidence) > 0


def test_assess_health_growth() -> None:
    """Test growth assessment."""
    model = MockReflectionModel()

    identity = Identity(goals=[Goal(content="Learn more")])

    hc = model.assess_health_criterion(identity, [], JahodaCriterion.GROWTH_AND_ACTUALIZATION)

    assert hc.score >= 0.5
    assert "goal" in " ".join(hc.evidence).lower()


def test_assess_health_integration() -> None:
    """Test integration assessment."""
    model = MockReflectionModel()

    identity = Identity(
        principles=[Principle(statement="Be honest")],
        habits=[Habit(statement="Usually honest")],
    )

    hc = model.assess_health_criterion(identity, [], JahodaCriterion.INTEGRATION)

    assert hc.score >= 0.5


def test_assess_health_autonomy() -> None:
    """Test autonomy assessment."""
    model = MockReflectionModel()

    identity = Identity(principles=[Principle(statement="My choice", chosen_consciously=True)])

    hc = model.assess_health_criterion(identity, [], JahodaCriterion.AUTONOMY)

    assert hc.score >= 0.5
