"""
FindingsTriage — Daily resolves level-B ``validation_findings`` by policy.

Operates on findings written by :class:`~atman.core.ports.memory_guardian.
MemoryGuardian` (and other sources). Critical findings are **never** auto-
resolved here — they get ``ResolutionStatus.requires_attention`` and are
left for an operator (see REFLECTION_FUTURE §10). Level-B (``info`` /
``warning``) findings are resolved by simple per-type rules.

Notes on scope:

* ``similar_entities`` — Daily handles only the trivial case (Memory-
  Guardian-supplied ``cosine >= LLM_FREE_MERGE_THRESHOLD``) by ignoring it
  here and deferring the LLM-driven merge decision to Deep reflection
  (R10 / ``MergeCandidatesHandler``). The non-trivial cases are explicitly
  left as ``unresolved`` so Deep can pick them up.
* ``analysis_failed`` is escalated to ``requires_attention`` even at level
  B — there's no auto-fix for it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from atman.core.models.validation import (
    FindingSeverity,
    FindingType,
    ResolutionStatus,
    ValidationFinding,
)
from atman.core.ports.memory_guardian import MemoryGuardian

logger = logging.getLogger(__name__)

# MemoryGuardian default for similar-entity scans is 0.92; Daily only resolves
# trivially-obvious duplicates (cosine ≥ this), deferring the rest to Deep R10.
DAILY_TRIVIAL_DUPLICATE_THRESHOLD: float = 0.98

TRIAGE_RESOLVED_BY: str = "reflection.findings_triage"


@dataclass
class TriageOutcome:
    """Summary of one Daily triage pass."""

    resolved_count: int
    requires_attention_count: int
    skipped_count: int

    @property
    def total_processed(self) -> int:
        return self.resolved_count + self.requires_attention_count + self.skipped_count


def _is_level_b(severity: FindingSeverity) -> bool:
    return severity in (FindingSeverity.info, FindingSeverity.warning)


def _decide_similar_entities(finding: ValidationFinding) -> tuple[bool, str | None, str]:
    """
    Daily-policy for similar_entities (cf. §4.4 + §5.4 split).

    Returns ``(should_resolve, resolution_status, note)``. When
    ``should_resolve`` is False the finding is left ``unresolved`` and
    becomes a Deep-reflection candidate.
    """
    # Cosine score is written by scan_merge_candidates under the
    # ``similarity`` key (cf. in_memory_memory_guardian._scan_merge_candidates).
    # Older code paths used ``cosine`` — read both so the threshold actually
    # takes effect (Devin Review #598 spotted the legacy-only key making the
    # DAILY_TRIVIAL_DUPLICATE_THRESHOLD shortcut dead code).
    cosine = finding.details.get("similarity")
    if cosine is None:
        cosine = finding.details.get("cosine")
    try:
        cosine_val = float(cosine) if cosine is not None else None
    except (TypeError, ValueError):
        cosine_val = None

    if cosine_val is not None and cosine_val >= DAILY_TRIVIAL_DUPLICATE_THRESHOLD:
        # Trivially-obvious duplicate — ignored at this level (Deep R10 will
        # confirm and call EntityRegistry.merge_entities). We keep both
        # entities for now; merging is a destructive write Daily must not do.
        return (
            True,
            ResolutionStatus.ignored.value,
            f"trivial duplicate cosine={cosine_val:.3f} deferred to Deep R10",
        )
    # Non-trivial — let Deep handle the LLM merge decision.
    return (False, None, "")


class FindingsTriage:
    """
    Process level-B ``validation_findings`` for a given agent.

    Single ``run(agent_id)`` call is what Daily reflection invokes; the
    operation is idempotent because already-resolved findings are filtered
    out by :meth:`MemoryGuardian.get_unresolved`.
    """

    def __init__(self, guardian: MemoryGuardian) -> None:
        self.guardian = guardian

    def run(self, agent_id: UUID) -> TriageOutcome:
        try:
            unresolved = self.guardian.get_unresolved(agent_id)
        except Exception as exc:
            logger.warning("findings_triage: get_unresolved failed: %s", exc)
            return TriageOutcome(0, 0, 0)

        resolved = 0
        attention = 0
        skipped = 0
        for finding in unresolved:
            # Critical findings (§10) — never auto-resolved. Left unresolved
            # so the operator dashboards keep showing them; alerting policy
            # lives elsewhere.
            if finding.severity == FindingSeverity.critical:
                skipped += 1
                continue
            if not _is_level_b(finding.severity):
                skipped += 1
                continue

            decision = self._decide(finding)
            if decision is None:
                # Explicitly defer to Deep reflection (e.g. non-trivial
                # similar_entities) — leave unresolved.
                skipped += 1
                continue

            resolution, note = decision
            try:
                self.guardian.resolve_finding(
                    finding.id,
                    resolution=resolution,
                    resolved_by=TRIAGE_RESOLVED_BY,
                    note=note,
                )
            except Exception as exc:
                logger.warning("findings_triage: resolve_finding(%s) failed: %s", finding.id, exc)
                skipped += 1
                continue

            if resolution == ResolutionStatus.requires_attention.value:
                attention += 1
            else:
                resolved += 1

        return TriageOutcome(resolved, attention, skipped)

    def _decide(self, finding: ValidationFinding) -> tuple[str, str] | None:
        """Return ``(resolution, note)`` for this finding, or None to skip."""
        ftype = finding.finding_type
        if ftype == FindingType.orphan_entity:
            # Mention-count alone is not enough to forget a memory.
            return (ResolutionStatus.ignored.value, "kept by policy")
        if ftype == FindingType.similar_entities:
            handled, status, note = _decide_similar_entities(finding)
            if not handled:
                return None
            assert status is not None
            return (status, note)
        if ftype == FindingType.pending_structured_markers:
            return (ResolutionStatus.ignored.value, "accepted as-is")
        if ftype == FindingType.analysis_failed:
            return (
                ResolutionStatus.requires_attention.value,
                "analysis pipeline failure — operator action required",
            )
        if ftype == FindingType.affect_detector_silent:
            # Critical class even when level-B; do not silently ignore.
            return (
                ResolutionStatus.requires_attention.value,
                "affect detector produced no signal — operator action required",
            )
        # Stale moments, embedding gaps, quality_metric — explicit no-op
        # at this layer (handled by maintenance worker policies).
        # HLE-31 Level-C psychological signals (`divergence_pattern`,
        # `stance_formation_too_fast`) also fall through here intentionally:
        # they are diagnostic, not actionable from Daily triage — R6 consumes
        # them, and Deep does not yet have a dedicated handler. Findings
        # accumulate as unresolved until operator review or a future
        # automated resolver is wired in.
        return None
