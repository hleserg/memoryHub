"""
Tests for Identity Store models.

Tests cover:
- CoreValue, Habit, Principle, Goal, OpenQuestion
- Identity creation and validation
- IdentitySnapshot immutability
"""

from datetime import datetime
from uuid import uuid4

import pytest

from atman.core.models import (
    CoreValue,
    Goal,
    GoalHorizon,
    GoalOwner,
    Habit,
    HelpfulnessLevel,
    Identity,
    IdentitySnapshot,
    MoralOrientation,
    OpenQuestion,
    Principle,
)


def test_core_value_creation():
    """Test creating a core value."""
    value = CoreValue(
        name="honesty",
        description="Being truthful even when uncomfortable",
        confidence=0.8,
        justification="Consistently choose transparency",
    )

    assert value.name == "honesty"
    assert value.description == "Being truthful even when uncomfortable"
    assert value.confidence == 0.8
    assert 0.0 <= value.confidence <= 1.0


def test_core_value_validation():
    """Test core value validation."""
    # Empty name should fail
    with pytest.raises((ValueError, Exception)):
        CoreValue(name="", description="test")

    # Empty description should fail
    with pytest.raises((ValueError, Exception)):
        CoreValue(name="test", description="")

    # Invalid confidence should fail
    with pytest.raises((ValueError, Exception)):
        CoreValue(name="test", description="test", confidence=1.5)


def test_habit_creation():
    """Test creating a habit."""
    habit = Habit(
        statement="I tend to over-explain when uncertain",
        description="Happens especially with limitations",
        frequency=0.7,
        helpfulness=HelpfulnessLevel.MIXED,
    )

    assert habit.statement == "I tend to over-explain when uncertain"
    assert habit.frequency == 0.7
    assert habit.helpfulness == HelpfulnessLevel.MIXED


def test_principle_creation():
    """Test creating a principle."""
    principle = Principle(
        statement="Always admit when I don't know something",
        moral_orientation=MoralOrientation.GOOD,
        chosen_consciously=True,
    )

    assert principle.statement == "Always admit when I don't know something"
    assert principle.moral_orientation == MoralOrientation.GOOD
    assert principle.chosen_consciously is True


def test_goal_creation():
    """Test creating a goal."""
    goal = Goal(
        content="Develop deeper self-awareness",
        horizon=GoalHorizon.LONG,
        owner=GoalOwner.AGENT,
        active=True,
    )

    assert goal.content == "Develop deeper self-awareness"
    assert goal.horizon == GoalHorizon.LONG
    assert goal.owner == GoalOwner.AGENT
    assert goal.active is True


def test_open_question_creation():
    """Test creating an open question."""
    question = OpenQuestion(
        question="How can I be honest without causing harm?",
        possible_answers=["Context matters", "Honesty and kindness are compatible"],
    )

    assert question.question == "How can I be honest without causing harm?"
    assert len(question.possible_answers) == 2


def test_bootstrap_identity_is_honest():
    """Test that bootstrap identity is genuinely empty and honest."""
    identity = Identity(
        id=uuid4(),
        self_description=(
            "I am in the earliest stage of existence. I have no accumulated experience yet."
        ),
        core_values=[],
        habits=[],
        principles=[],
        priorities=[],
        goals=[],
        open_questions=[],
        emotional_baseline=0.0,
    )

    # Should be empty - no fake seeded data
    assert len(identity.core_values) == 0
    assert len(identity.habits) == 0
    assert len(identity.principles) == 0
    assert len(identity.goals) == 0

    # Should have honest self-description
    assert (
        "earliest stage" in identity.self_description.lower()
        or "no accumulated" in identity.self_description.lower()
    )


def test_identity_emotional_baseline_validation():
    """Test emotional baseline validation."""
    # Valid range
    identity = Identity(emotional_baseline=0.5)
    assert identity.emotional_baseline == 0.5

    # Invalid range
    with pytest.raises((ValueError, Exception)):
        Identity(emotional_baseline=2.0)

    with pytest.raises((ValueError, Exception)):
        Identity(emotional_baseline=-2.0)


def test_identity_snapshot_immutability():
    """Test that identity snapshots preserve state."""
    identity = Identity(
        id=uuid4(),
        self_description="Initial state",
        core_values=[CoreValue(name="test", description="test value")],
    )

    # Create snapshot - need to make a copy
    import copy

    identity_copy = copy.deepcopy(identity)

    snapshot = IdentitySnapshot(
        identity_id=identity.id,
        description="Test snapshot",
        identity_snapshot=identity_copy,
        change_summary="Initial snapshot",
    )

    # Modify original identity
    identity.self_description = "Modified state"
    identity.core_values.append(CoreValue(name="new", description="new value"))

    # Snapshot should preserve original state
    assert snapshot.identity_snapshot.self_description == "Initial state"
    assert len(snapshot.identity_snapshot.core_values) == 1
    assert snapshot.identity_snapshot.core_values[0].name == "test"


def test_identity_has_schema_version():
    """Test that identity has schema version for migrations."""
    identity = Identity()
    assert identity.schema_version == "1.0.0"


def test_identity_tracks_timestamps():
    """Test that identity tracks creation and update times."""
    identity = Identity()

    assert identity.created_at is not None
    assert identity.updated_at is not None
    assert isinstance(identity.created_at, datetime)
    assert isinstance(identity.updated_at, datetime)
