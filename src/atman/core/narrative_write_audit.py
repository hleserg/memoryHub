"""
Narrative write audit helpers.

Production paths should wire a real :class:`~atman.core.ports.reflection.NarrativeWriteAuditPort`.
:class:`NoOpNarrativeWriteAudit` is an explicit, typed stand-in for tests and demos where no
governance sink is configured — it must be passed explicitly so narrative commits are never
silent-by-default.
"""

from uuid import UUID


class NoOpNarrativeWriteAudit:
    """Explicit no-op audit sink (observable contract without external systems)."""

    def record_narrative_commit(
        self,
        *,
        change_kind: str,
        narrative_id: UUID,
        identity_id: UUID,
        reason_or_summary: str,
    ) -> None:
        return None

    def record_narrative_commit_audit_failure(
        self,
        *,
        change_kind: str,
        narrative_id: UUID,
        identity_id: UUID,
        committed_summary: str,
        error_message: str,
    ) -> None:
        return None
