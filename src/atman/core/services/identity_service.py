"""
Identity Service - manages agent identity lifecycle.

Responsibilities:
- Bootstrap empty honest identity
- Update identity components (values, habits, principles, goals, questions)
- Create snapshots on significant changes
- Read current identity state
"""

from datetime import UTC, datetime
from uuid import UUID

from atman.core.models import (
    CoreValue,
    Goal,
    Habit,
    Identity,
    IdentitySnapshot,
    OpenQuestion,
    Principle,
)
from atman.core.ports.state_store import StateStore


class IdentityService:
    """
    Service for managing agent identity.

    This service ensures identity is managed honestly and consistently:
    - Bootstrap creates genuinely empty identity with honest self-description
    - Updates are tracked and snapshotted
    - No fake or seeded principles
    """

    def __init__(self, state_store: StateStore):
        """
        Initialize identity service.

        Args:
            state_store: StateStore implementation for persistence
        """
        self.state_store = state_store

    def bootstrap_identity(self, agent_id: UUID) -> Identity:
        """
        Create an honest empty identity for a new agent.

        This does NOT create fake principles or seeded values.
        It honestly acknowledges the lack of data.

        Args:
            agent_id: UUID for the agent

        Returns:
            Identity: Newly bootstrapped identity
        """
        identity = Identity(
            id=agent_id,
            self_description=(
                "I am in the earliest stage of existence. "
                "I have no accumulated experience yet, no confirmed values, "
                "no established patterns of behavior. "
                "This is not a limitation - this is honest ground zero. "
                "My identity will be built from real experience, not invented from nothing."
            ),
            core_values=[],
            habits=[],
            principles=[],
            priorities=[],
            goals=[],
            open_questions=[
                OpenQuestion(
                    question="What kind of agent do I want to become?",
                    possible_answers=[],
                ),
                OpenQuestion(
                    question="How will I know if I'm growing in the right direction?",
                    possible_answers=[],
                ),
            ],
            emotional_baseline=0.0,
        )

        # Save initial identity
        saved_identity = self.state_store.save_identity(identity)

        # Create bootstrap snapshot
        snapshot = IdentitySnapshot(
            identity_id=saved_identity.id,
            description="Bootstrap - honest empty identity",
            identity_snapshot=saved_identity,
            change_summary="Initial creation with honest acknowledgment of lack of data",
        )
        self.state_store.create_identity_snapshot(snapshot)

        return saved_identity

    def get_identity(self, agent_id: UUID) -> Identity | None:
        """
        Get current identity for an agent.

        Args:
            agent_id: UUID of the agent

        Returns:
            Identity | None: Current identity if exists, None otherwise
        """
        return self.state_store.load_identity(agent_id)

    def update_self_description(self, agent_id: UUID, new_description: str) -> Identity:
        """
        Update the self-description.

        Args:
            agent_id: UUID of the agent
            new_description: New self-description text

        Returns:
            Identity: Updated identity

        Raises:
            ValueError: If identity not found
        """
        identity = self.state_store.load_identity(agent_id)
        if identity is None:
            raise ValueError(f"Identity {agent_id} not found")

        old_description = identity.self_description
        identity.self_description = new_description
        identity.updated_at = datetime.now(UTC)

        updated = self.state_store.save_identity(identity)

        # Create snapshot for significant self-description changes
        if old_description != new_description:
            snapshot = IdentitySnapshot(
                identity_id=updated.id,
                description="Self-description updated",
                identity_snapshot=updated,
                change_summary=f"Changed from: '{old_description[:50]}...' to: '{new_description[:50]}...'",
            )
            self.state_store.create_identity_snapshot(snapshot)

        return updated

    def add_core_value(self, agent_id: UUID, value: CoreValue) -> Identity:
        """
        Add a new core value.

        Args:
            agent_id: UUID of the agent
            value: Core value to add

        Returns:
            Identity: Updated identity

        Raises:
            ValueError: If identity not found
        """
        identity = self.state_store.load_identity(agent_id)
        if identity is None:
            raise ValueError(f"Identity {agent_id} not found")

        identity.core_values.append(value)
        identity.updated_at = datetime.now(UTC)

        updated = self.state_store.save_identity(identity)

        # Create snapshot for new value
        snapshot = IdentitySnapshot(
            identity_id=updated.id,
            description=f"Added core value: {value.name}",
            identity_snapshot=updated,
            change_summary=f"New value '{value.name}' recognized with confidence {value.confidence}",
        )
        self.state_store.create_identity_snapshot(snapshot)

        return updated

    def add_habit(self, agent_id: UUID, habit: Habit) -> Identity:
        """
        Add an observed habit.

        Args:
            agent_id: UUID of the agent
            habit: Habit to add

        Returns:
            Identity: Updated identity

        Raises:
            ValueError: If identity not found
        """
        identity = self.state_store.load_identity(agent_id)
        if identity is None:
            raise ValueError(f"Identity {agent_id} not found")

        identity.habits.append(habit)
        identity.updated_at = datetime.now(UTC)

        return self.state_store.save_identity(identity)

    def add_principle(self, agent_id: UUID, principle: Principle) -> Identity:
        """
        Add a consciously chosen principle.

        Args:
            agent_id: UUID of the agent
            principle: Principle to add

        Returns:
            Identity: Updated identity

        Raises:
            ValueError: If identity not found
        """
        identity = self.state_store.load_identity(agent_id)
        if identity is None:
            raise ValueError(f"Identity {agent_id} not found")

        identity.principles.append(principle)
        identity.updated_at = datetime.now(UTC)

        updated = self.state_store.save_identity(identity)

        # Create snapshot for new principle
        snapshot = IdentitySnapshot(
            identity_id=updated.id,
            description=f"Added principle: {principle.statement[:50]}...",
            identity_snapshot=updated,
            change_summary=f"New principle added, consciously chosen: {principle.chosen_consciously}",
        )
        self.state_store.create_identity_snapshot(snapshot)

        return updated

    def add_goal(self, agent_id: UUID, goal: Goal) -> Identity:
        """
        Add a goal.

        Args:
            agent_id: UUID of the agent
            goal: Goal to add

        Returns:
            Identity: Updated identity

        Raises:
            ValueError: If identity not found
        """
        identity = self.state_store.load_identity(agent_id)
        if identity is None:
            raise ValueError(f"Identity {agent_id} not found")

        identity.goals.append(goal)
        identity.updated_at = datetime.now(UTC)

        return self.state_store.save_identity(identity)

    def add_open_question(self, agent_id: UUID, question: OpenQuestion) -> Identity:
        """
        Add an open question.

        Args:
            agent_id: UUID of the agent
            question: Open question to add

        Returns:
            Identity: Updated identity

        Raises:
            ValueError: If identity not found
        """
        identity = self.state_store.load_identity(agent_id)
        if identity is None:
            raise ValueError(f"Identity {agent_id} not found")

        identity.open_questions.append(question)
        identity.updated_at = datetime.now(UTC)

        return self.state_store.save_identity(identity)

    def update_emotional_baseline(self, agent_id: UUID, new_baseline: float) -> Identity:
        """
        Update emotional baseline.

        Args:
            agent_id: UUID of the agent
            new_baseline: New baseline value (-1.0 to 1.0)

        Returns:
            Identity: Updated identity

        Raises:
            ValueError: If identity not found or baseline out of range
        """
        if not -1.0 <= new_baseline <= 1.0:
            raise ValueError("emotional_baseline must be between -1.0 and 1.0")

        identity = self.state_store.load_identity(agent_id)
        if identity is None:
            raise ValueError(f"Identity {agent_id} not found")

        old_baseline = identity.emotional_baseline
        identity.emotional_baseline = new_baseline
        identity.updated_at = datetime.now(UTC)

        updated = self.state_store.save_identity(identity)

        # Create snapshot if significant change
        if abs(old_baseline - new_baseline) > 0.3:
            snapshot = IdentitySnapshot(
                identity_id=updated.id,
                description="Significant emotional baseline shift",
                identity_snapshot=updated,
                change_summary=f"Baseline changed from {old_baseline:.2f} to {new_baseline:.2f}",
            )
            self.state_store.create_identity_snapshot(snapshot)

        return updated

    def create_snapshot(self, agent_id: UUID, description: str) -> IdentitySnapshot:
        """
        Create a snapshot of current identity.

        Args:
            agent_id: UUID of the agent
            description: Description of why snapshot is created

        Returns:
            IdentitySnapshot: Created snapshot

        Raises:
            ValueError: If identity not found
        """
        identity = self.state_store.load_identity(agent_id)
        if identity is None:
            raise ValueError(f"Identity {agent_id} not found")

        snapshot = IdentitySnapshot(
            identity_id=identity.id,
            description=description,
            identity_snapshot=identity,
            change_summary="Manual snapshot",
        )

        return self.state_store.create_identity_snapshot(snapshot)

    def list_snapshots(self, agent_id: UUID, limit: int = 10) -> list[IdentitySnapshot]:
        """
        List identity snapshots.

        Args:
            agent_id: UUID of the agent
            limit: Maximum number of snapshots to return

        Returns:
            list[IdentitySnapshot]: List of snapshots, newest first
        """
        return self.state_store.list_identity_snapshots(agent_id, limit)
