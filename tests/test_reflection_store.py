"""
Tests for ReflectionStore implementations.

Tests cover:
- Basic CRUD operations (add, get, list_*)
- RLS (Row-Level Security) simulation with current_agent context
- Filtering by level, session, experience
- Ordering (newest first)
- Edge cases (empty results, None fields)
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from atman.adapters.storage.in_memory_postgres_reflection_store import InMemoryReflectionStore
from atman.adapters.storage.postgres_reflection_models import ReflectionRecord
from atman.core.models.reflection import ReflectionLevel


@pytest.fixture
def store():
    """Fresh in-memory reflection store for each test."""
    return InMemoryReflectionStore()


def test_add_reflection_assigns_id(store: InMemoryReflectionStore):
    """Adding a reflection assigns a new ID."""
    agent_id = uuid4()
    session_id = uuid4()

    record = ReflectionRecord(
        agent_id=agent_id,
        level=ReflectionLevel.MICRO,
        session_id=session_id,
        content="Test reflection",
    )

    result = store.add(record)

    assert result.id is not None
    assert result.id == 1  # First ID in sequence
    assert result.agent_id == agent_id
    assert result.content == "Test reflection"


def test_add_multiple_reflections_increments_id(store: InMemoryReflectionStore):
    """Multiple adds increment the ID sequence."""
    agent_id = uuid4()

    r1 = store.add(
        ReflectionRecord(agent_id=agent_id, level=ReflectionLevel.MICRO, content="First")
    )
    r2 = store.add(
        ReflectionRecord(agent_id=agent_id, level=ReflectionLevel.DAILY, content="Second")
    )
    r3 = store.add(ReflectionRecord(agent_id=agent_id, level=ReflectionLevel.DEEP, content="Third"))

    assert r1.id == 1
    assert r2.id == 2
    assert r3.id == 3


def test_get_retrieves_reflection_by_id(store: InMemoryReflectionStore):
    """get() retrieves a reflection by its database ID."""
    agent_id = uuid4()
    added = store.add(
        ReflectionRecord(agent_id=agent_id, level=ReflectionLevel.MICRO, content="Test")
    )

    retrieved = store.get(added.id)  # type: ignore

    assert retrieved is not None
    assert retrieved.id == added.id
    assert retrieved.content == "Test"


def test_get_returns_none_for_missing_id(store: InMemoryReflectionStore):
    """get() returns None if reflection ID doesn't exist."""
    result = store.get(9999)

    assert result is None


def test_list_by_session_returns_matching_reflections(store: InMemoryReflectionStore):
    """list_by_session() returns reflections for a specific session."""
    agent_id = uuid4()
    session1 = uuid4()
    session2 = uuid4()

    r1 = store.add(
        ReflectionRecord(
            agent_id=agent_id, level=ReflectionLevel.MICRO, session_id=session1, content="S1"
        )
    )
    store.add(
        ReflectionRecord(
            agent_id=agent_id, level=ReflectionLevel.MICRO, session_id=session2, content="S2"
        )
    )

    results = store.list_by_session(session1)

    assert len(results) == 1
    assert results[0].id == r1.id
    assert results[0].session_id == session1


def test_list_by_session_empty_when_no_match(store: InMemoryReflectionStore):
    """list_by_session() returns empty list if no session matches."""
    agent_id = uuid4()
    store.add(
        ReflectionRecord(
            agent_id=agent_id, level=ReflectionLevel.MICRO, session_id=uuid4(), content="Test"
        )
    )

    results = store.list_by_session(uuid4())

    assert results == []


def test_list_recent_returns_newest_first(store: InMemoryReflectionStore):
    """list_recent() returns reflections in reverse chronological order."""
    agent_id = uuid4()
    now = datetime.now(UTC)

    r1 = store.add(
        ReflectionRecord(
            agent_id=agent_id,
            level=ReflectionLevel.MICRO,
            created_at=now - timedelta(hours=2),
            content="Oldest",
        )
    )
    r2 = store.add(
        ReflectionRecord(
            agent_id=agent_id,
            level=ReflectionLevel.MICRO,
            created_at=now - timedelta(hours=1),
            content="Middle",
        )
    )
    r3 = store.add(
        ReflectionRecord(
            agent_id=agent_id, level=ReflectionLevel.MICRO, created_at=now, content="Newest"
        )
    )

    results = store.list_recent(agent_id, limit=10)

    assert len(results) == 3
    assert results[0].id == r3.id  # Newest first
    assert results[1].id == r2.id
    assert results[2].id == r1.id


