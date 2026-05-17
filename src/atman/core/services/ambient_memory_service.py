"""AmbientMemoryService — entity-anchor parallel RAG injection (HLE-33).

Plan §6 "Ambient anchor + ассоциативный RAG" + §7 "Stance превалирует" +
§12 шаги (c-f). The existing :class:`PassiveMemoryInjector` only knows
dense embedding similarity (with optional BM25 fusion + reranker); this
service adds the **entity-anchor** side: for each ambient anchor in the
incoming user message, fan out a backend query keyed on the resolved
entity id, fold the populated `EntityStance` for that entity in on top,
and merge everything before token-budget capping.

Pipeline (plan §12 c-f):
  c) ``LinguisticAnalyzer.analyze_user_message(text)`` →
     :class:`UserMessageAnalysis` with ``anchors`` and ``entities``.
  d) For each biographical anchor (topic/person/place/object/event):
     * resolve the entity via :class:`EntityRegistry.find_by_name` (read-only;
       creation belongs in the live-write path).
     * pull ``FactualMemory.find_facts_by_entity(entity_id)``.
     * pull ``StateStore.find_moments_by_entity(entity_id)``.
     * fetch the active :class:`EntityStance` for that entity if any.
  e) Salience-aware ranking on moments per plan §8:
     ``salience * 0.4 + emotional_intensity * 0.3 + recency * 0.3``.
  f) Stances always sort to the top (plan §7 "сознательное отношение
     превалирует над эпизодами").

Outputs a list of :class:`AmbientSurfaceItem` items, capped by
``token_budget`` so the caller can hand them straight to the message
composer without re-running token estimation. Used moments are
``mark_accessed``'d via :class:`SalienceDecayService` so the salience
loop reflects retrieval.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from atman.core.models.entity import Entity, EntityStance
    from atman.core.models.experience import KeyMoment
    from atman.core.models.fact import FactRecord
    from atman.core.ports.entity_registry import EntityRegistry
    from atman.core.ports.entity_stance import EntityStanceStore
    from atman.core.ports.linguistic import (
        AmbientAnchor,
        LinguisticAnalyzer,
        UserMessageAnalysis,
    )
    from atman.core.ports.memory_backend import FactualMemory
    from atman.core.ports.salience_decay import SalienceDecayService
    from atman.core.ports.state_store import StateStore

_LOG = logging.getLogger(__name__)

# Anchor types from `AmbientAnchor.anchor_type` that resolve to a stored
# entity in the registry (and therefore can drive a per-entity backend
# query). Action / emotion / time refs are handled by the dense pipeline.
_BIOGRAPHICAL_ANCHOR_TYPES = frozenset({"person_ref", "topic", "location", "object_ref"})


# PLAYBOOK-START
# id: entity-anchor-parallel-rag
# category: design-patterns
# title: Entity-Anchor Parallel RAG with Stance-First Ordering
# status: draft
# since: 2026-05-17
#
# Pattern: when the dense retriever doesn't know "this is a person we have
# stored history on", anchor the retrieval on entity ids extracted from
# the user message. For each anchor type that maps to a known registry
# entity, fan out a per-entity query against the structured stores
# (moments + facts + stance) rather than relying purely on vector recall.
# A stable "stance precedes evidence" ordering rule then puts the agent's
# considered position on top of the raw episodes.
#
# Why generalizable: dense vector recall is symptomatic — entities are
# the ontology. Anchoring retrieval on entity ids gives perfect recall
# inside the structured store at the cost of one NER pass; the dense
# layer still picks up everything else.
# PLAYBOOK-END


@dataclass(frozen=True)
class AmbientSurfaceItem:
    """A single item surfaced by :class:`AmbientMemoryService`.

    The ``kind`` field stays a string (not an enum) so adding new
    categories doesn't require touching this domain primitive — the
    composer cares only about the payload.
    """

    kind: str  # "stance" | "moment" | "fact"
    payload: Any
    score: float
    anchor_text: str | None = None
    entity_id: UUID | None = None


@dataclass(frozen=True)
class AmbientResult:
    """The full output of :meth:`AmbientMemoryService.compose_injection`."""

    items: list[AmbientSurfaceItem]
    tokens_used: int = 0


def _moment_score(moment: KeyMoment, *, now: datetime, recency_window_days: int) -> float:
    """Salience-aware composite score per plan §8.

    ``salience * 0.4 + emotional_intensity * 0.3 + recency * 0.3`` where
    recency decays linearly across ``recency_window_days`` from `moment.when`.
    """
    salience = float(getattr(moment, "salience", 0.5) or 0.0)
    intensity = float(
        getattr(getattr(moment, "how_i_felt", None), "emotional_intensity", 0.0) or 0.0
    )
    when = getattr(moment, "when", None)
    if isinstance(when, datetime):
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        age_days = max(0.0, (now - when).total_seconds() / 86400.0)
        recency = max(0.0, 1.0 - age_days / float(max(1, recency_window_days)))
    else:
        recency = 0.0
    return salience * 0.4 + intensity * 0.3 + recency * 0.3


def _estimate_tokens(text: str) -> int:
    """UTF-8 byte-length / 3 heuristic — same scheme as PMI's
    ``estimate_tokens`` so the two services can share a budget without
    importing each other."""
    return max(1, len(text.encode("utf-8")) // 3) if text else 0


def _item_text(item: AmbientSurfaceItem) -> str:
    """Primary text for token estimation."""
    payload = item.payload
    if item.kind == "stance":
        return getattr(payload, "stance_text", "") or ""
    if item.kind == "moment":
        what = getattr(payload, "what_happened", "") or ""
        why = getattr(payload, "why_it_matters", "") or ""
        return f"{what} {why}".strip()
    if item.kind == "fact":
        return getattr(payload, "content", "") or ""
    return ""


class AmbientMemoryService:
    """Entity-anchor parallel RAG injection (HLE-33)."""

    def __init__(
        self,
        *,
        linguistic_analyzer: LinguisticAnalyzer,
        entity_registry: EntityRegistry,
        state_store: StateStore,
        factual_memory: FactualMemory | None = None,
        entity_stance_store: EntityStanceStore | None = None,
        salience_decay: SalienceDecayService | None = None,
        moments_per_anchor: int = 5,
        facts_per_anchor: int = 5,
        recency_window_days: int = 30,
        token_budget: int = 2000,
    ) -> None:
        self._analyzer = linguistic_analyzer
        self._registry = entity_registry
        self._state_store = state_store
        self._facts = factual_memory
        self._stance = entity_stance_store
        self._salience = salience_decay
        self._moments_per_anchor = moments_per_anchor
        self._facts_per_anchor = facts_per_anchor
        self._recency_window_days = recency_window_days
        self._token_budget = token_budget

    def compose_injection(self, text: str, *, agent_id: UUID) -> AmbientResult:
        """Return the ranked, budget-capped ambient context for ``text``."""
        if not text or not text.strip():
            return AmbientResult(items=[], tokens_used=0)

        analysis: UserMessageAnalysis = self._analyzer.analyze_user_message(text)
        biographical = [a for a in analysis.anchors if a.anchor_type in _BIOGRAPHICAL_ANCHOR_TYPES]
        if not biographical:
            return AmbientResult(items=[], tokens_used=0)

        # Step 1 — collect per anchor
        candidates: list[AmbientSurfaceItem] = []
        seen_ids: set[tuple[str, UUID]] = set()  # (kind, payload.id) dedup
        now = datetime.now(UTC)
        for anchor in biographical:
            entity = self._resolve_anchor(anchor, agent_id=agent_id)
            if entity is None:
                continue
            # Stance — priority sentinel score so it lands on top regardless
            # of episode rankings (plan §7).
            if self._stance is not None:
                stance = self._safe_get_current_stance(agent_id, entity.id)
                if stance is not None:
                    key = ("stance", stance.id)
                    if key not in seen_ids:
                        seen_ids.add(key)
                        candidates.append(
                            AmbientSurfaceItem(
                                kind="stance",
                                payload=stance,
                                score=float("inf"),
                                anchor_text=anchor.text,
                                entity_id=entity.id,
                            )
                        )
            # Moments — salience-aware composite (§8).
            for moment in self._safe_find_moments(entity.id, limit=self._moments_per_anchor):
                key = ("moment", moment.id)
                if key in seen_ids:
                    continue
                seen_ids.add(key)
                candidates.append(
                    AmbientSurfaceItem(
                        kind="moment",
                        payload=moment,
                        score=_moment_score(
                            moment,
                            now=now,
                            recency_window_days=self._recency_window_days,
                        ),
                        anchor_text=anchor.text,
                        entity_id=entity.id,
                    )
                )
            # Facts — flat ordering by source; backend already orders by
            # whatever salience proxy it has.
            for fact in self._safe_find_facts(entity.id, limit=self._facts_per_anchor):
                key = ("fact", fact.id)
                if key in seen_ids:
                    continue
                seen_ids.add(key)
                # Facts get a uniform 0.5 — they're context, not evidence.
                candidates.append(
                    AmbientSurfaceItem(
                        kind="fact",
                        payload=fact,
                        score=0.5,
                        anchor_text=anchor.text,
                        entity_id=entity.id,
                    )
                )

        # Step 2 — order. Stances first (inf score), then moments/facts by score.
        candidates.sort(key=lambda i: (-i.score, i.kind != "stance"))

        # Step 3 — token-budget cap.
        out: list[AmbientSurfaceItem] = []
        spent = 0
        for item in candidates:
            cost = _estimate_tokens(_item_text(item))
            if spent + cost > self._token_budget and out:
                break
            out.append(item)
            spent += cost

        # Step 4 — mark_accessed for moments we actually returned.
        self._mark_used_moments(out)

        return AmbientResult(items=out, tokens_used=spent)

    # ------------------------------------------------------------------
    # safe wrappers — every backend call is wrapped because the ambient
    # path runs in the user-message hot path and must degrade rather than
    # raise on adapter issues (e.g. Postgres connectivity blip).

    def _resolve_anchor(self, anchor: AmbientAnchor, *, agent_id: UUID) -> Entity | None:
        try:
            matches = self._registry.find_by_name(agent_id, anchor.text)
        except Exception:  # pragma: no cover - defensive
            _LOG.warning("registry.find_by_name failed for %r", anchor.text, exc_info=True)
            return None
        if not matches:
            return None
        return matches[0]

    def _safe_get_current_stance(self, agent_id: UUID, entity_id: UUID) -> EntityStance | None:
        if self._stance is None:
            return None
        try:
            return self._stance.get_current_stance(agent_id, entity_id)
        except Exception:  # pragma: no cover - defensive
            _LOG.warning("stance.get_current_stance failed", exc_info=True)
            return None

    def _safe_find_moments(self, entity_id: UUID, *, limit: int) -> list[KeyMoment]:
        try:
            return list(self._state_store.find_moments_by_entity(entity_id, limit=limit))
        except Exception:
            _LOG.warning("state_store.find_moments_by_entity failed", exc_info=True)
            return []

    def _safe_find_facts(self, entity_id: UUID, *, limit: int) -> list[FactRecord]:
        if self._facts is None:
            return []
        try:
            return list(self._facts.find_facts_by_entity(entity_id, limit=limit))
        except Exception:  # pragma: no cover - defensive
            _LOG.warning("factual_memory.find_facts_by_entity failed", exc_info=True)
            return []

    def _mark_used_moments(self, items: list[AmbientSurfaceItem]) -> None:
        if self._salience is None:
            return
        for item in items:
            if item.kind != "moment":
                continue
            moment_id = getattr(item.payload, "id", None)
            if moment_id is None:
                continue
            try:
                self._salience.mark_accessed(moment_id)
            except Exception:  # pragma: no cover - defensive
                _LOG.warning("salience.mark_accessed failed for %s", moment_id, exc_info=True)
