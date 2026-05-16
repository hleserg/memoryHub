"""
Identity Service - manages agent identity lifecycle.

Responsibilities:
- Bootstrap empty honest identity
- Update identity components (values, habits, principles, goals, questions)
- Create snapshots on significant changes
- Read current identity state
"""

from datetime import UTC, datetime
from typing import Any, ClassVar
from uuid import UUID

from atman.core.models import (
    CoreValue,
    Goal,
    Habit,
    Identity,
    IdentitySnapshot,
    OpenQuestion,
    Principle,
    SelfAppliedChange,
    SelfChangeSource,
    SelfChangeTargetKind,
)
from atman.core.ports.self_applied_changes import SelfAppliedChangeStore
from atman.core.ports.state_store import StateStore


class IdentityService:
    """
    Service for managing agent identity.

    This service ensures identity is managed honestly and consistently:
    - Bootstrap creates genuinely empty identity with honest self-description
    - Updates are tracked and snapshotted
    - No fake or seeded principles
    """

    def __init__(
        self,
        state_store: StateStore,
        self_applied_change_store: SelfAppliedChangeStore | None = None,
    ):
        """
        Initialize identity service.

        Args:
            state_store: StateStore implementation for persistence
            self_applied_change_store: Audit store for `apply_self_change`/`revert_self_change`.
                Optional — only required if those methods are used.
        """
        self.state_store = state_store
        self._self_applied_change_store = self_applied_change_store

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

    # ---------------------------------------------------------------------
    # Self-apply API (reflection-initiated changes with audit and revert)
    # ---------------------------------------------------------------------

    _IDENTITY_LIST_FIELDS: ClassVar[dict[SelfChangeTargetKind, str]] = {
        SelfChangeTargetKind.IDENTITY_CORE_VALUE: "core_values",
        SelfChangeTargetKind.IDENTITY_PRINCIPLE: "principles",
        SelfChangeTargetKind.IDENTITY_HABIT: "habits",
        SelfChangeTargetKind.IDENTITY_GOAL: "goals",
        SelfChangeTargetKind.IDENTITY_OPEN_QUESTION: "open_questions",
    }

    # PLAYBOOK-START
    # id: reversible-audit-trail-before-after-snapshots
    # category: design-patterns
    # title: Reversible Audit Trail with Before/After Snapshots
    # status: draft
    #
    # Pattern: every autonomous state mutation captures a `before` snapshot
    # (the prior value) and an `after` snapshot (the new value) into an
    # append-only audit store. Revert is a separate operation that loads the
    # recorded `before`, re-applies it to current state, and writes a second
    # audit entry referencing the original. The store itself is never
    # mutated; even a revert produces a new record.
    #
    # Why generalizable: any system that lets autonomous agents (or
    # automated workflows) change persistent state needs both observability
    # and surgical undo. Treating each change as immutable evidence with
    # paired snapshots gives reviewers a complete diff and gives operators
    # a deterministic rollback without rebuilding from a full event log.
    #
    # Trade-offs: doubles write volume vs. forward-only logs. Revert in
    # this prototype restores the recorded `before` snapshot wholesale, so
    # any intermediate mutation to the same field is silently overwritten;
    # production use needs an explicit conflict policy.
    # PLAYBOOK-END
    def apply_self_change(
        self,
        agent_id: UUID,
        target_kind: SelfChangeTargetKind,
        payload: Any,
        source: SelfChangeSource,
    ) -> SelfAppliedChange:
        """
        Apply an identity change initiated by reflection itself.

        Records a `SelfAppliedChange` audit row with full before/after snapshot
        so the change can be reverted later. This path does **not** require a
        `GovernanceDecision` — it is reflection's own prerogative — but the
        source must carry rationale, confidence statement, and supporting
        moment ids (enforced by `SelfChangeSource`).

        Args:
            agent_id: identity to modify
            target_kind: which aspect of identity is being changed; must be
                one of the ``IDENTITY_*`` kinds. ``NARRATIVE_*`` is rejected.
            payload: change payload. For list-shaped kinds (core_value,
                principle, habit, goal, open_question) this is the item to
                append. For ``IDENTITY_SELF_DESCRIPTION`` this is the new
                description string.
            source: provenance with rationale and supporting moments.

        Returns:
            SelfAppliedChange: persisted audit record.

        Raises:
            RuntimeError: if the service was not constructed with a
                `SelfAppliedChangeStore`.
            ValueError: if identity not found or target_kind is not an
                identity kind.
            TypeError: if payload type does not match target_kind.
        """
        store = self._require_self_applied_store("apply_self_change")
        identity = self.state_store.load_identity(agent_id)
        if identity is None:
            raise ValueError(f"Identity {agent_id} not found")

        if target_kind == SelfChangeTargetKind.IDENTITY_SELF_DESCRIPTION:
            target_ref, before_snapshot, after_snapshot = self._apply_self_description(
                identity, payload
            )
        elif target_kind in self._IDENTITY_LIST_FIELDS:
            target_ref, before_snapshot, after_snapshot = self._apply_identity_list_append(
                identity, target_kind, payload
            )
        else:
            raise ValueError(
                f"apply_self_change does not handle target_kind={target_kind.value!r}; "
                "narrative kinds go through NarrativeRevisionService.apply_self_layer_update"
            )

        identity.updated_at = datetime.now(UTC)
        self.state_store.save_identity(identity)

        change = SelfAppliedChange(
            agent_id=agent_id,
            actor=source.actor,
            reflection_event_id=source.reflection_event_id,
            target_kind=target_kind,
            target_ref=target_ref,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
            rationale=source.rationale,
            confidence_self_assessment=source.confidence_self_assessment,
            based_on_moment_ids=list(source.based_on_moment_ids),
        )
        store.save(change)
        return change

    def revert_self_change(
        self,
        agent_id: UUID,
        self_applied_id: UUID,
        reason: str,
    ) -> SelfAppliedChange:
        """
        Revert a previously self-applied identity change.

        The revert restores the change's `before_snapshot` onto the current
        identity and records the revert by updating the original audit row
        (`reverted_at`, `reverted_reason`). The actual restoration is itself
        a write to identity; existing IdentitySnapshots are not touched.

        Args:
            agent_id: identity to modify
            self_applied_id: id of the SelfAppliedChange to revert
            reason: human-readable explanation

        Returns:
            SelfAppliedChange: the original record with revert fields populated.

        Raises:
            RuntimeError: if no SelfAppliedChangeStore.
            KeyError: if the change does not exist.
            ValueError: if the change targets a different agent, has already
                been reverted, or is not an identity kind.
        """
        if not reason or not reason.strip():
            raise ValueError("reason must be non-empty")

        store = self._require_self_applied_store("revert_self_change")
        change = store.get(self_applied_id)
        if change is None:
            raise KeyError(f"self_applied_change {self_applied_id} not found")
        if change.reverted_at is not None:
            raise ValueError(f"self_applied_change {self_applied_id} already reverted")
        if change.agent_id is not None and change.agent_id != agent_id:
            raise ValueError(
                f"self_applied_change {self_applied_id} belongs to a different agent "
                f"({change.agent_id}); cannot revert against {agent_id}"
            )

        identity = self.state_store.load_identity(agent_id)
        if identity is None:
            raise ValueError(f"Identity {agent_id} not found")

        if change.target_kind == SelfChangeTargetKind.IDENTITY_SELF_DESCRIPTION:
            self._revert_self_description(identity, change)
        elif change.target_kind in self._IDENTITY_LIST_FIELDS:
            self._revert_identity_list_append(identity, change)
        else:
            raise ValueError(
                f"revert_self_change cannot revert target_kind={change.target_kind.value!r}; "
                "use NarrativeRevisionService.revert_self_change for narrative kinds"
            )

        identity.updated_at = datetime.now(UTC)
        self.state_store.save_identity(identity)

        return store.mark_reverted(
            self_applied_id,
            reverted_at=datetime.now(UTC),
            reason=reason.strip(),
        )

    # ----- helpers -----

    def _require_self_applied_store(self, method: str) -> SelfAppliedChangeStore:
        if self._self_applied_change_store is None:
            raise RuntimeError(
                f"IdentityService.{method} requires a SelfAppliedChangeStore; "
                "pass one to the constructor"
            )
        return self._self_applied_change_store

    def _apply_self_description(
        self, identity: Identity, payload: Any
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        if not isinstance(payload, str):
            raise TypeError(
                f"IDENTITY_SELF_DESCRIPTION expects str payload, got {type(payload).__name__}"
            )
        before = identity.self_description
        identity.self_description = payload
        return (
            "self_description",
            {"self_description": before},
            {"self_description": payload},
        )

    _IDENTITY_LIST_TYPES: ClassVar[dict[SelfChangeTargetKind, type]] = {
        SelfChangeTargetKind.IDENTITY_CORE_VALUE: CoreValue,
        SelfChangeTargetKind.IDENTITY_PRINCIPLE: Principle,
        SelfChangeTargetKind.IDENTITY_HABIT: Habit,
        SelfChangeTargetKind.IDENTITY_GOAL: Goal,
        SelfChangeTargetKind.IDENTITY_OPEN_QUESTION: OpenQuestion,
    }

    def _apply_identity_list_append(
        self, identity: Identity, kind: SelfChangeTargetKind, payload: Any
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        field_name = self._IDENTITY_LIST_FIELDS[kind]
        model_cls = self._IDENTITY_LIST_TYPES[kind]
        if not isinstance(payload, model_cls):
            raise TypeError(
                f"{kind.value} expects payload of type {model_cls.__name__}, "
                f"got {type(payload).__name__}"
            )
        current_list = list(getattr(identity, field_name))
        new_list = [*current_list, payload]
        setattr(identity, field_name, new_list)
        target_ref = self._target_ref_for_item(kind, payload)
        return (
            target_ref,
            {field_name: [item.model_dump(mode="json") for item in current_list]},
            {field_name: [item.model_dump(mode="json") for item in new_list]},
        )

    @staticmethod
    def _target_ref_for_item(kind: SelfChangeTargetKind, payload: Any) -> str:
        if kind == SelfChangeTargetKind.IDENTITY_CORE_VALUE:
            return f"core_value:{payload.name}"
        if kind == SelfChangeTargetKind.IDENTITY_PRINCIPLE:
            return f"principle:{payload.statement[:80]}"
        if kind == SelfChangeTargetKind.IDENTITY_HABIT:
            return f"habit:{payload.statement[:80]}"
        if kind == SelfChangeTargetKind.IDENTITY_GOAL:
            return f"goal:{payload.content[:80]}"
        if kind == SelfChangeTargetKind.IDENTITY_OPEN_QUESTION:
            return f"open_question:{payload.question[:80]}"
        return kind.value

    def _revert_self_description(self, identity: Identity, change: SelfAppliedChange) -> None:
        before = change.before_snapshot.get("self_description")
        if not isinstance(before, str):
            raise ValueError(
                f"self_applied_change {change.id} has malformed before_snapshot for self_description"
            )
        identity.self_description = before

    def _revert_identity_list_append(self, identity: Identity, change: SelfAppliedChange) -> None:
        field_name = self._IDENTITY_LIST_FIELDS[change.target_kind]
        before_list = change.before_snapshot.get(field_name)
        if not isinstance(before_list, list):
            raise ValueError(
                f"self_applied_change {change.id} has malformed before_snapshot for {field_name}"
            )
        model_cls = self._IDENTITY_LIST_TYPES[change.target_kind]
        rehydrated = [model_cls.model_validate(item) for item in before_list]
        setattr(identity, field_name, rehydrated)
