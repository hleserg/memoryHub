"""
EntityRelationsFormulator — R9 service (REFLECTION_FUTURE.md §5.3).

Deep-reflection-only. Builds a co-occurrence index from
:meth:`StateStore.find_moments_by_entity` for the agent's entities, then
for each pair with co-occurrence ≥ ``min_cooccurrences`` asks the LLM via
:meth:`ReflectionModel.formulate_entity_relation` whether there is a
meaningful typed relation. Confirmed relations are persisted through
:class:`EntityRelationStore` as ``learned_by='reflection'``.

Coexists with real-time mREBEL extraction (which writes
``learned_by='factual_extraction'`` and / or ``learned_by='mrebel'``):
the store dedups by ``(agent_id, from, to, type, learned_by)`` so both
sources can produce the same relation_type without overwriting each
other's confidence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from itertools import combinations
from uuid import UUID

from atman.core.models.entity import Entity, EntityRelation
from atman.core.models.experience import KeyMoment
from atman.core.ports.entity_registry import EntityRegistry
from atman.core.ports.entity_relation_store import EntityRelationStore
from atman.core.ports.reflection import ReflectionModel
from atman.core.ports.state_store import StateStore

logger = logging.getLogger(__name__)

DEFAULT_MIN_COOCCURRENCES: int = 3
DEFAULT_MIN_CONFIDENCE: float = 0.7
LEARNED_BY_REFLECTION: str = "reflection"


@dataclass
class RelationFormulationOutcome:
    """Summary of one Deep relation-formulation pass."""

    formulated: int
    """New / refreshed relations persisted this pass."""
    skipped: int
    """Pairs where the LLM declined or confidence was below threshold."""
    pairs_considered: int
    """Pairs that met the co-occurrence threshold."""


def _index_entities_by_moment(
    state_store: StateStore, entities: list[Entity], moment_limit: int = 200
) -> dict[UUID, set[UUID]]:
    """Build a ``moment_id -> set(entity_id)`` index from the state store."""
    by_moment: dict[UUID, set[UUID]] = {}
    for entity in entities:
        try:
            moments = state_store.find_moments_by_entity(entity.id, limit=moment_limit)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "entity_relations: find_moments_by_entity(%s) failed: %s",
                entity.id,
                exc,
            )
            continue
        for m in moments:
            by_moment.setdefault(m.id, set()).add(entity.id)
    return by_moment


def _collect_pair_cooccurrences(
    by_moment: dict[UUID, set[UUID]],
    moment_lookup: dict[UUID, KeyMoment],
    *,
    min_cooccurrences: int,
) -> dict[tuple[UUID, UUID], list[KeyMoment]]:
    """Return ``(entity_a_id, entity_b_id) -> [shared moments]`` for pairs ≥ threshold."""
    pair_to_moments: dict[tuple[UUID, UUID], list[KeyMoment]] = {}
    for moment_id, entity_set in by_moment.items():
        if len(entity_set) < 2:
            continue
        moment = moment_lookup.get(moment_id)
        if moment is None:
            continue
        for a, b in combinations(sorted(entity_set, key=str), 2):
            pair_to_moments.setdefault((a, b), []).append(moment)
    return {
        pair: moments
        for pair, moments in pair_to_moments.items()
        if len(moments) >= min_cooccurrences
    }


class EntityRelationsFormulator:
    """
    Deep-reflection service: emit ``learned_by='reflection'`` relations from
    co-occurrence patterns.
    """

    def __init__(
        self,
        state_store: StateStore,
        entity_registry: EntityRegistry,
        relation_store: EntityRelationStore,
        reflection_model: ReflectionModel,
        *,
        min_cooccurrences: int = DEFAULT_MIN_COOCCURRENCES,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
        moment_limit: int = 200,
    ) -> None:
        self.state_store = state_store
        self.entity_registry = entity_registry
        self.relation_store = relation_store
        self.reflection_model = reflection_model
        self.min_cooccurrences = min_cooccurrences
        self.min_confidence = min_confidence
        self.moment_limit = moment_limit

    def run(self, agent_id: UUID) -> RelationFormulationOutcome:
        """
        Compute pairs, ask the LLM per pair, persist confirmed relations.

        Returns a summary; the surrounding Deep job uses it for `notes`.
        """
        entities = list(self.entity_registry.list_entities(agent_id=agent_id, limit=500))
        if len(entities) < 2:
            return RelationFormulationOutcome(0, 0, 0)
        entity_by_id = {e.id: e for e in entities}

        by_moment = _index_entities_by_moment(
            self.state_store, entities, moment_limit=self.moment_limit
        )
        # Build a (moment_id -> KeyMoment) lookup from the same fetch so we
        # can pass full KeyMoment objects to the LLM without re-querying.
        moment_lookup: dict[UUID, KeyMoment] = {}
        for entity in entities:
            try:
                moments = self.state_store.find_moments_by_entity(
                    entity.id, limit=self.moment_limit
                )
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "entity_relations: re-fetch moments(%s) failed: %s",
                    entity.id,
                    exc,
                )
                moments = []
            for m in moments:
                moment_lookup.setdefault(m.id, m)

        pairs = _collect_pair_cooccurrences(
            by_moment, moment_lookup, min_cooccurrences=self.min_cooccurrences
        )

        formulated = 0
        skipped = 0
        for (a_id, b_id), shared_moments in sorted(
            pairs.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1]))
        ):
            entity_a = entity_by_id.get(a_id)
            entity_b = entity_by_id.get(b_id)
            if entity_a is None or entity_b is None:
                skipped += 1
                continue
            shared_moments_sorted = sorted(shared_moments, key=lambda m: (m.when, str(m.id)))
            output = self.reflection_model.formulate_entity_relation(
                entity_a, entity_b, shared_moments_sorted
            )
            relation_type = output.relation_type.strip() if output.relation_type else ""
            if not relation_type:
                skipped += 1
                continue
            if output.confidence < self.min_confidence:
                skipped += 1
                continue

            try:
                self.relation_store.add_relation(
                    EntityRelation(
                        agent_id=agent_id,
                        from_entity_id=a_id,
                        to_entity_id=b_id,
                        relation_type=relation_type,
                        confidence=output.confidence,
                        learned_by=LEARNED_BY_REFLECTION,
                    )
                )
                formulated += 1
            except Exception as exc:
                logger.warning(
                    "entity_relations: add_relation for (%s, %s) failed: %s",
                    a_id,
                    b_id,
                    exc,
                )
                skipped += 1

        return RelationFormulationOutcome(
            formulated=formulated, skipped=skipped, pairs_considered=len(pairs)
        )
