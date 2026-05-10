"""Tests for ConflictDetector (E24.5)."""

from __future__ import annotations

from pathlib import Path

import pytest

from atman.adapters.memory.file_backend import FileBackend
from atman.adapters.memory.in_memory_backend import InMemoryBackend
from atman.core.models.fact import FactRecord, FactStatus
from atman.core.ports import FactualMemory
from atman.core.services.conflict_detector import ConflictDetector


def _backend_with(*facts: FactRecord) -> InMemoryBackend:
    backend = InMemoryBackend()
    for fact in facts:
        backend.add_fact(fact)
    return backend


@pytest.fixture(params=["in_memory", "file"])
def persisted_backend(request: pytest.FixtureRequest, tmp_path: Path) -> FactualMemory:
    """Exercise conflict detection against both volatile and persistent facts."""
    if request.param == "file":
        return FileBackend(tmp_path / "facts.jsonl")
    return InMemoryBackend()


def test_check_fact_returns_empty_when_no_other_facts():
    backend = _backend_with()
    detector = ConflictDetector(factual_memory=backend)
    new_fact = FactRecord(content="The sky is blue", source="obs")
    assert detector.check_fact(new_fact) == []


def test_check_fact_skips_non_active_input():
    backend = _backend_with()
    detector = ConflictDetector(factual_memory=backend)
    # All non-ACTIVE inputs short-circuit to no conflicts.
    for status in (FactStatus.INVALIDATED, FactStatus.SUPERSEDED, FactStatus.DISPUTED):
        non_active = FactRecord(content="x", source="t", status=status)
        assert detector.check_fact(non_active) == []


def test_check_fact_detects_negation_contradiction():
    # InMemoryBackend.search() does substring matching on fact.content using
    # `new_fact.content[:50]` as the query, so the candidate's content must
    # contain the new fact's content verbatim.
    existing = FactRecord(
        content="build is healthy not really",
        source="ci",
    )
    backend = _backend_with(existing)
    detector = ConflictDetector(factual_memory=backend)

    new_fact = FactRecord(
        content="build is healthy",
        source="ci",
    )
    conflicts = detector.check_fact(new_fact)
    assert len(conflicts) >= 1
    assert conflicts[0].conflict_type == "contradiction"
    assert 0.0 < conflicts[0].confidence <= 0.9


def test_check_fact_detects_negation_contradiction_across_backends(
    persisted_backend: FactualMemory,
):
    persisted_backend.add_fact(FactRecord(content="build is healthy not really", source="ci"))
    detector = ConflictDetector(factual_memory=persisted_backend)

    conflicts = detector.check_fact(FactRecord(content="build is healthy", source="ci"))

    assert len(conflicts) == 1
    assert conflicts[0].conflict_type == "contradiction"


def test_check_fact_does_not_surface_persistent_non_active_candidates(tmp_path: Path):
    backend = FileBackend(tmp_path / "facts.jsonl")
    inactive = backend.add_fact(FactRecord(content="build is healthy not really", source="ci"))
    invalidated = backend.invalidate_fact(
        inactive.id,
        status=FactStatus.SUPERSEDED,
        note="replaced by newer signal",
    )
    assert invalidated is not None

    reloaded_backend = FileBackend(tmp_path / "facts.jsonl")
    detector = ConflictDetector(factual_memory=reloaded_backend)

    assert detector.check_fact(FactRecord(content="build is healthy", source="ci")) == []


def test_check_fact_detects_inconsistency_via_shared_tags():
    existing = FactRecord(
        content="Project X uses Python for the backend services pipeline",
        source="docs",
        tags=["project-x", "stack"],
    )
    backend = _backend_with(existing)
    detector = ConflictDetector(factual_memory=backend)

    new_fact = FactRecord(
        content="Project X uses Python for the backend services",
        source="docs",
        tags=["project-x", "stack"],
    )
    conflicts = detector.check_fact(new_fact)
    assert len(conflicts) >= 1
    assert conflicts[0].conflict_type == "inconsistency"


def test_scan_all_conflicts_detects_negation_pair():
    f1 = FactRecord(content="The deploy succeeded today on prod", source="ci")
    f2 = FactRecord(content="The deploy did not succeed today on prod", source="ci")
    backend = _backend_with(f1, f2)
    detector = ConflictDetector(factual_memory=backend)
    conflicts = detector.scan_all_conflicts(limit=10)
    assert len(conflicts) == 1
    assert conflicts[0].conflict_type == "contradiction"


def test_scan_all_conflicts_skips_invalidated_facts():
    backend = InMemoryBackend()
    backend.add_fact(FactRecord(content="The deploy succeeded today on prod", source="ci"))
    fact_b = backend.add_fact(
        FactRecord(content="The deploy did not succeed today on prod", source="ci")
    )
    backend.invalidate_fact(fact_b.id, status=FactStatus.SUPERSEDED, note="old")
    detector = ConflictDetector(factual_memory=backend)
    assert detector.scan_all_conflicts() == []


def test_get_cognitive_tension_zero_for_no_conflicts():
    detector = ConflictDetector(factual_memory=InMemoryBackend())
    assert detector.get_cognitive_tension([]) == 0.0


def test_get_cognitive_tension_grows_with_conflicts():
    f1 = FactRecord(content="The deploy succeeded today on prod", source="ci")
    f2 = FactRecord(content="The deploy did not succeed today on prod", source="ci")
    backend = _backend_with(f1, f2)
    detector = ConflictDetector(factual_memory=backend)
    conflicts = detector.scan_all_conflicts()
    tension = detector.get_cognitive_tension(conflicts)
    assert 0.0 < tension <= 1.0


def test_content_similarity_handles_empty_text():
    detector = ConflictDetector(factual_memory=InMemoryBackend())
    assert detector._content_similarity("", "anything") == 0.0
    assert detector._content_similarity("anything", "") == 0.0
