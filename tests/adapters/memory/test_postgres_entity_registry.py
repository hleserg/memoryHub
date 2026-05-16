"""Tests for PostgresEntityRegistry.

These tests require a running Postgres database with all migrations applied.
Skipped if the ``TEST_DB_URL`` environment variable is not set.

Contract mirrors ``TestInMemoryEntityRegistry`` in
``tests/test_new_v3_adapters.py``.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

# Skip the whole module if psycopg is not available or if no test database.
try:
    import psycopg  # noqa: F401

    from atman.adapters.memory.postgres_entity_registry import PostgresEntityRegistry

    PSYCOPG_AVAILABLE = True
except ImportError:
    PSYCOPG_AVAILABLE = False

from atman.core.models.entity import EntityType, ResolutionMethod

pytestmark = [
    pytest.mark.skipif(not PSYCOPG_AVAILABLE, reason="psycopg not installed"),
    pytest.mark.skipif(
        not os.environ.get("TEST_DB_URL"),
        reason="TEST_DB_URL not set",
    ),
]


@pytest.fixture
def db_url() -> str:
    """Return test database URL from environment."""
    return os.environ.get("TEST_DB_URL", "postgresql://atman@localhost:5432/atman_test")


@pytest.fixture
def agent_record(db_url: str) -> tuple[UUID, int]:
    """Create a fresh agent and provision its per-agent schema.

    Returns (agent_id, serial_id).
    """
    import psycopg as _psycopg

    with _psycopg.connect(db_url) as conn, conn.transaction():
        row = conn.execute(
            """
            INSERT INTO public.agents (name, description)
            VALUES (%s, %s)
            RETURNING id, serial_id
            """,
            ["test-entity-registry-agent", "entity registry test agent"],
        ).fetchone()
        assert row is not None
        agent_id: UUID = row[0]
        serial_id: int = row[1]

        conn.execute(
            "SELECT public.create_agent_schema(%s, %s)",
            [agent_id, serial_id],
        )

    return agent_id, serial_id


@pytest.fixture
def reg(db_url: str, agent_record: tuple[UUID, int]) -> Any:
    """Create a PostgresEntityRegistry bound to the test agent's schema.

    Cleans entities + entity_aliases for the agent before each test.
    """
    _, serial_id = agent_record
    r = PostgresEntityRegistry(db_url=db_url, serial_id=serial_id)  # type: ignore[possibly-unbound]
    conn = r._get_conn()
    with conn.cursor() as cur:
        cur.execute(f"DELETE FROM agent_{serial_id}.entity_aliases")  # type: ignore[arg-type]
        cur.execute(f"DELETE FROM agent_{serial_id}.entities")  # type: ignore[arg-type]
    conn.commit()
    return r


# ---------------------------------------------------------------------------
# Tests mirroring TestInMemoryEntityRegistry
# ---------------------------------------------------------------------------


def test_l3_create_new_entity(reg: Any, agent_record: tuple[UUID, int]) -> None:
    agent_id, _ = agent_record
    ent, method = reg.resolve_or_create(agent_id, "Alice", EntityType.person)
    assert method is ResolutionMethod.L3_new
    assert ent.canonical_name == "Alice"
    assert ent.agent_id == agent_id


def test_l1_exact_canonical_returns_existing(reg: Any, agent_record: tuple[UUID, int]) -> None:
    agent_id, _ = agent_record
    first, _ = reg.resolve_or_create(agent_id, "Alice", EntityType.person)
    second, method = reg.resolve_or_create(agent_id, "alice", EntityType.person)
    assert method is ResolutionMethod.L1_exact
    assert second.id == first.id


def test_l1_exact_via_alias_resolves(reg: Any, agent_record: tuple[UUID, int]) -> None:
    agent_id, _ = agent_record
    ent, _ = reg.resolve_or_create(agent_id, "Alice", EntityType.person, alias_text="Al")
    again, method = reg.resolve_or_create(agent_id, "Bob", EntityType.person, alias_text="Al")
    assert method is ResolutionMethod.L1_exact
    assert again.id == ent.id


def test_l2_embedding_match_above_threshold(reg: Any, agent_record: tuple[UUID, int]) -> None:
    agent_id, _ = agent_record
    # 1024-dim halfvec to satisfy the schema; only first dim is non-zero.
    vec_a: list[float] = [1.0] + [0.0] * 1023
    vec_b: list[float] = [0.99] + [0.0] * 1023  # cosine ~ 1.0
    a, _ = reg.resolve_or_create(agent_id, "ProjectX", EntityType.topic, embedding=vec_a)
    b, method = reg.resolve_or_create(agent_id, "Project-X", EntityType.topic, embedding=vec_b)
    assert method is ResolutionMethod.L2_embedding
    assert b.id == a.id


def test_l2_embedding_below_threshold_creates_new(reg: Any, agent_record: tuple[UUID, int]) -> None:
    agent_id, _ = agent_record
    vec_a: list[float] = [1.0, 0.0] + [0.0] * 1022
    vec_b: list[float] = [0.0, 1.0] + [0.0] * 1022  # orthogonal — cosine = 0
    reg.resolve_or_create(agent_id, "Alpha", EntityType.topic, embedding=vec_a)
    _b, method = reg.resolve_or_create(agent_id, "Beta", EntityType.topic, embedding=vec_b)
    assert method is ResolutionMethod.L3_new
    listed = reg.list_entities(agent_id)
    assert len(listed) == 2


def test_get_entity(reg: Any, agent_record: tuple[UUID, int]) -> None:
    agent_id, _ = agent_record
    ent, _ = reg.resolve_or_create(agent_id, "X", EntityType.topic)
    fetched = reg.get_entity(ent.id)
    assert fetched is not None
    assert fetched.id == ent.id
    assert reg.get_entity(uuid4()) is None


def test_find_by_name_returns_match_via_canonical_and_alias(
    reg: Any, agent_record: tuple[UUID, int]
) -> None:
    agent_id, _ = agent_record
    ent, _ = reg.resolve_or_create(agent_id, "Alice", EntityType.person, alias_text="Al")

    results = reg.find_by_name(agent_id, "Alice")
    assert [e.id for e in results] == [ent.id]

    results_alias = reg.find_by_name(agent_id, "Al")
    assert [e.id for e in results_alias] == [ent.id]

    results_filtered = reg.find_by_name(agent_id, "Alice", entity_type=EntityType.organization)
    assert results_filtered == []


def test_add_alias_appends_and_dedupes(reg: Any, agent_record: tuple[UUID, int]) -> None:
    agent_id, _ = agent_record
    ent, _ = reg.resolve_or_create(agent_id, "Alice", EntityType.person)
    a1 = reg.add_alias(ent.id, "Liz")
    a2 = reg.add_alias(ent.id, "liz")  # case dedup
    assert a1.alias_text == "liz"
    assert a2.alias_text == "liz"
    assert a1.id == a2.id


def test_add_alias_unknown_entity_raises(reg: Any) -> None:
    with pytest.raises(KeyError):
        reg.add_alias(uuid4(), "x")


def test_merge_entities_moves_aliases(reg: Any, agent_record: tuple[UUID, int]) -> None:
    agent_id, _ = agent_record
    src, _ = reg.resolve_or_create(agent_id, "AliceA", EntityType.person, alias_text="A1")
    tgt, _ = reg.resolve_or_create(agent_id, "AliceB", EntityType.person)

    reg.merge_entities(src.id, tgt.id, reason="duplicate")

    results = reg.find_by_name(agent_id, "A1")
    assert tgt.id in [e.id for e in results]

    loaded_src = reg.get_entity(src.id)
    assert loaded_src is not None
    assert loaded_src.needs_disambiguation is True


def test_merge_entities_unknown_raises(reg: Any, agent_record: tuple[UUID, int]) -> None:
    agent_id, _ = agent_record
    ent, _ = reg.resolve_or_create(agent_id, "x", EntityType.topic)
    with pytest.raises(KeyError):
        reg.merge_entities(uuid4(), ent.id, reason="r")
    with pytest.raises(KeyError):
        reg.merge_entities(ent.id, uuid4(), reason="r")


def test_update_last_seen_increments_mention(reg: Any, agent_record: tuple[UUID, int]) -> None:
    agent_id, _ = agent_record
    ent, _ = reg.resolve_or_create(agent_id, "x", EntityType.topic)
    before = ent.mention_count
    reg.update_last_seen(ent.id)
    loaded = reg.get_entity(ent.id)
    assert loaded is not None
    assert loaded.mention_count == before + 1
    # Unknown is a silent no-op.
    reg.update_last_seen(uuid4())


def test_list_entities_orders_by_last_seen_desc(
    reg: Any, agent_record: tuple[UUID, int], db_url: str
) -> None:
    agent_id, serial_id = agent_record
    a, _ = reg.resolve_or_create(agent_id, "A", EntityType.topic)
    b, _ = reg.resolve_or_create(agent_id, "B", EntityType.topic)

    # Force b to have a later last_seen_at directly via SQL.
    import psycopg as _psycopg

    future = datetime.now(UTC) + timedelta(seconds=10)
    with _psycopg.connect(db_url) as conn, conn.transaction():
        conn.execute(
            f"UPDATE agent_{serial_id}.entities SET last_seen_at = %s WHERE id = %s",  # type: ignore[arg-type]
            [future, b.id],
        )

    result = reg.list_entities(agent_id)
    assert result[0].id == b.id
    assert {e.id for e in result} == {a.id, b.id}

    only_topic = reg.list_entities(agent_id, entity_type=EntityType.topic)
    assert len(only_topic) == 2
    only_person = reg.list_entities(agent_id, entity_type=EntityType.person)
    assert only_person == []


def test_flag_disambiguation(reg: Any, agent_record: tuple[UUID, int]) -> None:
    agent_id, _ = agent_record
    ent, _ = reg.resolve_or_create(agent_id, "x", EntityType.topic)
    reg.flag_disambiguation(ent.id)
    loaded = reg.get_entity(ent.id)
    assert loaded is not None
    assert loaded.needs_disambiguation is True
    # Unknown is a silent no-op.
    reg.flag_disambiguation(uuid4())


def test_context_manager_closes(db_url: str, agent_record: tuple[UUID, int]) -> None:
    """PostgresEntityRegistry works as a context manager."""
    _, serial_id = agent_record
    with PostgresEntityRegistry(db_url=db_url, serial_id=serial_id) as r:  # type: ignore[possibly-unbound]
        _ = r._get_conn()
        assert r._conn is not None
        assert not r._conn.closed
    assert r._conn is not None
    assert r._conn.closed