def test_list_recent_respects_limit(store: InMemoryReflectionStore):
    """list_recent() respects the limit parameter."""
    agent_id = uuid4()

    for i in range(5):
        store.add(ReflectionRecord(agent_id=agent_id, level=ReflectionLevel.MICRO, content=f"R{i}"))

    results = store.list_recent(agent_id, limit=2)

    assert len(results) == 2


def test_list_recent_filters_by_agent(store: InMemoryReflectionStore):
    """list_recent() only returns reflections for the specified agent."""
    agent1 = uuid4()
    agent2 = uuid4()

    store.add(ReflectionRecord(agent_id=agent1, level=ReflectionLevel.MICRO, content="A1"))
    store.add(ReflectionRecord(agent_id=agent2, level=ReflectionLevel.MICRO, content="A2"))
    store.add(ReflectionRecord(agent_id=agent1, level=ReflectionLevel.DAILY, content="A1-2"))

    results = store.list_recent(agent1, limit=10)

    assert len(results) == 2
    assert all(r.agent_id == agent1 for r in results)


def test_list_by_level_filters_correctly(store: InMemoryReflectionStore):
    """list_by_level() returns only reflections at the specified level."""
    agent_id = uuid4()

    r_micro = store.add(
        ReflectionRecord(agent_id=agent_id, level=ReflectionLevel.MICRO, content="Micro")
    )
    store.add(ReflectionRecord(agent_id=agent_id, level=ReflectionLevel.DAILY, content="Daily"))
    r_micro2 = store.add(
        ReflectionRecord(agent_id=agent_id, level=ReflectionLevel.MICRO, content="Micro2")
    )

    results = store.list_by_level(agent_id, ReflectionLevel.MICRO)

    assert len(results) == 2
    assert {r.id for r in results} == {r_micro.id, r_micro2.id}


def test_list_by_level_with_since_filter(store: InMemoryReflectionStore):
    """list_by_level() with since parameter filters by created_at."""
    agent_id = uuid4()
    now = datetime.now(UTC)
    cutoff = now - timedelta(hours=1)

    store.add(
        ReflectionRecord(
            agent_id=agent_id,
            level=ReflectionLevel.DAILY,
            created_at=now - timedelta(hours=2),
            content="Old",
        )
    )
    r_new = store.add(
        ReflectionRecord(
            agent_id=agent_id, level=ReflectionLevel.DAILY, created_at=now, content="New"
        )
    )

    results = store.list_by_level(agent_id, ReflectionLevel.DAILY, since=cutoff)

    assert len(results) == 1
    assert results[0].id == r_new.id


def test_list_by_experience_finds_matching_refs(store: InMemoryReflectionStore):
    """list_by_experience() returns reflections that reference the experience."""
    agent_id = uuid4()
    exp1 = uuid4()
    exp2 = uuid4()

    r1 = store.add(
        ReflectionRecord(
            agent_id=agent_id,
            level=ReflectionLevel.DAILY,
            content="Analyzed exp1",
            experience_refs=[exp1],
        )
    )
    store.add(
        ReflectionRecord(
            agent_id=agent_id,
            level=ReflectionLevel.DAILY,
            content="Analyzed exp2",
            experience_refs=[exp2],
        )
    )
    r3 = store.add(
        ReflectionRecord(
            agent_id=agent_id,
            level=ReflectionLevel.DEEP,
            content="Analyzed both",
            experience_refs=[exp1, exp2],
        )
    )

    results = store.list_by_experience(exp1)

    assert len(results) == 2
    assert {r.id for r in results} == {r1.id, r3.id}


def test_list_by_experience_empty_when_no_refs(store: InMemoryReflectionStore):
    """list_by_experience() returns empty list if experience not referenced."""
    agent_id = uuid4()
    store.add(
        ReflectionRecord(
            agent_id=agent_id,
            level=ReflectionLevel.DAILY,
            content="Test",
            experience_refs=[],
        )
    )

    results = store.list_by_experience(uuid4())

    assert results == []


