"""
SessionCache - per-session entity resolution and RAG result cache.

Lives exactly one session. Prevents redundant GLiNER → EntityResolver →
pgvector round-trips for entities that were already resolved or queried.

Invalidation rule: when a new fact or KeyMoment is written for entity X,
invalidate_rag(X) is called so the next RAG lookup recomputes fresh results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass
class SessionCache:
    """Per-session cache for entity resolutions and RAG results."""

    entity_resolutions: dict[str, Any] = field(default_factory=dict)
    """mention_text → resolved Entity (or None if not found)"""

    rag_results: dict[UUID, list] = field(default_factory=dict)
    """entity_id → last RAG candidates for that entity"""

    dirty_entities: set[UUID] = field(default_factory=set)
    """entity_ids whose RAG cache was invalidated due to new writes in this session"""

    def invalidate_rag(self, entity_id: UUID) -> None:
        """Mark entity_id as dirty and drop its cached RAG results."""
        self.dirty_entities.add(entity_id)
        self.rag_results.pop(entity_id, None)

    def is_rag_cached(self, entity_id: UUID) -> bool:
        """True when we have a valid (non-dirty) cached result for entity_id."""
        return entity_id not in self.dirty_entities and entity_id in self.rag_results

    def stats(self) -> dict[str, int]:
        return {
            "entity_cache_size": len(self.entity_resolutions),
            "rag_cache_size": len(self.rag_results),
            "dirty_count": len(self.dirty_entities),
        }
