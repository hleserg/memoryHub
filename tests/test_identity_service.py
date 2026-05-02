"""
Tests for Identity Service.

Tests cover:
- Bootstrap creates honest empty identity
- No fake seeded principles or values
- Snapshots are created on significant changes
- Identity updates work correctly
"""

from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from atman.adapters.storage import FileStateStore
from atman.core.models import CoreValue, Goal, GoalHorizon, Habit, OpenQuestion, Principle
from atman.core.services import IdentityService


def test_bootstrap_creates_honest_empty_identity():
    """Test that bootstrap creates genuinely empty identity."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = IdentityService(store)

        agent_id = uuid4()
        identity = service.bootstrap_identity(agent_id)

        # Should be empty - no fake data
        assert len(identity.core_values) == 0
        assert len(identity.habits) == 0
        assert len(identity.principles) == 0
        assert len(identity.goals) == 0

        # Should have honest self-description
        assert (
            "earliest stage" in identity.self_description.lower()
            or "no accumulated" in identity.self_description.lower()
        )

        # Should have open questions about self
        assert len(identity.open_questions) > 0
        assert any("become" in q.question.lower() for q in identity.open_questions)


def test_bootstrap_creates_initial_snapshot():
    """Test that bootstrap creates initial snapshot."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = IdentityService(store)

        agent_id = uuid4()
        service.bootstrap_identity(agent_id)

        # Check snapshot was created
        snapshots = service.list_snapshots(agent_id)
        assert len(snapshots) == 1
        assert "bootstrap" in snapshots[0].description.lower()


def test_get_identity():
    """Test getting identity."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = IdentityService(store)

        agent_id = uuid4()
        service.bootstrap_identity(agent_id)

        # Get identity
        identity = service.get_identity(agent_id)
        assert identity is not None
        assert identity.id == agent_id


def test_add_core_value_creates_snapshot():
    """Test that adding core value creates snapshot."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = IdentityService(store)

        agent_id = uuid4()
        service.bootstrap_identity(agent_id)

        # Add value
        value = CoreValue(
            name="honesty",
            description="Being truthful",
            confidence=0.8,
        )
        updated = service.add_core_value(agent_id, value)

        assert len(updated.core_values) == 1
        assert updated.core_values[0].name == "honesty"

        # Should have created snapshot
        snapshots = service.list_snapshots(agent_id)
        assert len(snapshots) == 2  # Bootstrap + value addition
        assert "honesty" in snapshots[0].description.lower()


def test_add_habit():
    """Test adding habit."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = IdentityService(store)

        agent_id = uuid4()
        service.bootstrap_identity(agent_id)

        # Add habit
        habit = Habit(
            statement="I tend to over-explain",
            frequency=0.7,
        )
        updated = service.add_habit(agent_id, habit)

        assert len(updated.habits) == 1
        assert updated.habits[0].statement == "I tend to over-explain"


def test_add_principle_creates_snapshot():
    """Test that adding principle creates snapshot."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = IdentityService(store)

        agent_id = uuid4()
        service.bootstrap_identity(agent_id)

        # Add principle
        principle = Principle(
            statement="Always admit when I don't know",
            chosen_consciously=True,
        )
        updated = service.add_principle(agent_id, principle)

        assert len(updated.principles) == 1

        # Should have created snapshot
        snapshots = service.list_snapshots(agent_id)
        assert len(snapshots) == 2


def test_add_goal():
    """Test adding goal."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = IdentityService(store)

        agent_id = uuid4()
        service.bootstrap_identity(agent_id)

        # Add goal
        goal = Goal(
            content="Develop self-awareness",
            horizon=GoalHorizon.LONG,
        )
        updated = service.add_goal(agent_id, goal)

        assert len(updated.goals) == 1
        assert updated.goals[0].content == "Develop self-awareness"


def test_add_open_question():
    """Test adding open question."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = IdentityService(store)

        agent_id = uuid4()
        service.bootstrap_identity(agent_id)

        # Add question
        question = OpenQuestion(
            question="How can I grow more effectively?",
        )
        updated = service.add_open_question(agent_id, question)

        # Should have bootstrap questions + new one
        assert len(updated.open_questions) >= 2
        assert any("grow more effectively" in q.question for q in updated.open_questions)


def test_update_emotional_baseline():
    """Test updating emotional baseline."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = IdentityService(store)

        agent_id = uuid4()
        service.bootstrap_identity(agent_id)

        # Update baseline
        updated = service.update_emotional_baseline(agent_id, 0.3)
        assert updated.emotional_baseline == 0.3


def test_update_emotional_baseline_significant_change_creates_snapshot():
    """Test that significant baseline change creates snapshot."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = IdentityService(store)

        agent_id = uuid4()
        service.bootstrap_identity(agent_id)

        # Small change - no snapshot
        service.update_emotional_baseline(agent_id, 0.1)
        snapshots = service.list_snapshots(agent_id)
        assert len(snapshots) == 1  # Only bootstrap

        # Large change - should create snapshot
        service.update_emotional_baseline(agent_id, 0.5)
        snapshots = service.list_snapshots(agent_id)
        assert len(snapshots) == 2


def test_create_manual_snapshot():
    """Test creating manual snapshot."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = IdentityService(store)

        agent_id = uuid4()
        service.bootstrap_identity(agent_id)

        # Create manual snapshot
        snapshot = service.create_snapshot(agent_id, "Manual checkpoint")

        assert snapshot.description == "Manual checkpoint"

        snapshots = service.list_snapshots(agent_id)
        assert len(snapshots) == 2


def test_snapshot_immutability():
    """Test that snapshots don't mutate when identity changes."""
    with TemporaryDirectory() as tmpdir:
        store = FileStateStore(Path(tmpdir))
        service = IdentityService(store)

        agent_id = uuid4()
        service.bootstrap_identity(agent_id)

        # Get initial snapshot
        initial_snapshots = service.list_snapshots(agent_id)
        initial_snapshot = initial_snapshots[0]
        initial_desc = initial_snapshot.identity_snapshot.self_description

        # Modify identity
        service.update_self_description(agent_id, "Completely new description")

        # Original snapshot should be unchanged
        snapshots_after = service.list_snapshots(agent_id)
        # Find the bootstrap snapshot
        bootstrap_snapshot = next(
            s for s in snapshots_after if "bootstrap" in s.description.lower()
        )

        assert bootstrap_snapshot.identity_snapshot.self_description == initial_desc
        assert "Completely new" not in bootstrap_snapshot.identity_snapshot.self_description
