"""
EntityStanceFormulator — R7 service (REFLECTION_FUTURE.md §4.3, §5.2, §9).

Given an :class:`~atman.core.models.entity.Entity` and the
:class:`~atman.core.models.experience.KeyMoment`-s that involve it,
asks the :class:`~atman.core.ports.reflection.ReflectionModel` to put
into words how the agent currently relates to that entity, and
persists the result through :class:`~atman.core.ports.entity_stance.
EntityStanceStore`.

Design principles (§9):

* Stance is an **interpretation**, not an aggregation. No averaging of
  per-moment scalars; the LLM writes a sentence and an estimate.
* Old stance is never deleted — only ``superseded_at`` + ``superseded_by``
  (the ``EntityStanceStore`` handles this in ``write_stance``).
* ``based_on_moment_ids`` is **mandatory** — we always carry the moments
  the stance was grounded in.
* ``is_provisional=True`` on first formulation. The Deep-reflection
  pathway (``revise_stale``) is what flips a stance to non-provisional
  when re-affirmed by new moments.

Daily entry point: :meth:`formulate_for_new_entities` — runs over
entities with ≥ ``min_moments`` new moments since the last stance for
that entity.

Deep entry point: :meth:`revise_stale` — for active stances older than
``staleness_days`` whose entities have had new moments since the stance
was formed, asks the LLM to re-formulate; if the new stance is
"materially different" we write a new stance (auto-superseding the old
one); otherwise we promote the existing stance to non-provisional and
bump its ``confidence`` toward 1.0.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from atman.core.clock_impl import SystemClock
from atman.core.models.entity import Entity, EntityStance
from atman.core.models.experience import KeyMoment
from atman.core.ports.clock import ClockPort
from atman.core.ports.entity_registry import EntityRegistry
from atman.core.ports.entity_stance import EntityStanceStore
from atman.core.ports.reflection import ReflectionModel
from atman.core.ports.state_store import StateStore

logger = logging.getLogger(__name__)

DEFAULT_MIN_MOMENTS: int = 5
DEFAULT_STALENESS_DAYS: int = 30
# When a Deep re-formulation matches the existing stance closely (small
# valence delta + same direction), we bump confidence by this much rather
# than write a new row.
CONFIDENCE_REAFFIRM_BUMP: float = 0.1
# Valence delta below this counts as "no material change" for promotion.
STANCE_MATERIAL_CHANGE_THRESHOLD: float = 0.2


@dataclass
class StanceFormulationOutcome:
    """Summary of one Daily / Deep stance pass."""

    formulated: int
    """New stances written this pass."""
    promoted: int
    """Stances flipped to non-provisional after Deep re-affirmation."""
    skipped: int
    """Entities with insufficient material or LLM declined."""


def _rollup_markers(moments: list[KeyMoment]) -> dict[str, int]:
    """Count marker keys across moments — feeds the prompt as rolled-up context."""
    counts: dict[str, int] = defaultdict(int)
    for m in moments:
        if m.structured_markers:
            for key in m.structured_markers:
                counts[key] += 1
    return dict(counts)


def _is_material_change(old: EntityStance, new_valence: float | None) -> bool:
    """True when a Deep re-formulation diverges enough to warrant a new row."""
    if new_valence is None or old.valence is None:
        # Cannot compare numerically — fall back to "always materially different
        # so we write the new stance and keep the old one as history."
        return True
    return abs(new_valence - old.valence) >= STANCE_MATERIAL_CHANGE_THRESHOLD


class EntityStanceFormulator:
    """
    Formulate (Daily) and revise (Deep) ``entity_stance`` rows.

    Wiring: pass an instance to ``DailyReflectionService`` /
    ``DeepReflectionService`` via their optional constructor hook (added in
    a follow-up); the services call :meth:`formulate_for_new_entities` and
    :meth:`revise_stale` respectively.
    """

    def __init__(
        self,
        state_store: StateStore,
        entity_registry: EntityRegistry,
        stance_store: EntityStanceStore,
        reflection_model: ReflectionModel,
        *,
        clock: ClockPort | None = None,
        min_moments: int = DEFAULT_MIN_MOMENTS,
        staleness_days: int = DEFAULT_STALENESS_DAYS,
    ) -> None:
        self.state_store = state_store
        self.entity_registry = entity_registry
        self.stance_store = stance_store
        self.reflection_model = reflection_model
        self._clock = clock or SystemClock()
        self.min_moments = min_moments
        self.staleness_days = staleness_days

    # ------------------------------------------------------------------
    # Daily entry point
    # ------------------------------------------------------------------

    def formulate_for_new_entities(
        self,
        agent_id: UUID,
        *,
        candidate_entity_ids: list[UUID] | None = None,
        formed_in_reflection_id: UUID | None = None,
    ) -> StanceFormulationOutcome:
        """
        For each entity with ≥ ``min_moments`` recent moments, ask the LLM
        to formulate a stance and persist it (auto-superseding any prior
        stance for that entity).

        ``candidate_entity_ids`` lets the caller restrict to a known
        set (e.g. entities touched in the current day's sessions). When
        ``None``, we iterate over all entities currently in the registry.
        """
        formulated = 0
        skipped = 0
        try:
            entities = self._candidate_entities(agent_id, candidate_entity_ids)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("entity_stance: candidate fetch failed: %s", exc)
            return StanceFormulationOutcome(0, 0, 0)

        for entity in entities:
            moments = self._moments_for(entity.id)
            if len(moments) < self.min_moments:
                skipped += 1
                continue

            output = self.reflection_model.formulate_entity_stance(
                entity, moments, _rollup_markers(moments)
            )
            stance_text = output.stance_text.strip() if output.stance_text else ""
            if not stance_text:
                skipped += 1
                continue

            try:
                self.stance_store.write_stance(
                    agent_id,
                    entity.id,
                    stance_text,
                    valence=output.valence_estimate,
                    intensity=output.intensity_estimate,
                    formed_in_reflection_id=formed_in_reflection_id,
                    based_on_moment_ids=[m.id for m in moments],
                    confidence=output.confidence,
                    is_provisional=True,
                )
            except Exception as exc:
                logger.warning(
                    "entity_stance: write_stance for entity=%s failed: %s",
                    entity.id,
                    exc,
                )
                skipped += 1
                continue
            formulated += 1

        return StanceFormulationOutcome(formulated, 0, skipped)

    # ------------------------------------------------------------------
    # Deep entry point
    # ------------------------------------------------------------------

    def revise_stale(
        self,
        agent_id: UUID,
        *,
        formed_in_reflection_id: UUID | None = None,
    ) -> StanceFormulationOutcome:
        """
        Re-visit active stances older than ``staleness_days``.

        For each: if the entity has any new moments since the stance was
        formed, ask the LLM to re-formulate. If materially different →
        write a new stance (auto-supersedes). Otherwise → promote the
        existing stance to non-provisional and nudge its confidence up.
        """
        formulated = 0
        promoted = 0
        skipped = 0
        try:
            stances = self.stance_store.list_active_stances(agent_id, limit=200)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("entity_stance: list_active_stances failed: %s", exc)
            return StanceFormulationOutcome(0, 0, 0)

        now = self._clock.now()
        cutoff = now - timedelta(days=self.staleness_days)
        for stance in stances:
            if stance.formed_at > cutoff:
                continue

            entity = self.entity_registry.get_entity(stance.entity_id)
            if entity is None:
                skipped += 1
                continue

            new_moments = [m for m in self._moments_for(entity.id) if m.when > stance.formed_at]
            if not new_moments:
                # No new evidence → cannot confirm or deny; leave as-is.
                skipped += 1
                continue

            output = self.reflection_model.formulate_entity_stance(
                entity, new_moments, _rollup_markers(new_moments)
            )
            stance_text = output.stance_text.strip() if output.stance_text else ""
            if not stance_text:
                skipped += 1
                continue

            if _is_material_change(stance, output.valence_estimate):
                try:
                    self.stance_store.write_stance(
                        agent_id,
                        entity.id,
                        stance_text,
                        valence=output.valence_estimate,
                        intensity=output.intensity_estimate,
                        formed_in_reflection_id=formed_in_reflection_id,
                        based_on_moment_ids=[m.id for m in new_moments],
                        confidence=output.confidence,
                        is_provisional=True,
                    )
                    formulated += 1
                except Exception as exc:
                    logger.warning(
                        "entity_stance: deep write_stance for entity=%s failed: %s",
                        entity.id,
                        exc,
                    )
                    skipped += 1
            else:
                # Confirm — promote in-place. EntityStance is mutable
                # (validate_assignment=True) and the stance store keeps it
                # by reference.
                try:
                    stance.is_provisional = False
                    if stance.confidence is None:
                        stance.confidence = output.confidence or 0.0
                    else:
                        stance.confidence = min(1.0, stance.confidence + CONFIDENCE_REAFFIRM_BUMP)
                    promoted += 1
                except Exception as exc:
                    logger.warning(
                        "entity_stance: deep promote for stance=%s failed: %s",
                        stance.id,
                        exc,
                    )
                    skipped += 1

        return StanceFormulationOutcome(formulated, promoted, skipped)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _candidate_entities(
        self, agent_id: UUID, candidate_entity_ids: list[UUID] | None
    ) -> list[Entity]:
        if candidate_entity_ids is not None:
            out: list[Entity] = []
            for eid in candidate_entity_ids:
                e = self.entity_registry.get_entity(eid)
                if e is not None and e.agent_id == agent_id:
                    out.append(e)
            return out
        # Iterate over registry. EntityRegistry.list_entities API:
        return list(self.entity_registry.list_entities(agent_id=agent_id))

    def _moments_for(self, entity_id: UUID) -> list[KeyMoment]:
        try:
            moments = list(self.state_store.find_moments_by_entity(entity_id, limit=200))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("entity_stance: find_moments_by_entity(%s) failed: %s", entity_id, exc)
            return []
        moments.sort(key=lambda m: (m.when, str(m.id)))
        return moments
