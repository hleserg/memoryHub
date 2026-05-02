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


def test_generate_reframing_note_with_patterns() -> None:
    """Test generating reframing note with patterns."""
    model = MockReflectionModel()
    exp = SessionExperience(
        session_id=_SID,
        key_moments=[
            KeyMoment(
                what_happened="Test",
                how_i_felt=FeltSense(
                    emotional_valence=0.3, emotional_intensity=0.6, depth=EmotionalDepth.MEANINGFUL
                ),
                why_it_matters="Test",
            )
        ],
    )

    note = model.generate_reframing_note(exp, {"patterns": "test pattern"})
    assert "pattern" in note.lower()


def test_generate_reframing_note_without_patterns() -> None:
    """Test generating reframing note without patterns."""
    model = MockReflectionModel()
    exp = SessionExperience(
        session_id=_SID,
        key_moments=[
            KeyMoment(
                what_happened="Test",
                how_i_felt=FeltSense(
                    emotional_valence=0.3, emotional_intensity=0.6, depth=EmotionalDepth.MEANINGFUL
                ),
                why_it_matters="Test",
            )
        ],
    )

    note = model.generate_reframing_note(exp, {})
    assert len(note) > 0


def test_detect_pattern_positive() -> None:
    """Test detecting positive pattern."""
    model = MockReflectionModel()

    experiences = [
        SessionExperience(
            session_id=_SID,
            key_moments=[
                KeyMoment(
                    what_happened="Test",
                    how_i_felt=FeltSense(
                        emotional_valence=0.5,
                        emotional_intensity=0.6,
                        depth=EmotionalDepth.MEANINGFUL,
                    ),
                    why_it_matters="Test",
                )
            ],
        ),
        SessionExperience(
            session_id=_SID2,
            key_moments=[
                KeyMoment(
                    what_happened="Test 2",
                    how_i_felt=FeltSense(
                        emotional_valence=0.6,
                        emotional_intensity=0.7,
                        depth=EmotionalDepth.MEANINGFUL,
                    ),
                    why_it_matters="Test",
                )
            ],
        ),
    ]

    pattern = model.detect_pattern(experiences, {})
    assert "positive" in pattern.lower() or "curiosity" in pattern.lower()


def test_detect_pattern_negative() -> None:
    """Test detecting negative pattern."""
    model = MockReflectionModel()

    experiences = [
        SessionExperience(
            session_id=_SID,
            key_moments=[
                KeyMoment(
                    what_happened="Test",
                    how_i_felt=FeltSense(
                        emotional_valence=-0.5,
                        emotional_intensity=0.6,
                        depth=EmotionalDepth.MEANINGFUL,
                    ),
                    why_it_matters="Test",
                )
            ],
        ),
        SessionExperience(
            session_id=_SID2,
            key_moments=[
                KeyMoment(
                    what_happened="Test 2",
                    how_i_felt=FeltSense(
                        emotional_valence=-0.6,
                        emotional_intensity=0.7,
                        depth=EmotionalDepth.MEANINGFUL,
                    ),
                    why_it_matters="Test",
                )
            ],
        ),
    ]

    pattern = model.detect_pattern(experiences, {})
    assert "uncertain" in pattern.lower() or "concerned" in pattern.lower()


def test_detect_pattern_single_experience() -> None:
    """Test that pattern detection requires multiple experiences."""
    model = MockReflectionModel()

    exp = SessionExperience(
        session_id=_SID,
        key_moments=[
            KeyMoment(
                what_happened="Test",
                how_i_felt=FeltSense(
                    emotional_valence=0.5, emotional_intensity=0.6, depth=EmotionalDepth.MEANINGFUL
                ),
                why_it_matters="Test",
            )
        ],
    )

    pattern = model.detect_pattern([exp], {})
    assert pattern == ""


def test_propose_narrative_update_micro() -> None:
    """Test proposing narrative update for micro reflection."""
    model = MockReflectionModel()

    identity = Identity()
    narrative = NarrativeDocument(
        identity_id=identity.id,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="Core"),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="Recent"),
    )

    exp = SessionExperience(
        session_id=_SID,
        key_moments=[
            KeyMoment(
                what_happened="Test event",
                how_i_felt=FeltSense(
                    emotional_valence=0.5, emotional_intensity=0.6, depth=EmotionalDepth.MEANINGFUL
                ),
                why_it_matters="Test importance",
            )
        ],
    )

    update = model.propose_narrative_update(narrative, [exp], ReflectionLevel.MICRO)
    assert "session" in update.lower()


def test_assess_health_all_criteria() -> None:
    """Test assessing all health criteria."""
    model = MockReflectionModel()

    identity = Identity(
        self_description="Test",
        goals=[Goal(content="Test goal")],
        principles=[Principle(statement="Test principle", chosen_consciously=True)],
        habits=[Habit(statement="Test habit", helpfulness=HelpfulnessLevel.HELPFUL)],
    )

    experiences = [
        SessionExperience(
            session_id=_SID,
            key_moments=[
                KeyMoment(
                    what_happened="Test",
                    how_i_felt=FeltSense(
                        emotional_valence=0.5,
                        emotional_intensity=0.6,
                        depth=EmotionalDepth.MEANINGFUL,
                    ),
                    why_it_matters="Test",
                )
            ],
        )
    ]

    for criterion in JahodaCriterion:
        score, evidence, concerns = model.assess_health_criterion(
            identity, experiences, criterion
        )

        assert 0.0 <= score <= 1.0
        assert isinstance(evidence, list)
        assert isinstance(concerns, list)


def test_assess_health_positive_self_attitude() -> None:
    """Test positive self-attitude assessment."""
    model = MockReflectionModel()

    identity = Identity(self_description="I am learning")

    score, evidence, _concerns = model.assess_health_criterion(
        identity, [], JahodaCriterion.POSITIVE_SELF_ATTITUDE
    )

    assert score >= 0.5
    assert len(evidence) > 0


def test_assess_health_growth() -> None:
    """Test growth assessment."""
    model = MockReflectionModel()

    identity = Identity(goals=[Goal(content="Learn more")])

    score, evidence, _concerns = model.assess_health_criterion(
        identity, [], JahodaCriterion.GROWTH_AND_ACTUALIZATION
    )

    assert score >= 0.5
    assert "goal" in " ".join(evidence).lower()


def test_assess_health_integration() -> None:
    """Test integration assessment."""
    model = MockReflectionModel()

    identity = Identity(
        principles=[Principle(statement="Be honest")],
        habits=[Habit(statement="Usually honest")],
    )

    score, _evidence, _concerns = model.assess_health_criterion(
        identity, [], JahodaCriterion.INTEGRATION
    )

    assert score >= 0.5


def test_assess_health_autonomy() -> None:
    """Test autonomy assessment."""
    model = MockReflectionModel()

    identity = Identity(principles=[Principle(statement="My choice", chosen_consciously=True)])

    score, _evidence, _concerns = model.assess_health_criterion(
        identity, [], JahodaCriterion.AUTONOMY
    )

    assert score >= 0.5
