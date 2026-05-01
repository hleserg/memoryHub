"""
Experience Service - business logic for working with experiences.

This service coordinates between the domain models and the storage adapter.
It enforces invariants and provides high-level operations.
"""

from datetime import datetime
from uuid import UUID

from atman.core.models import ExperienceRecord, ReframingNote, SessionExperience
from atman.core.ports import (
    DateRangeQuery,
    DepthQuery,
    SessionExperienceQuery,
    StateStore,
    ValuesTouchedQuery,
)


class ExperienceService:
    """
    Service for managing experiences.

    Provides high-level operations:
    - Creating experiences
    - Retrieving experiences
    - Adding reframing notes
    - Marking access
    - Searching and querying
    - Calculating current salience
    """

    def __init__(self, store: StateStore):
        """
        Initialize the experience service.

        Args:
            store: Storage adapter for persistence
        """
        self.store = store

    def create_experience(
        self, experience: SessionExperience, schema_version: str = "1.0.0"
    ) -> ExperienceRecord:
        """
        Create a new experience.

        Args:
            experience: The session experience to store
            schema_version: Schema version for the record

        Returns:
            ExperienceRecord: The created record

        Raises:
            ValueError: If the experience is invalid or already exists
        """
        record = ExperienceRecord(schema_version=schema_version, experience=experience)

        return self.store.create_experience(record)

    def get_experience(self, experience_id: UUID) -> ExperienceRecord | None:
        """
        Retrieve an experience by ID.

        Args:
            experience_id: UUID of the experience

        Returns:
            ExperienceRecord | None: The experience if found
        """
        return self.store.get_experience(experience_id)

    def add_reframing_note(
        self,
        experience_id: UUID,
        reflection: str,
        reflection_type: str = "general",
        triggered_by: str | None = None,
    ) -> ExperienceRecord | None:
        """
        Add a reframing note to an experience.

        This is the ONLY way to modify an experience after creation.

        Args:
            experience_id: UUID of the experience
            reflection: The reflection text
            reflection_type: Type of reflection
            triggered_by: What triggered this reflection

        Returns:
            ExperienceRecord | None: Updated experience if found
        """
        note = ReframingNote(
            reflection=reflection, reflection_type=reflection_type, triggered_by=triggered_by
        )

        return self.store.add_reframing_note(experience_id, note)

    def mark_accessed(self, experience_id: UUID) -> ExperienceRecord | None:
        """
        Mark an experience as accessed.

        Updates last_accessed_at and increments access_count.

        Args:
            experience_id: UUID of the experience

        Returns:
            ExperienceRecord | None: Updated experience if found
        """
        return self.store.mark_accessed(experience_id)

    def calculate_current_salience(
        self, experience_id: UUID, decay_lambda: float = 0.1, current_time: datetime | None = None
    ) -> float | None:
        """
        Calculate current salience for an experience.

        This does NOT modify the stored experience.

        Args:
            experience_id: UUID of the experience
            decay_lambda: Decay rate parameter
            current_time: Current time for calculation

        Returns:
            float | None: Current salience if experience found, None otherwise
        """
        record = self.store.get_experience(experience_id)
        if record is None:
            return None

        return record.experience.calculate_current_salience(
            decay_lambda=decay_lambda, current_time=current_time
        )

    def search_by_session(self, session_id: UUID, limit: int = 10) -> list[ExperienceRecord]:
        """
        Search experiences by session ID.

        Args:
            session_id: UUID of the session
            limit: Maximum number of results

        Returns:
            list[ExperienceRecord]: Matching experiences
        """
        query = SessionExperienceQuery(session_id=session_id)
        return self.store.search_experiences(query=query, limit=limit)

    def search_by_values(self, values: list[str], limit: int = 10) -> list[ExperienceRecord]:
        """
        Search experiences by values touched.

        Args:
            values: List of value names to search for
            limit: Maximum number of results

        Returns:
            list[ExperienceRecord]: Matching experiences
        """
        query = ValuesTouchedQuery(values=values)
        return self.store.search_experiences(query=query, limit=limit)

    def search_by_depth(self, depth: str, limit: int = 10) -> list[ExperienceRecord]:
        """
        Search experiences by emotional depth.

        Args:
            depth: Depth level (surface, meaningful, profound)
            limit: Maximum number of results

        Returns:
            list[ExperienceRecord]: Matching experiences
        """
        query = DepthQuery(depth=depth)
        return self.store.search_experiences(query=query, limit=limit)

    def search_by_date_range(
        self, start_date: datetime, end_date: datetime, limit: int = 10
    ) -> list[ExperienceRecord]:
        """
        Search experiences by date range.

        Args:
            start_date: Start of date range
            end_date: End of date range
            limit: Maximum number of results

        Returns:
            list[ExperienceRecord]: Matching experiences
        """
        query = DateRangeQuery(start_date=start_date, end_date=end_date)
        return self.store.search_experiences(query=query, limit=limit)

    def list_recent(self, limit: int = 10) -> list[ExperienceRecord]:
        """
        List recent experiences.

        Args:
            limit: Maximum number of results

        Returns:
            list[ExperienceRecord]: Recent experiences, newest first
        """
        return self.store.list_recent_experiences(limit=limit)
