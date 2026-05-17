"""Port: MemoryGuardian — scan for inconsistencies and quality issues."""

from abc import ABC, abstractmethod
from uuid import UUID

from atman.core.models.validation import ValidationFinding


class MemoryGuardian(ABC):
    """Abstract port for scanning agent memory for quality issues and inconsistencies."""

    @abstractmethod
    def scan_orphan_entities(self, agent_id: UUID) -> list[ValidationFinding]:
        """Find entities with no linked facts or key_moments."""

    @abstractmethod
    def scan_merge_candidates(
        self,
        agent_id: UUID,
        *,
        similarity_threshold: float = 0.92,
    ) -> list[ValidationFinding]:
        """Find entity pairs with high embedding similarity that may be duplicates."""

    @abstractmethod
    def scan_stale_moments(
        self,
        agent_id: UUID,
        *,
        days_threshold: int = 90,
    ) -> list[ValidationFinding]:
        """Find key_moments with very low salience that haven't been accessed."""

    @abstractmethod
    def scan_embedding_gaps(self, agent_id: UUID) -> list[ValidationFinding]:
        """Find entities and key_moments missing embeddings."""

    def scan_quality_metrics(
        self,
        agent_id: UUID,
        *,
        window_days: int = 7,
        incomplete_coloring_threshold: float = 0.3,
        divergence_pattern_threshold: int = 5,
        stance_too_fast_hours: int = 24,
        stance_too_fast_min_count: int = 3,
    ) -> list[ValidationFinding]:
        """Level-C psychological quality-metric scans (HLE-31).

        Inspects recent agent activity for systemic signals that the
        memory pipeline (not the agent itself) is misbehaving:

        * ``affect_detector_silent`` — too many moments arriving with
          ``incomplete_coloring=True`` over ``window_days``.
        * ``divergence_pattern`` — same divergence_type firing ≥ N times
          over ``window_days``; a stable pattern that R6 should weigh.
        * ``stance_formation_too_fast`` — stances formed within
          ``stance_too_fast_hours`` of their backing moments occurring
          ≥ ``stance_too_fast_min_count`` times: reflection is jumping
          to conclusions before evidence has settled.

        Default returns ``[]`` so existing implementations that have not
        yet adopted the scan stay valid; concrete adapters override.
        """
        _ = (
            agent_id,
            window_days,
            incomplete_coloring_threshold,
            divergence_pattern_threshold,
            stance_too_fast_hours,
            stance_too_fast_min_count,
        )
        return []

    @abstractmethod
    def write_finding(self, finding: ValidationFinding) -> ValidationFinding:
        """Persist a finding to storage."""

    @abstractmethod
    def get_unresolved(
        self,
        agent_id: UUID,
        severity: str | None = None,
    ) -> list[ValidationFinding]:
        """Get unresolved findings, optionally filtered by severity."""

    @abstractmethod
    def resolve_finding(
        self,
        finding_id: UUID,
        *,
        resolution: str,
        resolved_by: str,
        note: str = "",
    ) -> ValidationFinding | None:
        """Mark a finding as resolved."""
