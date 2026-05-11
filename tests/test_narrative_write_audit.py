"""No-op narrative write audit contract."""

from __future__ import annotations

from uuid import uuid4

from atman.core.narrative_write_audit import NoOpNarrativeWriteAudit


def test_noop_narrative_write_audit_methods_return_none() -> None:
    audit = NoOpNarrativeWriteAudit()
    nid = uuid4()
    iid = uuid4()
    assert (
        audit.record_narrative_commit(
            change_kind="update",
            narrative_id=nid,
            identity_id=iid,
            reason_or_summary="smoke",
        )
        is None
    )
    assert (
        audit.record_narrative_commit_audit_failure(
            change_kind="update",
            narrative_id=nid,
            identity_id=iid,
            committed_summary="x",
            error_message="y",
        )
        is None
    )
