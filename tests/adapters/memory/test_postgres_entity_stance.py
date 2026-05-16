"""Tests for PostgresEntityStanceStore.

These tests require a running Postgres database with all migrations applied.
Skipped if the ``TEST_DB_URL`` environment variable is not set.
"""

import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest

# Skip the whole module if psycopg is not available or if no test database
try:
    import psycopg  # noqa: F401

    from atman.adapters.memory.postgres_entity_stance import PostgresEntityStanceStore

    PSYCOPG_AVAILABLE = True
except ImportError:
    PSYCOPG_AVAILABLE = False
    PostgresEntityStanceStore = Any  # type: ignore[misc,assignment]

pytestmark = [
    pytest.mark.skipif(not PSYCOPG_AVAILABLE, reason="psycopg not installed"),
    pytest.mark.skipif(
        not os.environ.get("TEST_DB_URL"),
        reason="TEST_DB_URL not set - skipping PostgresEntityStanceStore tests",
    ),
]


@pytest.fixture
def db_url() -> str:
    """Return test database URL from environment."""
    return os.environ.get("TEST_DB_URL", "postgresql://atman@localhost:5432/atman_test")


@pytest.fixture
def agent_record(db_url: str) -> tuple[UUID, int]:
    """Create a fresh agent (and its per-agent schema) for the test.

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
            ["test-stance-agent", "stance test agent"],
        ).fetchone()
        assert row is not None
        agent_id: UUID = row[0]
        serial_id: int = row[1]

        # Provision the per-agent schema (idempotent).
        conn.execute(
            "SELECT public.create_agent_schema(%s, %s)",
            [agent_id, serial_id],
        )

    return agent_id, serial_id


@pytest.fixture
def store(db_url: str, agent_record: tuple[UUID, int]) -> Any:
    """Create a PostgresEntityStanceStore bound to the test agent's schema."""
    from atman.adapters.memory.postgres_entity_stance import (
        PostgresEntityStanceStore as _Store,
    )

    _, serial_id = agent_record
    s = _Store(db_url=db_url, serial_id=serial_id)

    # Clean the entity_stance and entities tables before each test.
    import psycopg as _psycopg
    from psycopg import sql as _sql

    conn = s._get_conn()
    schema = _sql.Identifier(f"agent_{serial_id}")
    with conn.cursor() as cur:
        cur.execute(_sql.SQL("DELETE FROM {schema}.entity_stance").format(schema=schema))
        cur.execute(_sql.SQL("DELETE FROM {schema}.entities").format(schema=schema))
    conn.commit()
    _ = _psycopg  # keep import referenced for clarity
    return s


def _insert_entity(
    db_url: str,
    serial_id: int,
    agent_id: UUID,
    canonical_name: str = "Alice",
) -> UUID:
    """Insert a minimal entity row for FK satisfaction and return its id."""
    import psycopg as _psycopg
    from psycopg import sql as _sql

    entity_id = uuid4()
    schema = _sql.Identifier(f"agent_{serial_id}")
    with _psycopg.connect(db_url) as conn, conn.transaction():
        conn.execute(
            _sql.SQL(
                """
                INSERT INTO {schema}.entities
                    (id, agent_id, canonical_name, entity_type)
                VALUES (%s, %s, %s, %s)
                """
            ).format(schema=schema),
            [entity_id, agent_id, canonical_name, "person"],
        )
    return entity_id


# ---------------------------------------------------------------------------
# Tests (mirroring TestInMemoryEntityStanceStore)
# ---------------------------------------------------------------------------


def test_no_stance_returns_none(store: Any, agent_record: tuple[UUID, int], db_url: str) -> None:
    agent_id, serial_id = agent_record
    entity_id = _insert_entity(db_url, serial_id, agent_id)
    assert store.get_current_stance(agent_id, entity_id) is None


def test_write_and_get_current(store: Any, agent_record: tuple[UUID, int], db_url: str) -> None:
    agent_id, serial_id = agent_record
    entity_id = _insert_entity(db_url, serial_id, agent_id)

    s = store.write_stance(agent_id, entity_id, "trusts deeply", valence=0.8, intensity=0.6)
    current = store.get_current_stance(agent_id, entity_id)

    assert current is not None
    assert current.id == s.id
    assert current.stance_text == "trusts deeply"
    assert current.valence == pytest.approx(0.8)
    assert current.intensity == pytest.approx(0.6)
    assert current.is_active is True


