"""
In-memory implementation of ReflectionStore.

This adapter implements the ReflectionStore port using an in-memory dictionary.
It's useful for testing and development without requiring a PostgreSQL instance.

RLS (Row-Level Security) is simulated by filtering on agent_id when a current
agent context is set.
"""

from datetime import datetime
from threading import Lock
from uuid import UUID

from atman.core.models.reflection import ReflectionLevel, ReflectionRecord
from atman.core.ports.reflection_store import ReflectionStore


class InMemoryReflectionStore(ReflectionStore):
    """
    In-memory implementation of ReflectionStore.

    Stores reflections in a dictionary indexed by BIGSERIAL-like integer IDs.
    Simulates PostgreSQL BIGSERIAL auto-increment behavior.

    Thread-safe for concurrent access.
    """

    def __init__(self) -> None:
        """Initialize empty in-memory store."""
        self._reflections: dict[int, ReflectionRecord] = {}
        self._next_id: int = 1
        self._lock = Lock()
        self._current_agent_id: UUID | None = None

    def set_current_agent(self, agent_id: UUID | None) -> None:
        """
        Set current agent context for RLS simulation.

        When set, list operations filter by agent_id.
        This simulates PostgreSQL RLS policy:
        `agent_id = NULLIF(current_setting('atman.current_agent', TRUE), '')::UUID`

        Args:
            agent_id: Agent UUID to filter by, or None to clear filter
        """
        self._current_agent_id = agent_id

    def add(self, record: ReflectionRecord) -> ReflectionRecord:
        """
        Add a new reflection record.

        Assigns a new id (simulating BIGSERIAL), stores the record,
        and returns the record with id populated.

        Args:
            record: ReflectionRecord to store (id field ignored if set)

        Returns:
            ReflectionRecord with id field populated
        """
        with self._lock:
            new_id = self._next_id
            self._next_id += 1

            # Create a new record with assigned ID
            stored_record = ReflectionRecord(
                id=new_id,
                agent_id=record.agent_id,
                level=record.level,
                created_at=record.created_at,
                session_id=record.session_id,
                period_start=record.period_start,
                period_end=record.period_end,
                content=record.content,
                summary=record.summary,
                experience_refs=record.experience_refs,
                reframing_note_ids=record.reframing_note_ids,
                model_provider=record.model_provider,
                model_name=record.model_name,
                schema_version=record.schema_version,
                metadata=record.metadata,
            )

            self._reflections[new_id] = stored_record
            return stored_record

    def get(self, reflection_id: int) -> ReflectionRecord | None:
        """
        Retrieve a reflection by its ID.

        Applies RLS filter (agent_id must match current agent if set),
        matching PostgreSQL RLS behavior where USING policy applies to
        all SELECT queries.

        Args:
            reflection_id: Database ID

        Returns:
            ReflectionRecord if found, None otherwise
        """
        with self._lock:
            record = self._reflections.get(reflection_id)
            if record is None:
                return None
            if self._current_agent_id is not None and record.agent_id != self._current_agent_id:
                return None
            return record

    def list_by_session(self, session_id: UUID) -> list[ReflectionRecord]:
        """
        List all reflections for a specific session.

        Returns only reflections matching both:
        - session_id matches (typically level=micro)
        - agent_id matches current agent (if RLS context is set)

        Args:
            session_id: Session UUID

        Returns:
            List of ReflectionRecord (ordered by created_at DESC)
        """
        with self._lock:
            results = [
                r
                for r in self._reflections.values()
                if r.session_id == session_id
                and (self._current_agent_id is None or r.agent_id == self._current_agent_id)
            ]
            return sorted(results, key=lambda r: r.created_at, reverse=True)

    def list_recent(self, agent_id: UUID, limit: int = 10) -> list[ReflectionRecord]:
        """
        List most recent reflections for an agent.

        Applies RLS filter (agent_id must match current agent if set).

        Args:
            agent_id: Agent UUID
            limit: Maximum number of records to return

        Returns:
            List of ReflectionRecord (ordered by created_at DESC, newest first)
        """
        with self._lock:
            results = [
                r
                for r in self._reflections.values()
                if r.agent_id == agent_id
                and (self._current_agent_id is None or r.agent_id == self._current_agent_id)
            ]
            sorted_results = sorted(results, key=lambda r: r.created_at, reverse=True)
            return sorted_results[:limit]

    def list_by_level(
        self, agent_id: UUID, level: ReflectionLevel, since: datetime | None = None
    ) -> list[ReflectionRecord]:
        """
        List reflections at a specific level for an agent.

        Applies RLS filter and optional time filter.

        Args:
            agent_id: Agent UUID
            level: Reflection level (micro/daily/deep)
            since: Optional cutoff; only return reflections created_at >= since

        Returns:
            List of ReflectionRecord (ordered by created_at DESC)
        """
        with self._lock:
            results = [
                r
                for r in self._reflections.values()
                if r.agent_id == agent_id
                and r.level == level
                and (self._current_agent_id is None or r.agent_id == self._current_agent_id)
                and (since is None or r.created_at >= since)
            ]
            return sorted(results, key=lambda r: r.created_at, reverse=True)

    def list_by_experience(self, experience_id: UUID) -> list[ReflectionRecord]:
        """
        List all reflections that analyzed a specific experience.

        Uses array containment check on experience_refs.
        Applies RLS filter.

        Args:
            experience_id: Experience UUID

        Returns:
            List of ReflectionRecord that reference this experience
        """
        with self._lock:
            results = [
                r
                for r in self._reflections.values()
                if experience_id in r.experience_refs
                and (self._current_agent_id is None or r.agent_id == self._current_agent_id)
            ]
            return sorted(results, key=lambda r: r.created_at, reverse=True)

    def clear(self) -> None:
        """Clear all stored reflections (for testing)."""
        with self._lock:
            self._reflections.clear()
            self._next_id = 1
