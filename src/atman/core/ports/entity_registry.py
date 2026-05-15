"""Port: EntityRegistry — resolve, create, and manage named entities."""

from abc import ABC, abstractmethod
from uuid import UUID

from atman.core.models.entity import Entity, EntityAlias, EntityType, ResolutionMethod


class EntityRegistry(ABC):
    """Hexagonal port for entity resolution (L1→L2→L3) and lifecycle management."""

    @abstractmethod
    def resolve_or_create(
        self,
        agent_id: UUID,
        canonical_name: str,
        entity_type: EntityType,
        *,
        description: str | None = None,
        embedding: list[float] | None = None,
        alias_text: str | None = None,
        learned_from_fact_id: UUID | None = None,
    ) -> tuple[Entity, ResolutionMethod]:
        """L1→L2→L3: find existing entity or create new one.

        Resolution order:
          L1 — exact match on canonical_name or known alias (case-insensitive).
          L2 — cosine similarity of provided embedding against stored embeddings;
               succeeds when similarity ≥ configured threshold.
          L3 — no match found; a new Entity is created and persisted.

        If alias_text is provided and differs from canonical_name, the alias is
        registered against the resolved/created entity.

        Returns (entity, how_resolved).
        """

    @abstractmethod
    def get_entity(self, entity_id: UUID) -> Entity | None:
        """Return Entity by primary key, or None if not found."""

    @abstractmethod
    def find_by_name(
        self,
        agent_id: UUID,
        name: str,
        entity_type: EntityType | None = None,
    ) -> list[Entity]:
        """Alias + canonical name lookup (L1).

        Performs case-insensitive search across both canonical_name and all
        registered aliases for the given agent.  Optionally filters by
        entity_type.  Returns all matches; empty list when nothing found.
        """

    @abstractmethod
    def add_alias(
        self,
        entity_id: UUID,
        alias_text: str,
        *,
        learned_from_fact_id: UUID | None = None,
    ) -> EntityAlias:
        """Register a new alias for an existing entity.

        The alias is normalised (stripped, lowercased) before storage.
        Returns the persisted EntityAlias.
        """

    @abstractmethod
    def merge_entities(
        self,
        source_id: UUID,
        target_id: UUID,
        *,
        reason: str,
    ) -> Entity:
        """Merge source into target.

        All aliases of source are transferred to target.  source is marked
        needs_disambiguation=True so downstream systems can route queries to
        target.  Returns the updated target Entity.
        """

    @abstractmethod
    def update_last_seen(self, entity_id: UUID) -> None:
        """Increment mention_count by 1 and set last_seen_at to current UTC time."""

    @abstractmethod
    def list_entities(
        self,
        agent_id: UUID,
        entity_type: EntityType | None = None,
        *,
        limit: int = 50,
    ) -> list[Entity]:
        """Return up to limit entities for agent_id, optionally filtered by type.

        Results are ordered by last_seen_at DESC.
        """

    @abstractmethod
    def flag_disambiguation(self, entity_id: UUID) -> None:
        """Mark entity as needing human or reflection-based disambiguation.

        Sets needs_disambiguation=True on the entity record.
        """
