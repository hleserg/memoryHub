"""In-memory implementation of :class:`EntityRelationStore`."""

from __future__ import annotations

import threading
from uuid import UUID

from typing_extensions import override

from atman.core.models.entity import EntityRelation
from atman.core.ports.entity_relation_store import EntityRelationStore


def _dedup_key(rel: EntityRelation) -> tuple:
    return (
        rel.agent_id,
        rel.from_entity_id,
        rel.to_entity_id,
        rel.relation_type,
        rel.learned_by,
    )


class InMemoryEntityRelationStore(EntityRelationStore):
    """Thread-safe in-memory store with upsert-by-(agent, pair, type, learned_by)."""

    def __init__(self) -> None:
        self._by_key: dict[tuple, EntityRelation] = {}
        self._lock = threading.Lock()

    @override
    def add_relation(self, relation: EntityRelation) -> EntityRelation:
        key = _dedup_key(relation)
        with self._lock:
            existing = self._by_key.get(key)
            if existing is None:
                self._by_key[key] = relation
                return relation
            # Upsert: bump confidence to the higher of the two; keep the
            # original id so callers can detect "we already had this".
            new_conf = max(existing.confidence, relation.confidence)
            updated = existing.model_copy(update={"confidence": new_conf})
            self._by_key[key] = updated
            return updated

    @override
    def list_for_agent(
        self,
        agent_id: UUID,
        *,
        learned_by: str | None = None,
        limit: int = 200,
    ) -> list[EntityRelation]:
        with self._lock:
            out = [r for r in self._by_key.values() if r.agent_id == agent_id]
        if learned_by is not None:
            out = [r for r in out if r.learned_by == learned_by]
        return out[:limit]

    @override
    def find_between(
        self,
        agent_id: UUID,
        from_entity_id: UUID,
        to_entity_id: UUID,
    ) -> list[EntityRelation]:
        with self._lock:
            return [
                r
                for r in self._by_key.values()
                if r.agent_id == agent_id
                and r.from_entity_id == from_entity_id
                and r.to_entity_id == to_entity_id
            ]
