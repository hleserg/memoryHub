"""
Ports for Reflection Engine.

These define interfaces that the Reflection Engine depends on:
- ExperienceRepository: access to stored experiences
- IdentityRepository: access to identity state
- NarrativeRepository: access to narrative state
- ReflectionModel: text generation for reflection (LLM or mock)
- PatternStore: storage for detected patterns
- ReflectionEventStore: storage for reflection events
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from atman.core.models.entity import Entity
from atman.core.models.experience import (
    KeyMoment,
    ReframingNote,
    ReframingNoteAppendResult,
    SessionExperience,
)
from atman.core.models.identity import Identity, IdentitySnapshot
from atman.core.models.narrative import NarrativeDocument
from atman.core.models.reflection import (
    EntityRelationFormulationOutput,
    HealthAssessment,
    HealthCriterionOutput,
    JahodaCriterion,
    MergeDecisionOutput,
    NarrativeUpdateOutput,
    PatternCandidate,
    PatternDetectionOutput,
    ReflectionEvent,
    ReflectionLevel,
    ReframingNoteOutput,
    StanceFormulationOutput,
)


class ExperienceRepository(Protocol):
    """
    Port for accessing stored experiences.

    Reflection Engine needs to read experiences to analyze patterns,
    add reframing notes, and assess salience.
    """

    def get(self, experience_id: UUID) -> SessionExperience | None:
        """Get a single experience by ID."""
        ...

    def get_all(self) -> list[SessionExperience]:
        """Get all stored experiences."""
        ...

    def get_by_session(self, session_id: UUID) -> list[SessionExperience]:
        """Get all experiences from a specific session."""
        ...

    def get_recent(self, limit: int = 10) -> list[SessionExperience]:
        """Get most recent experiences."""
        ...

    def get_in_range(self, start: datetime, end: datetime) -> list[SessionExperience]:
        """Get experiences within a date range."""
        ...

    def update(self, experience: SessionExperience) -> None:
        """Update an experience (e.g., after adding reframing note)."""
        ...

    def add_reframing_note(
        self, experience_id: UUID, note: ReframingNote
    ) -> ReframingNoteAppendResult:
        """
        Append a reframing note to an experience.

        If ``note.triggered_by`` matches an existing note on the same experience,
        implementations must return :attr:`~atman.core.models.experience.ReframingNoteAppendResult.DUPLICATE_TRIGGERED_BY`
        (idempotent no-op). Callers must not treat that outcome like a missing
        experience or a storage failure.

        Returns:
            :class:`~atman.core.models.experience.ReframingNoteAppendResult` discriminating
            stored / duplicate / not found / storage rejected.
        """
        ...


class IdentityRepository(Protocol):
    """
    Port for accessing identity state.

    Reflection Engine needs to read current identity to understand values,
    principles, and open questions, and to propose updates.
    """

    def get_current(self) -> Identity | None:
        """Get the current identity."""
        ...

    def get_snapshot(self, snapshot_id: UUID) -> IdentitySnapshot | None:
        """Get a specific identity snapshot."""
        ...

    def get_history(self) -> list[IdentitySnapshot]:
        """Get history of identity snapshots."""
        ...

    def update(self, identity: Identity) -> None:
        """Update the current identity."""
        ...

    def create_snapshot(
        self,
        identity: Identity,
        description: str,
        change_summary: str,
        *,
        snapshot_id: UUID | None = None,
    ) -> IdentitySnapshot:
        """
        Create a new identity snapshot.

        When ``snapshot_id`` is set, implementations must use it as the snapshot
        row id (for idempotent reflection anchors keyed by ``reflection_run_key``).
        """
        ...


class NarrativeRepository(Protocol):
    """
    Port for accessing narrative state.

    Reflection Engine needs to read and update the narrative document,
    especially during micro and deep reflection.
    """

    def get_current(self) -> NarrativeDocument | None:
        """Get the current narrative document."""
        ...

    def update(
        self,
        narrative: NarrativeDocument,
        *,
        expected_updated_at: datetime | None = None,
    ) -> None:
        """
        Persist the narrative document.

        When ``expected_updated_at`` is set, implementations must reject the
        write unless the last committed narrative has the same ``updated_at``
        (optimistic concurrency). On mismatch, raise
        :class:`NarrativePersistenceConflictError` so callers do not silently
        overwrite concurrent edits.

        When ``expected_updated_at`` is None, implementations may skip the
        check (legacy / tooling paths only — production reflection paths
        should pass the token).
        """
        ...

    def get_history(self) -> list[NarrativeDocument]:
        """Get history of narrative documents (if versioned)."""
        ...


class NarrativeWriteAuditPort(Protocol):
    """
    Optional hook for governance / audit after a successful narrative commit.

    Implementations may append :class:`AuditEvent`-like records, emit metrics,
    or enqueue human review. Core layer commits should always be observable
    when this port is wired.

    If :meth:`record_narrative_commit` raises after the repository has already
    persisted the narrative, callers use :meth:`record_narrative_commit_audit_failure`
    so governance still sees a durable signal (commit succeeded, audit emission
    failed).
    """

    def record_narrative_commit(
        self,
        *,
        change_kind: str,
        narrative_id: UUID,
        identity_id: UUID,
        reason_or_summary: str,
    ) -> None:
        """
        Record that a narrative mutation was committed.

        ``change_kind`` values used by ``NarrativeRevisionService``:
        ``core_layer``, ``recent_layer``, ``thread_open``, ``thread_update``,
        ``thread_close``.
        """
        ...

    def record_narrative_commit_audit_failure(
        self,
        *,
        change_kind: str,
        narrative_id: UUID,
        identity_id: UUID,
        committed_summary: str,
        error_message: str,
    ) -> None:
        """
        Record that persistence succeeded but the primary audit line failed.

        Implementations should append a degraded / out-of-band audit row (or
        enqueue retry). Must not raise if avoidable — the narrative is already
        committed.
        """
        ...


class PatternStore(ABC):
    """
    Storage for detected patterns.

    Patterns accumulate over time as reflection discovers recurring themes.
    """

    @abstractmethod
    def save(self, pattern: PatternCandidate) -> None:
        """Save a pattern candidate."""
        ...

    @abstractmethod
    def get(self, pattern_id: UUID) -> PatternCandidate | None:
        """Get a pattern by ID."""
        ...

    @abstractmethod
    def get_all(self) -> list[PatternCandidate]:
        """Get all patterns."""
        ...

    @abstractmethod
    def get_by_level(self, level: ReflectionLevel) -> list[PatternCandidate]:
        """Get patterns detected at a specific reflection level."""
        ...

    @abstractmethod
    def update(self, pattern: PatternCandidate) -> None:
        """Update a pattern (e.g., change status to confirmed)."""
        ...

    @abstractmethod
    def save_with_detection_key(
        self, detection_key: str, pattern: PatternCandidate
    ) -> PatternCandidate:
        """
        Persist a pattern once per ``detection_key``.

        Returns the stored instance (existing row on retry, or the newly saved
        pattern with a stable id derived from the key).
        """
        ...


class ReflectionEventStore(ABC):
    """
    Storage for reflection events.

    This keeps a history of all reflection processes that have been run.
    """

    @abstractmethod
    def save(self, event: ReflectionEvent) -> None:
        """
        Save a reflection event.

        When ``event.reflection_run_key`` is set, implementations must upsert by
        that key so retries reuse the same logical event id.
        """
        ...

    @abstractmethod
    def get_by_reflection_run_key(self, run_key: str) -> ReflectionEvent | None:
        """Return the event for a deterministic reflection job, if any."""
        ...

    @abstractmethod
    def get(self, event_id: UUID) -> ReflectionEvent | None:
        """Get a reflection event by ID."""
        ...

    @abstractmethod
    def get_all(self) -> list[ReflectionEvent]:
        """Get all reflection events."""
        ...

    @abstractmethod
    def get_by_level(self, level: ReflectionLevel) -> list[ReflectionEvent]:
        """Get reflection events at a specific level."""
        ...

    @abstractmethod
    def get_recent(self, limit: int = 10) -> list[ReflectionEvent]:
        """Get most recent reflection events."""
        ...


@runtime_checkable
class ReflectionEventPersistenceObserver(Protocol):
    """Observes failures to persist a reflection event after other durable writes."""

    def record_reflection_event_save_failed_after_narrative_commit(
        self,
        *,
        reflection_level: ReflectionLevel,
        error_message: str,
    ) -> None:
        """Narrative was committed but the reflection event could not be stored."""
        ...

    def record_reflection_job_event_save_failed_after_side_effects(
        self,
        *,
        reflection_level: ReflectionLevel,
        reflection_run_key: str | None,
        error_message: str,
    ) -> None:
        """Patterns/reframing/health (etc.) may be persisted but the job event was not."""
        ...


class HealthAssessmentStore(ABC):
    """
    Storage for health assessments.

    Health assessments are performed during deep reflection.
    """

    @abstractmethod
    def save(self, assessment: HealthAssessment) -> None:
        """Save a health assessment."""
        ...

    @abstractmethod
    def get(self, assessment_id: UUID) -> HealthAssessment | None:
        """Get a health assessment by ID."""
        ...

    @abstractmethod
    def get_all(self) -> list[HealthAssessment]:
        """Get all health assessments."""
        ...

    @abstractmethod
    def get_latest(self) -> HealthAssessment | None:
        """Get the most recent health assessment."""
        ...


class ReflectionModel(ABC):
    """
    Port for structured generation during reflection (LLM or mock).

    Implementations return Pydantic DTOs so services do not depend on free-form
    parsing (GitHub #146, MODEL-01).
    """

    @abstractmethod
    def generate_reframing_note(
        self,
        experience: SessionExperience,
        context: dict[str, str],
    ) -> ReframingNoteOutput:
        """
        Generate a reframing note for an experience.

        Args:
            experience: The experience to reframe
            context: Additional context (identity, recent patterns, etc.)

        Returns:
            Structured note; empty ``reflection`` means skip persistence.
        """
        ...

    @abstractmethod
    def detect_pattern(
        self,
        experiences: list[SessionExperience],
        context: dict[str, str],
    ) -> PatternDetectionOutput:
        """
        Detect and describe a pattern across experiences.

        Args:
            experiences: List of experiences to analyze
            context: Additional context (identity, known patterns, etc.)

        Returns:
            Structured detection; empty ``description`` means no pattern.
        """
        ...

    @abstractmethod
    def propose_narrative_update(
        self,
        current_narrative: NarrativeDocument,
        recent_experiences: list[SessionExperience],
        reflection_level: ReflectionLevel,
    ) -> NarrativeUpdateOutput:
        """
        Propose an update to the narrative.

        Args:
            current_narrative: Current narrative document
            recent_experiences: Recent experiences to incorporate
            reflection_level: Level of reflection being performed

        Returns:
            Structured proposal; ``body`` is applied to the narrative layer.
        """
        ...

    @abstractmethod
    def assess_health_criterion(
        self,
        identity: Identity,
        experiences: list[SessionExperience],
        criterion: JahodaCriterion,
    ) -> HealthCriterionOutput:
        """
        Assess one Jahoda health criterion.

        Args:
            identity: Current identity
            experiences: Recent experiences
            criterion: Which criterion to assess

        Returns:
            Structured score, evidence, and concerns.
        """
        ...

    # R7 — EntityStanceFormulator (REFLECTION_FUTURE.md §4.3, §5.2, §9).
    # Implementations that have not yet wired up a stance prompt should
    # return the default empty :class:`StanceFormulationOutput`; the service
    # will treat that as "decline to commit" and skip persistence.
    def formulate_entity_stance(
        self,
        entity: Entity,
        moments: list[KeyMoment],
        structured_markers: dict[str, int] | None = None,
    ) -> StanceFormulationOutput:
        """
        Interpret a sequence of KeyMoments and put words to the agent's
        current stance toward ``entity``.

        Args:
            entity: The entity the stance is about.
            moments: KeyMoments involving the entity (R7 default: ≥ 5).
            structured_markers: Optional rolled-up marker counts for context.

        Returns:
            Structured stance; empty ``stance_text`` means decline / skip.
        """
        return StanceFormulationOutput()

    # R9 — EntityRelationsFormulator (REFLECTION_FUTURE.md §5.3). Non-abstract
    # default so existing subclasses don't break; service treats an empty
    # ``relation_type`` as "no relation worth recording".
    def formulate_entity_relation(
        self,
        entity_a: Entity,
        entity_b: Entity,
        shared_moments: list[KeyMoment],
    ) -> EntityRelationFormulationOutput:
        """
        Interpret a sequence of KeyMoments where ``entity_a`` and ``entity_b``
        co-occur and decide whether there is a meaningful typed relation.

        Implementations should not invent relations: when the evidence is
        thin or contradictory, return an empty ``relation_type``.
        """
        return EntityRelationFormulationOutput()

    # R10 — MergeCandidatesHandler (REFLECTION_FUTURE.md §5.4). Non-abstract
    # default so existing subclasses don't break; service treats
    # ``confirmed=False`` (the default) as "ignore" with the empty reason.
    def decide_entity_merge(
        self,
        entity_a: Entity,
        entity_b: Entity,
        contexts_a: list[KeyMoment],
        contexts_b: list[KeyMoment],
    ) -> MergeDecisionOutput:
        """
        Decide whether two near-duplicate entities are actually the same
        subject. Used by Deep reflection on ``similar_entities`` findings.

        Implementations should not invent confirmations: when the contexts
        disagree, return ``confirmed=False`` with a short ``reason``.
        """
        return MergeDecisionOutput()
