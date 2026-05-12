"""
In-memory adapter for experience storage.

Stores experiences in memory - useful for testing and development.
Not persistent - all data is lost when the process exits.
"""

from uuid import UUID

from atman.core.models import ExperienceRecord, KeyMoment, ReframingNote
from atman.core.ports import (
    DateRangeQuery,
    DepthQuery,
    ExperienceQuery,
    FactRefsContainsQuery,
    SessionExperienceQuery,
    StateStore,
    ValuesTouchedQuery,
)


class InMemoryExperienceStore(StateStore):
    """
    In-memory implementation of StateStore.

    Stores experiences in a dictionary in memory.
    Fast and simple, but not persistent.
    """

    def __init__(self):
        """Initialize in-memory experience store."""
        self._experiences: dict[UUID, ExperienceRecord] = {}
        self._key_moments: dict[UUID, KeyMoment] = {}

    def create_experience(self, record: ExperienceRecord) -> ExperienceRecord:
        """Create a new experience in storage."""
        if record.experience.id in self._experiences:
            raise ValueError(f"Experience with id {record.experience.id} already exists")

        self._experiences[record.experience.id] = record
        return record

    def get_experience(self, experience_id: UUID) -> ExperienceRecord | None:
        """Retrieve an experience by its ID."""
        return self._experiences.get(experience_id)

    def add_reframing_note(
        self, experience_id: UUID, note: ReframingNote
    ) -> ExperienceRecord | None:
        """Add a reframing note to an existing experience."""
        if experience_id not in self._experiences:
            return None

        record = self._experiences[experience_id]
        if note.triggered_by and any(
            n.triggered_by == note.triggered_by for n in record.experience.reframing_notes
        ):
            return record

        record.experience.add_reframing_note(note)

        return record

    def mark_accessed(self, experience_id: UUID) -> ExperienceRecord | None:
        """Mark an experience as accessed."""
        if experience_id not in self._experiences:
            return None

        record = self._experiences[experience_id]
        record.experience.mark_accessed()

        return record

    def search_experiences(
        self, query: ExperienceQuery | None = None, limit: int = 10
    ) -> list[ExperienceRecord]:
        """Search for experiences matching a query."""
        results: list[ExperienceRecord] = []

        for record in self._experiences.values():
            if self._matches_query(record, query):
                results.append(record)

        # Sort by timestamp, newest first
        results.sort(key=lambda r: r.experience.timestamp, reverse=True)

        return results[:limit]

    def _matches_query(self, record: ExperienceRecord, query: ExperienceQuery | None) -> bool:
        """
        Check if a record matches the given query.

        Args:
            record: The experience record to check
            query: The query to match against

        Returns:
            bool: True if the record matches the query
        """
        if query is None:
            return True

        exp = record.experience

        if isinstance(query, SessionExperienceQuery):
            return exp.session_id == query.session_id

        elif isinstance(query, ValuesTouchedQuery):
            for moment_id in exp.key_moment_ids:
                moment = self._key_moments.get(moment_id)
                if moment and any(qv in moment.values_touched for qv in query.values):
                    return True
            return False

        elif isinstance(query, DepthQuery):
            for moment_id in exp.key_moment_ids:
                moment = self._key_moments.get(moment_id)
                if moment and moment.how_i_felt.depth.value == query.depth:
                    return True
            return False

        elif isinstance(query, DateRangeQuery):
            return query.start_date <= exp.timestamp <= query.end_date

        elif isinstance(query, FactRefsContainsQuery):
            # Fetch key moments and check fact_refs
            for moment_id in exp.key_moment_ids:
                moment = self._key_moments.get(moment_id)
                if moment and query.fact_id in moment.fact_refs:
                    return True
            return False

        return False

    def list_recent_experiences(self, limit: int = 10) -> list[ExperienceRecord]:
        """List the most recent experiences."""
        results = list(self._experiences.values())
        results.sort(key=lambda r: r.experience.timestamp, reverse=True)

        return results[:limit]

    def store_key_moments(self, session_id: UUID, moments: list[KeyMoment]) -> None:
        """Store key moments for a session."""
        for moment in moments:
            self._key_moments[moment.id] = moment

    def get_key_moment(self, moment_id: UUID) -> KeyMoment | None:
        """Retrieve a key moment by its ID."""
        return self._key_moments.get(moment_id)

    def get_key_moments_for_session(self, session_id: UUID) -> list[KeyMoment]:
        """Retrieve all key moments for a session."""
        # Find the experience for this session
        for exp_record in self._experiences.values():
            if exp_record.experience.session_id == session_id:
                result = []
                for moment_id in exp_record.experience.key_moment_ids:
                    moment = self._key_moments.get(moment_id)
                    if moment:
                        result.append(moment)
                return result
        return []

    def clear(self) -> None:
        """Clear all experiences from storage (useful for testing)."""
        self._experiences.clear()
        self._key_moments.clear()

    def count(self) -> int:
        """Return the number of experiences in storage."""
        return len(self._experiences)

    # Identity Store operations (not implemented - for compatibility)

    def load_identity(self, agent_id) -> None:  # type: ignore
        """Not implemented - use FileStateStore for identity operations."""
        raise NotImplementedError("Identity operations not supported in InMemoryExperienceStore")

    def save_identity(self, identity, expected_version=None):  # type: ignore
        """Not implemented - use FileStateStore for identity operations."""
        raise NotImplementedError("Identity operations not supported in InMemoryExperienceStore")

    def create_identity_snapshot(self, snapshot):  # type: ignore
        """Not implemented - use FileStateStore for identity operations."""
        raise NotImplementedError("Identity operations not supported in InMemoryExperienceStore")

    def list_identity_snapshots(self, identity_id, limit=10):  # type: ignore
        """Not implemented - use FileStateStore for identity operations."""
        raise NotImplementedError("Identity operations not supported in InMemoryExperienceStore")

    def load_narrative(self, identity_id):  # type: ignore
        """Not implemented - use FileStateStore for narrative operations."""
        raise NotImplementedError("Narrative operations not supported in InMemoryExperienceStore")

    def save_narrative(self, narrative, expected_version=None, expected_updated_at=None):  # type: ignore
        """Not implemented - use FileStateStore for narrative operations."""
        raise NotImplementedError("Narrative operations not supported in InMemoryExperienceStore")

    def archive_narrative(self, narrative_id, reason):  # type: ignore
        """Not implemented - use FileStateStore for narrative operations."""
        raise NotImplementedError("Narrative operations not supported in InMemoryExperienceStore")

    def list_archived_narratives(self, identity_id, limit=10):  # type: ignore
        """Not implemented - use FileStateStore for narrative operations."""
        raise NotImplementedError("Narrative operations not supported in InMemoryExperienceStore")

    def save_eigenstate(self, eigenstate):  # type: ignore
        """Not implemented - use FileStateStore for eigenstate operations."""
        raise NotImplementedError("Eigenstate operations not supported in InMemoryExperienceStore")

    def load_latest_eigenstate(self, session_id=None, identity_id=None):  # type: ignore
        """Not implemented - use FileStateStore for eigenstate operations."""
        raise NotImplementedError("Eigenstate operations not supported in InMemoryExperienceStore")

    # KeyMoment operations (not implemented - for compatibility)

    def create_key_moment(self, key_moment):  # type: ignore
        """Not implemented - use FileStateStore for key moment operations."""
        raise NotImplementedError("KeyMoment operations not supported in InMemoryExperienceStore")

    def list_key_moments(self, session_id=None):  # type: ignore
        """Not implemented - use FileStateStore for key moment operations."""
        raise NotImplementedError("KeyMoment operations not supported in InMemoryExperienceStore")

    def get_key_moment(self, key_moment_id):  # type: ignore
        """Not implemented - use FileStateStore for key moment operations."""
        raise NotImplementedError("KeyMoment operations not supported in InMemoryExperienceStore")
