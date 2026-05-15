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