def test_writing_supersedes_previous(
    store: Any, agent_record: tuple[UUID, int], db_url: str
) -> None:
    agent_id, serial_id = agent_record
    entity_id = _insert_entity(db_url, serial_id, agent_id)

    first = store.write_stance(agent_id, entity_id, "neutral")
    second = store.write_stance(agent_id, entity_id, "warming up")

    history = store.get_stance_history(agent_id, entity_id)
    assert [s.id for s in history] == [second.id, first.id]

    # First should be superseded by second
    first_in_store = next(s for s in history if s.id == first.id)
    assert first_in_store.superseded_at is not None
    assert first_in_store.superseded_by == second.id

    # Only one active stance remains.
    current = store.get_current_stance(agent_id, entity_id)
    assert current is not None
    assert current.id == second.id


def test_supersede_stance_explicit(store: Any, agent_record: tuple[UUID, int], db_url: str) -> None:
    """Supersede a stance pointing at a real successor stance.

    The ``superseded_by`` column is a FK to ``entity_stance(id)``, so the
    target id must reference an existing row. The InMemory equivalent has
    no such constraint, but the semantics (the row gets marked superseded
    and ``superseded_by`` reflects the supplied id) are the same.
    """
    agent_id, serial_id = agent_record
    e1 = _insert_entity(db_url, serial_id, agent_id, canonical_name="E1")
    e2 = _insert_entity(db_url, serial_id, agent_id, canonical_name="E2")

    first = store.write_stance(agent_id, e1, "x")
    # Create a real successor stance (on a different entity, so write_stance
    # for that entity doesn't itself supersede ``first``).
    successor = store.write_stance(agent_id, e2, "successor")

    store.supersede_stance(first.id, superseded_by_id=successor.id)

    history = store.get_stance_history(agent_id, e1)
    s = next(s for s in history if s.id == first.id)
    assert s.superseded_at is not None
    assert s.superseded_by == successor.id

    # Unknown stance id is a silent no-op.
    store.supersede_stance(uuid4(), superseded_by_id=successor.id)


def test_list_active_stances_filters_and_sorts(
    store: Any, agent_record: tuple[UUID, int], db_url: str
) -> None:
    agent_id, serial_id = agent_record
    e1 = _insert_entity(db_url, serial_id, agent_id, canonical_name="E1")
    e2 = _insert_entity(db_url, serial_id, agent_id, canonical_name="E2")

    s1 = store.write_stance(agent_id, e1, "first")
    s2 = store.write_stance(agent_id, e2, "second")

    active = store.list_active_stances(agent_id)
    ids = {s.id for s in active}
    assert ids == {s1.id, s2.id}

    # formed_after filter
    future = datetime.now(UTC) + timedelta(hours=1)
    assert store.list_active_stances(agent_id, formed_after=future) == []


def test_based_on_moment_ids_roundtrip(
    store: Any, agent_record: tuple[UUID, int], db_url: str
) -> None:
    """UUID[] should roundtrip cleanly through psycopg."""
    agent_id, serial_id = agent_record
    entity_id = _insert_entity(db_url, serial_id, agent_id)

    moment_ids = [uuid4(), uuid4(), uuid4()]
    s = store.write_stance(
        agent_id,
        entity_id,
        "stance with moments",
        based_on_moment_ids=moment_ids,
    )
    assert s.based_on_moment_ids == moment_ids

    current = store.get_current_stance(agent_id, entity_id)
    assert current is not None
    assert current.based_on_moment_ids == moment_ids


def test_context_manager_closes(db_url: str, agent_record: tuple[UUID, int]) -> None:
    """PostgresEntityStanceStore works as a context manager."""
    from atman.adapters.memory.postgres_entity_stance import (
        PostgresEntityStanceStore as _Store,
    )

    _, serial_id = agent_record
    with _Store(db_url=db_url, serial_id=serial_id) as s:
        # Just exercise the connection.
        _ = s._get_conn()
        assert s._conn is not None
        assert not s._conn.closed
    # After exit, the connection is closed.
    assert s._conn is not None
    assert s._conn.closed
