"""
StateStore port - interface for state storage.

Defines the contract for all implementations of state storage:
- Experience storage
- Identity storage
- Narrative storage

Core only sees this interface, not the implementation details.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from atman.core.models import (
    Eigenstate,
    ExperienceRecord,
    Identity,
    IdentitySnapshot,
    NarrativeDocument,
    ReframingNote,
)


class ExperienceQuery:
    """Marker base class for experience queries."""

    __slots__ = ()


class SessionExperienceQuery(ExperienceQuery):
    """Query experiences by session ID."""

    def __init__(self, session_id: UUID):
        self.session_id = session_id


class ValuesTouchedQuery(ExperienceQuery):
    """Query experiences by values touched."""

    def __init__(self, values: list[str]):
        self.values = values


class DepthQuery(ExperienceQuery):
    """Query experiences by emotional depth."""

    def __init__(self, depth: str):
        self.depth = depth


class DateRangeQuery(ExperienceQuery):
    """Query experiences by date range."""

    def __init__(self, start_date: datetime, end_date: datetime):
        self.start_date = start_date
        self.end_date = end_date


class StateStore(ABC):
    """
    Interface for experience state storage.

    Provides operations for:
    - Creating experiences
    - Retrieving experiences by ID
    - Adding reframing notes
    - Marking access (for salience calculation)
    - Searching experiences by various filters

    The original experience is immutable - only reframing notes can be added.
    """

    @abstractmethod
    def create_experience(self, record: ExperienceRecord) -> ExperienceRecord:
        """
        Create a new experience in storage.

        Args:
            record: Experience record to store

        Returns:
            ExperienceRecord: The stored record with any generated IDs

        Raises:
            ValueError: If the experience is invalid
        """
        pass

    @abstractmethod
    def get_experience(self, experience_id: UUID) -> ExperienceRecord | None:
        """
        Retrieve an experience by its ID.

        Args:
            experience_id: UUID of the experience

        Returns:
            ExperienceRecord | None: The experience if found, None otherwise
        """
        pass

    @abstractmethod
    def add_reframing_note(
        self, experience_id: UUID, note: ReframingNote
    ) -> ExperienceRecord | None:
        """
        Add a reframing note to an existing experience.

        This is the ONLY way to modify an experience after creation.
        The original key_moments remain untouched.

        Args:
            experience_id: UUID of the experience
            note: The reframing note to add

        Returns:
            ExperienceRecord | None: Updated experience if found, None otherwise
        """
        pass

    @abstractmethod
    def mark_accessed(self, experience_id: UUID) -> ExperienceRecord | None:
        """
        Mark an experience as accessed.

        Updates last_accessed_at and increments access_count.
        Used for salience decay calculation.

        Args:
            experience_id: UUID of the experience

        Returns:
            ExperienceRecord | None: Updated experience if found, None otherwise
        """
        pass

    @abstractmethod
    def search_experiences(
        self, query: ExperienceQuery | None = None, limit: int = 10
    ) -> list[ExperienceRecord]:
        """
        Search for experiences matching a query.

        Supports queries by:
        - session_id (SessionExperienceQuery)
        - values_touched (ValuesTouchedQuery)
        - depth (DepthQuery)
        - date_range (DateRangeQuery)

        Args:
            query: Query object specifying search criteria
            limit: Maximum number of results

        Returns:
            list[ExperienceRecord]: List of matching experiences
        """
        pass

    @abstractmethod
    def list_recent_experiences(self, limit: int = 10) -> list[ExperienceRecord]:
        """
        List the most recent experiences.

        Args:
            limit: Maximum number of experiences to return

        Returns:
            list[ExperienceRecord]: List of recent experiences, newest first
        """
        pass

    # Identity Store operations

    @abstractmethod
    def load_identity(self, agent_id: UUID) -> Identity | None:
        """
        Load the current identity for an agent.

        Args:
            agent_id: UUID of the agent

        Returns:
            Identity | None: Current identity if exists, None otherwise
        """
        pass

    @abstractmethod
    def save_identity(self, identity: Identity, expected_version: str | None = None) -> Identity:
        """
        Save identity state.

        Args:
            identity: Identity to save
            expected_version: Expected schema version for optimistic locking

        Returns:
            Identity: Saved identity

        Raises:
            ValueError: If version mismatch (lost update)
        """
        pass

    @abstractmethod
    def create_identity_snapshot(self, snapshot: IdentitySnapshot) -> IdentitySnapshot:
        """
        Create a snapshot of identity at a point in time.

        Args:
            snapshot: Snapshot to store

        Returns:
            IdentitySnapshot: Stored snapshot
        """
        pass

    @abstractmethod
    def list_identity_snapshots(self, identity_id: UUID, limit: int = 10) -> list[IdentitySnapshot]:
        """
        List identity snapshots.

        Args:
            identity_id: UUID of the identity
            limit: Maximum number of snapshots to return

        Returns:
            list[IdentitySnapshot]: List of snapshots, newest first
        """
        pass

    # Narrative Store operations

    @abstractmethod
    def load_narrative(self, identity_id: UUID) -> NarrativeDocument | None:
        """
        Load the current narrative for an identity.

        Args:
            identity_id: UUID of the identity

        Returns:
            NarrativeDocument | None: Current narrative if exists, None otherwise
        """
        pass

    @abstractmethod
    def save_narrative(
        self, narrative: NarrativeDocument, expected_version: str | None = None
    ) -> NarrativeDocument:
        """
        Save narrative document.

        Args:
            narrative: Narrative to save
            expected_version: Expected schema version for optimistic locking

        Returns:
            NarrativeDocument: Saved narrative

        Raises:
            ValueError: If version mismatch (lost update)
        """
        pass

    @abstractmethod
    def archive_narrative(self, narrative_id: UUID, reason: str) -> None:
        """
        Archive an old narrative before replacing it.

        Args:
            narrative_id: UUID of the narrative to archive
            reason: Reason for archiving
        """
        pass

    @abstractmethod
    def list_archived_narratives(
        self, identity_id: UUID, limit: int = 10
    ) -> list[tuple[NarrativeDocument, str, datetime]]:
        """
        List archived narratives.

        Args:
            identity_id: UUID of the identity
            limit: Maximum number to return

        Returns:
            list[tuple[NarrativeDocument, reason, archived_at]]: Archived narratives with metadata
        """
        pass

    # Eigenstate operations

    @abstractmethod
    def save_eigenstate(self, eigenstate: Eigenstate) -> Eigenstate:
        """
        Save eigenstate from session end.

        Args:
            eigenstate: Eigenstate to save

        Returns:
            Eigenstate: Saved eigenstate
        """
        pass

    @abstractmethod
    def load_latest_eigenstate(self, session_id: UUID | None = None) -> Eigenstate | None:
        """
        Load the most recent eigenstate.

        Args:
            session_id: Optional session ID to load eigenstate for specific session

        Returns:
            Eigenstate | None: Latest eigenstate if exists, None otherwise
        """
        pass
