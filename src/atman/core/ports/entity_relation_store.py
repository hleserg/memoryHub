"""Port: EntityRelationStore — persist learned typed relations between entities.

R9 (REFLECTION_FUTURE.md §5.3): in addition to the real-time relation
extraction by mREBEL (``learned_by='factual_extraction'``), Deep reflection
synthesises higher-level relations from co-occurrence in KeyMoments
(``learned_by='reflection'``). This port stores them; the formulator
service owns the decision logic.

Idempotency: the store dedupes on ``(agent_id, from_entity_id, to_entity_id,
relation_type, learned_by)`` so re-formulation never duplicates an existing
relation row — instead it upserts higher ``confidence`` / refreshed metadata.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from atman.core.models.entity import EntityRelation


class EntityRelationStore(ABC):
    """Storage for typed binary relations between entities."""

    @abstractmethod
    def add_relation(self, relation: EntityRelation) -> EntityRelation:
        """
        Persist or upsert a relation.

        Implementations must dedupe by ``(agent_id, from_entity_id,
        to_entity_id, relation_type, learned_by)`` so repeated formulation
        cycles never duplicate the same edge. On a duplicate, return the
        stored row (potentially with bumped ``confidence``); callers compare
        ``relation.id`` to detect upsert vs. insert.
        """

    @abstractmethod
    def list_for_agent(
        self,
        agent_id: UUID,
        *,
        learned_by: str | None = None,
        limit: int = 200,
    ) -> list[EntityRelation]:
        """List relations for ``agent_id`` (filterable by ``learned_by``)."""

    @abstractmethod
    def find_between(
        self,
        agent_id: UUID,
        from_entity_id: UUID,
        to_entity_id: UUID,
    ) -> list[EntityRelation]:
        """Return all stored relations between a given ordered pair."""
