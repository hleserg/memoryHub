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
from typing import Protocol
from uuid import UUID

from atman.core.models.experience import ReframingNote, SessionExperience
from atman.core.models.identity import Identity, IdentitySnapshot
from atman.core.models.narrative import NarrativeDocument
from atman.core.models.reflection import (
    HealthAssessment,
    JahodaCriterion,
    PatternCandidate,
    ReflectionEvent,
    ReflectionLevel,
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

    def add_reframing_note(self, experience_id: UUID, note: ReframingNote) -> bool:
        """
        Append a reframing note to an experience.

        Returns:
            True if the experience existed and the note was stored; False otherwise.
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
        self, identity: Identity, description: str, change_summary: str
    ) -> IdentitySnapshot:
        """Create a new identity snapshot."""
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


class ReflectionEventStore(ABC):
    """
    Storage for reflection events.

    This keeps a history of all reflection processes that have been run.
    """

    @abstractmethod
    def save(self, event: ReflectionEvent) -> None:
        """Save a reflection event."""
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
    Port for text generation during reflection.

    This can be implemented as:
    - A real LLM integration (Claude, GPT, etc.)
    - A mock/deterministic generator for testing
    - A template-based generator

    The key is that reflection logic stays separate from text generation.
    """

    @abstractmethod
    def generate_reframing_note(
        self,
        experience: SessionExperience,
        context: dict[str, str],
    ) -> str:
        """
        Generate a reframing note for an experience.

        Args:
            experience: The experience to reframe
            context: Additional context (identity, recent patterns, etc.)

        Returns:
            Text of the reframing note
        """
        ...

    @abstractmethod
    def detect_pattern(
        self,
        experiences: list[SessionExperience],
        context: dict[str, str],
    ) -> str:
        """
        Detect and describe a pattern across experiences.

        Args:
            experiences: List of experiences to analyze
            context: Additional context (identity, known patterns, etc.)

        Returns:
            Description of detected pattern
        """
        ...

    @abstractmethod
    def propose_narrative_update(
        self,
        current_narrative: NarrativeDocument,
        recent_experiences: list[SessionExperience],
        reflection_level: ReflectionLevel,
    ) -> str:
        """
        Propose an update to the narrative.

        Args:
            current_narrative: Current narrative document
            recent_experiences: Recent experiences to incorporate
            reflection_level: Level of reflection being performed

        Returns:
            Proposed narrative update text
        """
        ...

    @abstractmethod
    def assess_health_criterion(
        self,
        identity: Identity,
        experiences: list[SessionExperience],
        criterion: JahodaCriterion,
    ) -> tuple[float, list[str], list[str]]:
        """
        Assess one Jahoda health criterion.

        Args:
            identity: Current identity
            experiences: Recent experiences
            criterion: Which criterion to assess

        Returns:
            Tuple of (score, evidence_list, concerns_list)
        """
        ...
