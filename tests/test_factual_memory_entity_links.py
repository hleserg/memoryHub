"""Tests for the FactualMemory.add_fact_with_entities / find_facts_by_entity defaults."""

from __future__ import annotations

from uuid import uuid4

import pytest

from atman.adapters.memory.file_backend import FileBackend
from atman.adapters.memory.in_memory_backend import InMemoryBackend
from atman.core.models import FactRecord


def _fact() -> FactRecord:
    return FactRecord(
        content="atman runs in Vermont",
        source="test",
        tags=["geo"],
    )


@pytest.fixture(params=["in_memory", "file"])
def backend(request, tmp_path):
    if request.param == "in_memory":
        return InMemoryBackend()
    return FileBackend(tmp_path / "facts.jsonl")


def test_add_fact_with_entities_default_persists_fact(backend) -> None:
    """Even when the backend doesn't override the new method, the fact itself is stored."""
    f = _fact()
    entity_a = uuid4()
    entity_b = uuid4()
    stored = backend.add_fact_with_entities(f, [(entity_a, "subject"), (entity_b, "object")])
    assert stored.id == f.id
    # Fact retrievable via standard API
    assert backend.get_fact(f.id) is not None


def test_find_facts_by_entity_default_returns_empty(backend) -> None:
    """Default returns [] for backends without entity-link tables."""
    f = _fact()
    backend.add_fact(f)
    result = backend.find_facts_by_entity(uuid4())
    assert result == []


def test_find_facts_by_entity_with_roles_default_returns_empty(backend) -> None:
    """Role filter does not change the default empty result."""
    result = backend.find_facts_by_entity(uuid4(), roles=["subject"])
    assert result == []
