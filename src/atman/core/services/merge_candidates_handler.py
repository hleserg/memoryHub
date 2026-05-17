"""
MergeCandidatesHandler — R10 service (REFLECTION_FUTURE.md §5.4, §10).

Deep-reflection-only. Processes ``similar_entities`` validation findings
that ``FindingsTriage`` (R8) deferred to Deep (i.e. the cosine wasn't
high enough to auto-resolve trivially). For each such finding:

1. Pulls a few recent KeyMoments for both candidate entities via
   :meth:`StateStore.find_moments_by_entity`.
2. Asks the LLM via :meth:`ReflectionModel.decide_entity_merge` whether
   they're the same subject.
3. If ``confirmed``: calls :meth:`EntityRegistry.merge_entities` (the
   registry handles FK rewrites — see ``InMemoryEntityRegistry`` /
   ``PostgresEntityRegistry``) and marks the finding ``fixed`` via the
   guardian's :meth:`resolve_finding`.
4. If not confirmed: marks the finding ``ignored`` with the LLM's
   ``reason`` written to the resolution note.

Failures (LLM error, merge error, store error) leave the finding
``unresolved`` so the next Deep run can retry — never half-merge.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from atman.core.models.validation import (
    FindingType,
    ResolutionStatus,
    ValidationFinding,
)
from atman.core.ports.entity_registry import EntityRegistry
from atman.core.ports.memory_guardian import MemoryGuardian
from atman.core.ports.reflection import ReflectionModel
from atman.core.ports.state_store import StateStore

logger = logging.getLogger(__name__)

DEFAULT_CONTEXT_LIMIT: int = 5
MERGE_RESOLVED_BY: str = "reflection.merge_candidates"


@dataclass
class MergeOutcome:
    """Summary of one Deep merge pass."""

    merged: int
    """Pairs the LLM confirmed and the registry merged."""
    ignored: int
    """Pairs the LLM rejected (resolution=ignored)."""
    skipped: int
    """Findings that couldn't be processed (missing entities, LLM error)."""


def _candidate_entity_ids(finding: ValidationFinding) -> tuple[UUID, UUID] | None:
    """
    Extract the two candidate entity ids from a ``similar_entities`` finding.

    MemoryGuardian writes the canonical pair under ``details.candidate_id``
    and ``details.target_id``; the finding's ``target_id`` is the primary
    target. We accept either shape conservatively so partial implementations
    don't all break.
    """
    a = finding.target_id
    details = finding.details or {}
    b_raw = (
        details.get("candidate_id")
        or details.get("other_id")
        or details.get("merge_id")
        or details.get("similar_id")
    )
    if b_raw is None:
        return None
    try:
        b = b_raw if isinstance(b_raw, UUID) else UUID(str(b_raw))
    except (ValueError, AttributeError):
        return None
    if a == b:
        return None
    return (a, b)


