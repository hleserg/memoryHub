"""
Port interface for reflection persistence (PostgreSQL reflections table).

This port defines the contract for storing and retrieving reflections
from the `public.reflections` table. It is separate from ReflectionEventStore
(which stores in-memory reflection events).

The ReflectionStore is used by:
- OllamaReflectionModel (write generated reflections)
- Micro/Daily/DeepReflectionService (write reflection outputs)
- E0.3 eval scripts (read reflections for quality assessment)
"""

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from atman.core.models.reflection import ReflectionLevel, ReflectionRecord


class ReflectionStore(ABC):
    """
    Storage port for reflections table (PostgreSQL).

    Reflections are append-only records of micro/daily/deep reflection
    processes. They reference experiences, create reframing notes, and
    capture the LLM-generated reflection content.
    """

    @abstractmethod
    def add(self, record: ReflectionRecord) -> ReflectionRecord:
        """
        Add a new reflection record to storage.

        Args:
            record: ReflectionRecord to store (id field ignored if set; DB assigns BIGSERIAL)

        Returns:
            ReflectionRecord with id field populated by database

        Raises:
            ValueError: if record validation fails
            StorageError: if database operation fails
        """
        ...

    @abstractmethod
    def get(self, reflection_id: int) -> ReflectionRecord | None:
        """
        Retrieve a reflection by its database ID.

        Args:
            reflection_id: Database ID (BIGSERIAL primary key)

        Returns:
            ReflectionRecord if found, None otherwise
        """
        ...

    @abstractmethod
    def list_by_session(self, session_id: UUID) -> list[ReflectionRecord]:
        """
        List all reflections for a specific session.

        Typically returns 0 or 1 record (micro reflection for that session).

        Args:
            session_id: Session UUID

        Returns:
            List of ReflectionRecord (ordered by created_at DESC)
        """
        ...

    @abstractmethod
    def list_recent(self, agent_id: UUID, limit: int = 10) -> list[ReflectionRecord]:
        """
        List most recent reflections for an agent (any level).

        Args:
            agent_id: Agent UUID
            limit: Maximum number of records to return (default 10)

        Returns:
            List of ReflectionRecord (ordered by created_at DESC, newest first)
        """
        ...

    @abstractmethod
    def list_by_level(
        self, agent_id: UUID, level: ReflectionLevel, since: datetime | None = None
    ) -> list[ReflectionRecord]:
        """
        List reflections at a specific level for an agent.

        Args:
            agent_id: Agent UUID
            level: Reflection level (micro/daily/deep)
            since: Optional cutoff timestamp; only return reflections created_at >= since

        Returns:
            List of ReflectionRecord (ordered by created_at DESC, newest first)
        """
        ...

    @abstractmethod
    def list_by_experience(self, experience_id: UUID) -> list[ReflectionRecord]:
        """
        List all reflections that analyzed a specific experience.

        Uses GIN index on experience_refs array.

        Args:
            experience_id: Experience UUID

        Returns:
            List of ReflectionRecord that reference this experience
        """
        ...
