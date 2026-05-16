"""Port: EntityStanceStore — manage agent's stances toward named entities."""

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from atman.core.models.entity import EntityStance


class EntityStanceStore(ABC):
    """Abstract port for persisting and querying agent stances toward entities."""

    @abstractmethod
    def get_current_stance(self, agent_id: UUID, entity_id: UUID) -> EntityStance | None:
        """Return the active (not superseded) stance, or None."""

    @abstractmethod
    def get_stance_history(self, agent_id: UUID, entity_id: UUID) -> list[EntityStance]:
        """Return all stances for entity, newest first."""

    @abstractmethod
    def write_stance(
        self,
        agent_id: UUID,
        entity_id: UUID,
        stance_text: str,
        *,
        valence: float | None = None,
        intensity: float | None = None,
        formed_in_reflection_id: UUID | None = None,
        based_on_moment_ids: list[UUID] | None = None,
        confidence: float | None = None,
        is_provisional: bool = True,
    ) -> EntityStance:
        """Create new stance, superseding any existing active stance."""

    @abstractmethod
    def supersede_stance(self, stance_id: UUID, *, superseded_by_id: UUID) -> None:
        """Mark a stance as superseded."""

    @abstractmethod
    def list_active_stances(
        self,
        agent_id: UUID,
        *,
        formed_after: datetime | None = None,
        limit: int = 50,
    ) -> list[EntityStance]:
        """List all active stances for the agent."""
