"""In-memory EntityRegistry adapter — for tests and local runs."""

import math
import threading
from datetime import UTC, datetime
from uuid import UUID

from typing_extensions import override

from atman.core.models.entity import Entity, EntityAlias, EntityType, ResolutionMethod
from atman.core.ports.entity_registry import EntityRegistry


class InMemoryEntityRegistry(EntityRegistry):
    """Thread-safe in-memory implementation of EntityRegistry.

    Suitable for unit tests and local runs where persistence is not required.
    All data is lost when the process exits.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entities: dict[UUID, Entity] = {}
        # keyed by entity_id
        self._aliases: dict[UUID, list[EntityAlias]] = {}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b, strict=False))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        return dot / (na * nb) if na and nb else 0.0

    def _all_aliases_for_entity(self, entity_id: UUID) -> list[EntityAlias]:
        return self._aliases.get(entity_id, [])

    def _find_entity_by_exact(
        self,
        agent_id: UUID,
        name: str,
        entity_type: EntityType | None = None,
    ) -> Entity | None:
        """L1: scan canonical names and aliases for exact (case-insensitive) match."""
        needle = name.strip().lower()
        for entity in self._entities.values():
            if entity.agent_id != agent_id:
                continue
            if entity_type is not None and entity.entity_type != entity_type:
                continue
            if entity.canonical_name.lower() == needle:
                return entity
            for alias in self._all_aliases_for_entity(entity.id):
                if alias.alias_text == needle:
                    return entity
        return None

    def _find_entity_by_embedding(
        self,
        agent_id: UUID,
        embedding: list[float],
        entity_type: EntityType | None = None,
        threshold: float = 0.85,
    ) -> Entity | None:
        """L2: return best-matching entity by cosine similarity, or None if below threshold."""
        best_entity: Entity | None = None
        best_score = -1.0
        for entity in self._entities.values():
            if entity.agent_id != agent_id:
                continue
            if entity_type is not None and entity.entity_type != entity_type:
                continue
            if entity.embedding is None:
                continue
            score = self._cosine(embedding, entity.embedding)
            if score > best_score:
                best_score = score
                best_entity = entity
        if best_entity is not None and best_score >= threshold:
            return best_entity
        return None

    # ------------------------------------------------------------------
    # EntityRegistry interface
    # ------------------------------------------------------------------

    @override
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
        with self._lock:
            # L1 — exact name / alias match
            candidates = [canonical_name]
            if alias_text:
                candidates.append(alias_text)
            for candidate in candidates:
                entity = self._find_entity_by_exact(agent_id, candidate, entity_type)
                if entity is not None:
                    # Register alias if provided and not already present
                    if alias_text and alias_text.strip().lower() != entity.canonical_name.lower():
                        self._add_alias_internal(
                            entity,
                            alias_text,
                            learned_from_fact_id=learned_from_fact_id,
                        )
                    return entity, ResolutionMethod.L1_exact

            # L2 — embedding similarity
            if embedding is not None:
                entity = self._find_entity_by_embedding(agent_id, embedding, entity_type)
                if entity is not None:
                    if alias_text and alias_text.strip().lower() != entity.canonical_name.lower():
                        self._add_alias_internal(
                            entity,
                            alias_text,
                            learned_from_fact_id=learned_from_fact_id,
                        )
                    return entity, ResolutionMethod.L2_embedding

            # L3 — create new entity
            entity = Entity(
                agent_id=agent_id,
                canonical_name=canonical_name,
                entity_type=entity_type,
                description=description,
                embedding=embedding,
            )
            self._entities[entity.id] = entity
            self._aliases[entity.id] = []

            if alias_text and alias_text.strip().lower() != canonical_name.strip().lower():
                self._add_alias_internal(
                    entity,
                    alias_text,
                    learned_from_fact_id=learned_from_fact_id,
                )

            return entity, ResolutionMethod.L3_new

    def _add_alias_internal(
        self,
        entity: Entity,
        alias_text: str,
        *,
        learned_from_fact_id: UUID | None = None,
    ) -> EntityAlias:
        """Add alias without acquiring lock (caller must hold it)."""
        normalised = alias_text.strip().lower()
        existing_list = self._aliases.setdefault(entity.id, [])
        for existing in existing_list:
            if existing.alias_text == normalised:
                return existing
        alias = EntityAlias(
            entity_id=entity.id,
            agent_id=entity.agent_id,
            alias_text=alias_text,  # constructor normalises via validator
            learned_from_fact_id=learned_from_fact_id,
        )
        existing_list.append(alias)
        return alias

    @override
    def get_entity(self, entity_id: UUID) -> Entity | None:
        with self._lock:
            return self._entities.get(entity_id)

    @override
    def find_by_name(
        self,
        agent_id: UUID,
        name: str,
        entity_type: EntityType | None = None,
    ) -> list[Entity]:
        needle = name.strip().lower()
        results: list[Entity] = []
        with self._lock:
            seen: set[UUID] = set()
            for entity in self._entities.values():
                if entity.agent_id != agent_id:
                    continue
                if entity_type is not None and entity.entity_type != entity_type:
                    continue
                if entity.id in seen:
                    continue
                matched = entity.canonical_name.lower() == needle
                if not matched:
                    for alias in self._all_aliases_for_entity(entity.id):
                        if alias.alias_text == needle:
                            matched = True
                            break
                if matched:
                    results.append(entity)
                    seen.add(entity.id)
        return results

    @override
    def add_alias(
        self,
        entity_id: UUID,
        alias_text: str,
        *,
        learned_from_fact_id: UUID | None = None,
    ) -> EntityAlias:
        with self._lock:
            entity = self._entities.get(entity_id)
            if entity is None:
                raise KeyError(f"Entity {entity_id} not found")
            return self._add_alias_internal(
                entity,
                alias_text,
                learned_from_fact_id=learned_from_fact_id,
            )

    @override
    def merge_entities(
        self,
        source_id: UUID,
        target_id: UUID,
        *,
        reason: str,
    ) -> Entity:
        with self._lock:
            source = self._entities.get(source_id)
            target = self._entities.get(target_id)
            if source is None:
                raise KeyError(f"Source entity {source_id} not found")
            if target is None:
                raise KeyError(f"Target entity {target_id} not found")

            # Transfer all aliases from source to target
            for alias in self._aliases.get(source_id, []):
                normalised = alias.alias_text  # already normalised
                target_aliases = self._aliases.setdefault(target_id, [])
                already_present = any(a.alias_text == normalised for a in target_aliases)
                if not already_present:
                    new_alias = EntityAlias(
                        entity_id=target_id,
                        agent_id=target.agent_id,
                        alias_text=alias.alias_text,
                        learned_from_fact_id=alias.learned_from_fact_id,
                        learned_at=alias.learned_at,
                    )
                    target_aliases.append(new_alias)

            # Mark source as needing disambiguation
            source.needs_disambiguation = True

            # Accumulate mention counts
            target.mention_count += source.mention_count

            return target

    @override
    def update_last_seen(self, entity_id: UUID) -> None:
        with self._lock:
            entity = self._entities.get(entity_id)
            if entity is None:
                return
            entity.last_seen_at = datetime.now(UTC)
            entity.mention_count += 1

    @override
    def list_entities(
        self,
        agent_id: UUID,
        entity_type: EntityType | None = None,
        *,
        limit: int = 50,
    ) -> list[Entity]:
        with self._lock:
            results = [
                e
                for e in self._entities.values()
                if e.agent_id == agent_id and (entity_type is None or e.entity_type == entity_type)
            ]
        results.sort(key=lambda e: e.last_seen_at, reverse=True)
        return results[:limit]

    @override
    def flag_disambiguation(self, entity_id: UUID) -> None:
        with self._lock:
            entity = self._entities.get(entity_id)
            if entity is not None:
                entity.needs_disambiguation = True

    # ------------------------------------------------------------------
    # Test helpers
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Remove all entities and aliases. Useful for test isolation."""
        with self._lock:
            self._entities.clear()
            self._aliases.clear()

    def count(self) -> int:
        """Return total number of stored entities."""
        with self._lock:
            return len(self._entities)
