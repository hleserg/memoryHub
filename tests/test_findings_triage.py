"""Tests for :mod:`atman.core.services.findings_triage` (R8)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from atman.core.models.validation import (
    FindingSeverity,
    FindingType,
    ResolutionStatus,
    ValidationFinding,
)
from atman.core.ports.memory_guardian import MemoryGuardian
from atman.core.services.findings_triage import (
    DAILY_TRIVIAL_DUPLICATE_THRESHOLD,
    TRIAGE_RESOLVED_BY,
    FindingsTriage,
)

AGENT_ID = UUID("00000000-0000-4000-8000-000000000010")


def _finding(
    *,
    ftype: FindingType,
    severity: FindingSeverity = FindingSeverity.warning,
    details: dict | None = None,
) -> ValidationFinding:
    return ValidationFinding(
        agent_id=AGENT_ID,
        finding_type=ftype,
        severity=severity,
        target_table="entities",
        target_id=uuid4(),
        details=details or {},
        detected_at=datetime.now(UTC),
        detected_by="test",
    )


class _StubGuardian(MemoryGuardian):
    """Minimal MemoryGuardian honouring only the methods FindingsTriage uses."""

    def __init__(self, findings: list[ValidationFinding]) -> None:
        self._findings = {f.id: f for f in findings}
        self.resolved_calls: list[tuple[UUID, str, str, str]] = []

    # Scan APIs unused here.
    def scan_orphan_entities(self, agent_id):  # pragma: no cover
        return []

    def scan_merge_candidates(self, agent_id, *, similarity_threshold=0.92):  # pragma: no cover
        return []

    def scan_stale_moments(self, agent_id, *, days_threshold=90):  # pragma: no cover
        return []

    def scan_embedding_gaps(self, agent_id):  # pragma: no cover
        return []

    def write_finding(self, finding):  # pragma: no cover
        self._findings[finding.id] = finding
        return finding

    def get_unresolved(self, agent_id, severity=None):
        out = [f for f in self._findings.values() if not f.is_resolved]
        if severity is not None:
            out = [f for f in out if f.severity.value == severity]
        return out

    def resolve_finding(
        self,
        finding_id,
        *,
        resolution,
        resolved_by,
        note="",
    ):
        f = self._findings.get(finding_id)
        if f is None:
            return None
        resolved = f.model_copy(
            update={
                "resolution": ResolutionStatus(resolution),
                "resolved_at": datetime.now(UTC),
                "resolved_by": resolved_by,
                "resolution_note": note,
            }
        )
        self._findings[finding_id] = resolved
        self.resolved_calls.append((finding_id, resolution, resolved_by, note))
        return resolved


# ---------------------------------------------------------------------------
# Per-type rules
# ---------------------------------------------------------------------------


def test_orphan_entity_resolved_as_ignored_kept_by_policy():
    f = _finding(ftype=FindingType.orphan_entity)
    g = _StubGuardian([f])
    out = FindingsTriage(g).run(AGENT_ID)
    assert out.resolved_count == 1
    fid, res, by, note = g.resolved_calls[0]
    assert fid == f.id
    assert res == ResolutionStatus.ignored.value
    assert by == TRIAGE_RESOLVED_BY
    assert "kept by policy" in note


def test_similar_entities_trivial_duplicate_resolved_as_ignored_deferred_to_deep():
    f = _finding(
        ftype=FindingType.similar_entities,
        details={"cosine": DAILY_TRIVIAL_DUPLICATE_THRESHOLD + 0.005},
    )
    g = _StubGuardian([f])
    out = FindingsTriage(g).run(AGENT_ID)
    assert out.resolved_count == 1
    assert g.resolved_calls[0][1] == ResolutionStatus.ignored.value
    assert "Deep" in g.resolved_calls[0][3]


def test_similar_entities_non_trivial_left_unresolved_for_deep():
    f = _finding(
        ftype=FindingType.similar_entities,
        details={"cosine": 0.94},
    )
    g = _StubGuardian([f])
    out = FindingsTriage(g).run(AGENT_ID)
    assert out.resolved_count == 0
    assert out.skipped_count == 1
    assert g.resolved_calls == []


def test_similar_entities_no_cosine_left_unresolved():
    f = _finding(ftype=FindingType.similar_entities, details={})
    g = _StubGuardian([f])
    out = FindingsTriage(g).run(AGENT_ID)
    assert out.skipped_count == 1
    assert g.resolved_calls == []


def test_similar_entities_reads_similarity_key_when_cosine_absent():
    """scan_merge_candidates writes the cosine score under details['similarity'],
    not ['cosine']. The triage shortcut must read both so the
    DAILY_TRIVIAL_DUPLICATE_THRESHOLD path is not dead code (Devin Review #598)."""
    f = _finding(
        ftype=FindingType.similar_entities,
        details={"similarity": DAILY_TRIVIAL_DUPLICATE_THRESHOLD + 0.01},
    )
    g = _StubGuardian([f])
    out = FindingsTriage(g).run(AGENT_ID)
    assert out.resolved_count == 1
    assert g.resolved_calls[0][1] == ResolutionStatus.ignored.value


def test_pending_structured_markers_resolved_as_accepted():
    f = _finding(ftype=FindingType.pending_structured_markers)
    g = _StubGuardian([f])
    out = FindingsTriage(g).run(AGENT_ID)
    assert out.resolved_count == 1
    assert g.resolved_calls[0][1] == ResolutionStatus.ignored.value
    assert "accepted as-is" in g.resolved_calls[0][3]


def test_analysis_failed_marked_requires_attention():
    f = _finding(ftype=FindingType.analysis_failed)
    g = _StubGuardian([f])
    out = FindingsTriage(g).run(AGENT_ID)
    assert out.requires_attention_count == 1
    assert g.resolved_calls[0][1] == ResolutionStatus.requires_attention.value


def test_affect_detector_silent_marked_requires_attention_even_at_warning():
    f = _finding(ftype=FindingType.affect_detector_silent, severity=FindingSeverity.warning)
    g = _StubGuardian([f])
    out = FindingsTriage(g).run(AGENT_ID)
    assert out.requires_attention_count == 1
    assert g.resolved_calls[0][1] == ResolutionStatus.requires_attention.value


# ---------------------------------------------------------------------------
# Severity policy
# ---------------------------------------------------------------------------


def test_critical_findings_never_auto_resolved():
    f = _finding(ftype=FindingType.affect_detector_silent, severity=FindingSeverity.critical)
    g = _StubGuardian([f])
    out = FindingsTriage(g).run(AGENT_ID)
    assert out.skipped_count == 1
    assert g.resolved_calls == []


def test_idempotent_run_does_not_revisit_resolved_findings():
    f = _finding(ftype=FindingType.orphan_entity)
    g = _StubGuardian([f])
    triage = FindingsTriage(g)
    first = triage.run(AGENT_ID)
    second = triage.run(AGENT_ID)
    assert first.resolved_count == 1
    assert second.total_processed == 0


def test_get_unresolved_failure_returns_zero_processed():
    class _Broken(_StubGuardian):
        def get_unresolved(self, agent_id, severity=None):  # type: ignore[override]
            raise RuntimeError("db down")

    out = FindingsTriage(_Broken([])).run(AGENT_ID)
    assert out.total_processed == 0


def test_resolve_failure_skips_finding():
    class _BrokenResolve(_StubGuardian):
        def resolve_finding(self, *args, **kwargs):  # type: ignore[override]
            raise RuntimeError("db down")

    f = _finding(ftype=FindingType.orphan_entity)
    out = FindingsTriage(_BrokenResolve([f])).run(AGENT_ID)
    assert out.resolved_count == 0
    assert out.skipped_count == 1