class MergeCandidatesHandler:
    """
    Resolve ``similar_entities`` validation findings via LLM merge decision.
    """

    def __init__(
        self,
        state_store: StateStore,
        entity_registry: EntityRegistry,
        guardian: MemoryGuardian,
        reflection_model: ReflectionModel,
        *,
        context_limit: int = DEFAULT_CONTEXT_LIMIT,
    ) -> None:
        self.state_store = state_store
        self.entity_registry = entity_registry
        self.guardian = guardian
        self.reflection_model = reflection_model
        self.context_limit = context_limit

    def run(self, agent_id: UUID) -> MergeOutcome:
        try:
            unresolved = self.guardian.get_unresolved(agent_id)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("merge_candidates: get_unresolved failed: %s", exc)
            return MergeOutcome(0, 0, 0)

        candidates = [f for f in unresolved if f.finding_type == FindingType.similar_entities]

        merged = 0
        ignored = 0
        skipped = 0
        for finding in candidates:
            pair = _candidate_entity_ids(finding)
            if pair is None:
                skipped += 1
                continue
            a_id, b_id = pair
            entity_a = self.entity_registry.get_entity(a_id)
            entity_b = self.entity_registry.get_entity(b_id)
            if entity_a is None or entity_b is None:
                skipped += 1
                continue

            try:
                ctx_a = list(
                    self.state_store.find_moments_by_entity(a_id, limit=self.context_limit)
                )
                ctx_b = list(
                    self.state_store.find_moments_by_entity(b_id, limit=self.context_limit)
                )
            except Exception as exc:
                logger.warning(
                    "merge_candidates: moment fetch for (%s, %s) failed: %s",
                    a_id,
                    b_id,
                    exc,
                )
                skipped += 1
                continue

            try:
                output = self.reflection_model.decide_entity_merge(entity_a, entity_b, ctx_a, ctx_b)
            except Exception as exc:
                logger.warning(
                    "merge_candidates: LLM decision failed for (%s, %s): %s",
                    a_id,
                    b_id,
                    exc,
                )
                skipped += 1
                continue

            reason = (output.reason or "").strip()
            if output.confirmed:
                keep_id, drop_id = self._choose_keep(entity_a, entity_b, output.canonical_name)
                # Guard against double-merge from a previous pass where the
                # merge committed but ``resolve_finding`` failed: a re-run
                # would otherwise call ``merge_entities`` again, and
                # ``mention_count`` accumulates unconditionally.
                drop_entity = entity_a if drop_id == entity_a.id else entity_b
                already_disambiguated = bool(getattr(drop_entity, "needs_disambiguation", False))
                if not already_disambiguated:
                    try:
                        self.entity_registry.merge_entities(
                            drop_id,
                            keep_id,
                            reason=(f"deep_reflection: {reason}" if reason else "deep_reflection"),
                        )
                    except Exception as exc:
                        logger.warning(
                            "merge_candidates: merge_entities(%s -> %s) failed: %s",
                            drop_id,
                            keep_id,
                            exc,
                        )
                        skipped += 1
                        continue
                resolve_note = reason or f"merged {drop_id} -> {keep_id}"
                if already_disambiguated:
                    resolve_note += " (previously merged; closing leftover finding)"
                self._resolve(
                    finding,
                    resolution=ResolutionStatus.fixed.value,
                    note=resolve_note,
                )
                merged += 1
            elif reason:
                self._resolve(
                    finding,
                    resolution=ResolutionStatus.ignored.value,
                    note=reason,
                )
                ignored += 1
            else:
                # LLM declined without a reason — leave unresolved so the
                # next pass can retry rather than swallow it.
                skipped += 1

        return MergeOutcome(merged=merged, ignored=ignored, skipped=skipped)

    # ------------------------------------------------------------------

    def _choose_keep(self, a, b, canonical_name: str | None) -> tuple[UUID, UUID]:
        """Pick which entity stays. The LLM's preferred name wins ties."""
        if canonical_name:
            name = canonical_name.strip().lower()
            if a.canonical_name.strip().lower() == name:
                return (a.id, b.id)
            if b.canonical_name.strip().lower() == name:
                return (b.id, a.id)
        # Default: keep the one with the higher mention_count (more
        # established), falling back to lexicographic id order for
        # determinism.
        a_count = getattr(a, "mention_count", 1)
        b_count = getattr(b, "mention_count", 1)
        if a_count >= b_count:
            return (a.id, b.id)
        return (b.id, a.id)

    def _resolve(self, finding: ValidationFinding, *, resolution: str, note: str) -> None:
        try:
            self.guardian.resolve_finding(
                finding.id,
                resolution=resolution,
                resolved_by=MERGE_RESOLVED_BY,
                note=note,
            )
        except Exception as exc:
            logger.warning(
                "merge_candidates: resolve_finding(%s) failed: %s",
                finding.id,
                exc,
            )