def test_rls_set_current_agent_filters_list_by_session(store: InMemoryReflectionStore):
    """RLS: list_by_session only returns reflections for current agent."""
    agent1 = uuid4()
    agent2 = uuid4()
    session1 = uuid4()

    store.add(
        ReflectionRecord(
            agent_id=agent1, level=ReflectionLevel.MICRO, session_id=session1, content="A1"
        )
    )
    store.add(
        ReflectionRecord(
            agent_id=agent2, level=ReflectionLevel.MICRO, session_id=session1, content="A2"
        )
    )

    # Set RLS context to agent1
    store.set_current_agent(agent1)
    results = store.list_by_session(session1)

    assert len(results) == 1
    assert results[0].agent_id == agent1


def test_rls_set_current_agent_filters_list_recent(store: InMemoryReflectionStore):
    """RLS: list_recent only returns reflections for current agent."""
    agent1 = uuid4()
    agent2 = uuid4()

    store.add(ReflectionRecord(agent_id=agent1, level=ReflectionLevel.MICRO, content="A1"))
    store.add(ReflectionRecord(agent_id=agent2, level=ReflectionLevel.MICRO, content="A2"))

    store.set_current_agent(agent1)
    results = store.list_recent(agent1, limit=10)

    assert len(results) == 1
    assert results[0].agent_id == agent1


def test_rls_set_current_agent_filters_list_by_level(store: InMemoryReflectionStore):
    """RLS: list_by_level only returns reflections for current agent."""
    agent1 = uuid4()
    agent2 = uuid4()

    store.add(ReflectionRecord(agent_id=agent1, level=ReflectionLevel.DAILY, content="A1"))
    store.add(ReflectionRecord(agent_id=agent2, level=ReflectionLevel.DAILY, content="A2"))

    store.set_current_agent(agent1)
    results = store.list_by_level(agent1, ReflectionLevel.DAILY)

    assert len(results) == 1
    assert results[0].agent_id == agent1


def test_rls_set_current_agent_filters_list_by_experience(store: InMemoryReflectionStore):
    """RLS: list_by_experience only returns reflections for current agent."""
    agent1 = uuid4()
    agent2 = uuid4()
    exp1 = uuid4()

    store.add(
        ReflectionRecord(
            agent_id=agent1, level=ReflectionLevel.DAILY, content="A1", experience_refs=[exp1]
        )
    )
    store.add(
        ReflectionRecord(
            agent_id=agent2, level=ReflectionLevel.DAILY, content="A2", experience_refs=[exp1]
        )
    )

    store.set_current_agent(agent1)
    results = store.list_by_experience(exp1)

    assert len(results) == 1
    assert results[0].agent_id == agent1


def test_rls_none_allows_all_agents(store: InMemoryReflectionStore):
    """RLS: setting current_agent to None disables filtering."""
    agent1 = uuid4()
    agent2 = uuid4()

    store.add(ReflectionRecord(agent_id=agent1, level=ReflectionLevel.MICRO, content="A1"))
    store.add(ReflectionRecord(agent_id=agent2, level=ReflectionLevel.MICRO, content="A2"))

    store.set_current_agent(None)
    results_a1 = store.list_recent(agent1, limit=10)
    results_a2 = store.list_recent(agent2, limit=10)

    # Both agents' reflections are visible when no RLS context is set
    assert len(results_a1) == 1
    assert len(results_a2) == 1


def test_clear_removes_all_reflections(store: InMemoryReflectionStore):
    """clear() removes all stored reflections."""
    agent_id = uuid4()
    store.add(ReflectionRecord(agent_id=agent_id, level=ReflectionLevel.MICRO, content="Test"))

    store.clear()

    results = store.list_recent(agent_id, limit=10)
    assert results == []


def test_clear_resets_id_sequence(store: InMemoryReflectionStore):
    """clear() resets the ID sequence to 1."""
    agent_id = uuid4()
    store.add(ReflectionRecord(agent_id=agent_id, level=ReflectionLevel.MICRO, content="First"))

    store.clear()

    new_record = store.add(
        ReflectionRecord(agent_id=agent_id, level=ReflectionLevel.MICRO, content="After clear")
    )
    assert new_record.id == 1
