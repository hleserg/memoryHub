"""
Integration tests for PostgresFactualMemory.

Runs against a real PostgreSQL database (atman_test).
Requires TEST_DATABASE_URL or DATABASE_URL in .env (database name replaced with atman_test).

Run:
    pytest tests/integration/test_postgres_facts.py -v -m integration
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

# ── Load .env ─────────────────────────────────────────────────────────────────

_env = Path(__file__).parents[2] / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        if _line.strip() and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())


def _replace_db(url: str) -> str:
    """Replace database name /atman → /atman_test in a URL."""
    if url.endswith("/atman"):
        return url[: -len("atman")] + "atman_test"
    return url + "_test"


def _test_db_url() -> str | None:
    """App-role URL for atman_test (atman_app, RLS enforced).
    Prefers TEST_DATABASE_URL, derives from DATABASE_URL otherwise."""
    if url := os.environ.get("TEST_DATABASE_URL"):
        return url
    if url := os.environ.get("DATABASE_URL"):
        return _replace_db(url)
    return None


def _test_admin_db_url() -> str | None:
    """Superuser URL for atman_test — used only for DDL (migrations, TRUNCATE).
    Prefers TEST_ADMIN_DATABASE_URL, derives from ATMAN_ADMIN_DATABASE_URL."""
    if url := os.environ.get("TEST_ADMIN_DATABASE_URL"):
        return url
    if url := os.environ.get("ATMAN_ADMIN_DATABASE_URL"):
        return _replace_db(url)
    # Fallback: if both admin URLs are missing, try the regular test URL
    return _test_db_url()


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def pg_store():
    """
    Module-scoped fixture: applies migration to atman_test, yields the store.
    Migration runs as superuser (DDL); store connects as atman_app (RLS enforced).
    Tables are NOT dropped at the end so results can be inspected.
    """
    import psycopg

    app_url = _test_db_url()
    admin_url = _test_admin_db_url()
    if not app_url:
        pytest.skip("No test DB URL (set TEST_DATABASE_URL or DATABASE_URL in .env)")
    assert admin_url is not None

    # Apply migration as superuser (CREATE TABLE, CREATE INDEX, etc.)
    migration_sql = (
        Path(__file__).parents[2] / "migrations" / "versions" / "0002_create_facts_table.sql"
    ).read_text()

    with psycopg.connect(admin_url) as conn:
        conn.execute(cast(Any, migration_sql))
        conn.commit()

    from atman.adapters.memory.postgres_backend import PostgresFactualMemory

    # Store connects as atman_app so RLS is enforced during tests
    store = PostgresFactualMemory(db_url=app_url)
    store.connect()
    yield store
    store.close()


@pytest.fixture(scope="module")
def pg_admin_conn():
    """Module-scoped superuser connection for DDL operations (TRUNCATE)."""
    import psycopg
    from psycopg.rows import dict_row

    admin_url = _test_admin_db_url()
    if admin_url is None:
        pytest.skip("No admin DB URL (set TEST_ADMIN_DATABASE_URL or TEST_DATABASE_URL)")
    conn = psycopg.connect(admin_url, row_factory=cast(Any, dict_row))
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def clean_facts(pg_store, pg_admin_conn):
    """Function-scoped: truncate facts before each test via superuser connection."""
    pg_store._conn.rollback()  # clear any failed transaction from previous test
    pg_admin_conn.rollback()
    with pg_admin_conn.cursor() as cur:
        cur.execute("TRUNCATE public.facts CASCADE")
    pg_admin_conn.commit()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _agent() -> str:
    """Return a fresh agent UUID as string and set it in the environment."""
    aid = str(uuid4())
    os.environ["ATMAN_CURRENT_AGENT"] = aid
    return aid


def _make_fact(agent_id=None, **kwargs):
    from uuid import UUID

    from atman.core.models.fact import FactRecord

    if agent_id is None:
        agent_id = UUID(os.environ.get("ATMAN_CURRENT_AGENT") or str(uuid4()))
    kwargs.setdefault("content", "Test fact")
    kwargs.setdefault("source", "test")
    return FactRecord(agent_id=agent_id, **kwargs)


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_add_and_get_roundtrip(pg_store):
    _agent()
    fact = _make_fact(content="User prefers dark mode", source="session_1", tags=["preference"])
    stored = pg_store.add_fact(fact)

    fetched = pg_store.get_fact(stored.id)
    assert fetched is not None
    assert fetched.content == "User prefers dark mode"
    assert fetched.source == "session_1"
    assert "preference" in fetched.tags
    assert fetched.salience == pytest.approx(0.5)
    assert fetched.status.value == "active"


@pytest.mark.integration
def test_get_missing_returns_none(pg_store):
    _agent()
    assert pg_store.get_fact(uuid4()) is None


@pytest.mark.integration
def test_search_by_text(pg_store):
    _agent()
    pg_store.add_fact(_make_fact(content="User likes Python programming", source="s1"))
    pg_store.add_fact(_make_fact(content="User dislikes Java", source="s2"))

    results = pg_store.search(query="Python")
    assert len(results) == 1
    assert "Python" in results[0].content


@pytest.mark.integration
def test_search_by_tags(pg_store):
    _agent()
    pg_store.add_fact(_make_fact(content="fact 1", source="s", tags=["tech", "python"]))
    pg_store.add_fact(_make_fact(content="fact 2", source="s", tags=["tech"]))
    pg_store.add_fact(_make_fact(content="fact 3", source="s", tags=["lifestyle"]))

    results = pg_store.search(tags=["tech", "python"])
    assert len(results) == 1
    assert results[0].content == "fact 1"


@pytest.mark.integration
def test_search_combined_query_and_tags(pg_store):
    _agent()
    pg_store.add_fact(_make_fact(content="Python is great", source="s", tags=["tech"]))
    pg_store.add_fact(_make_fact(content="Python is great", source="s", tags=["lifestyle"]))

    results = pg_store.search(query="Python", tags=["tech"])
    assert len(results) == 1
    assert "tech" in results[0].tags


@pytest.mark.integration
def test_search_include_invalidated(pg_store):
    _agent()
    f = pg_store.add_fact(_make_fact(content="old fact", source="s"))
    pg_store.invalidate_fact(f.id)

    assert pg_store.search(query="old") == []
    results = pg_store.search(query="old", include_invalidated=True)
    assert len(results) == 1


@pytest.mark.integration
def test_search_no_embedding_falls_back_to_text(pg_store):
    """When EmbeddingPort raises, search degrades to ILIKE — no exception."""
    from atman.adapters.memory.postgres_backend import PostgresFactualMemory

    bad_embedding = MagicMock()
    bad_embedding.embed.side_effect = RuntimeError("Ollama is down")

    url = _test_db_url()
    fallback_store = PostgresFactualMemory(db_url=url, embedding=bad_embedding)
    fallback_store._conn = pg_store._conn  # share connection, skip reconnect

    _agent()
    pg_store.add_fact(_make_fact(content="fallback search target", source="s"))

    import warnings

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        results = fallback_store.search(query="fallback")

    assert len(results) == 1
    assert any("Embedding failed" in str(w.message) for w in caught)


@pytest.mark.integration
def test_link_creates_relation(pg_store):
    _agent()
    f1 = pg_store.add_fact(_make_fact(content="cause", source="s"))
    f2 = pg_store.add_fact(_make_fact(content="effect", source="s"))

    ok = pg_store.link(f1.id, f2.id, "caused_by")
    assert ok is True

    fetched = pg_store.get_fact(f1.id)
    assert fetched is not None
    assert len(fetched.relations) == 1
    assert fetched.relations[0].target_id == f2.id
    assert fetched.relations[0].relation_type == "caused_by"


@pytest.mark.integration
def test_link_missing_fact_returns_false(pg_store):
    _agent()
    f = pg_store.add_fact(_make_fact(content="real", source="s"))
    assert pg_store.link(f.id, uuid4(), "related_to") is False


@pytest.mark.integration
def test_invalidate_changes_status(pg_store):
    _agent()
    f = pg_store.add_fact(_make_fact(content="old info", source="s"))
    result = pg_store.invalidate_fact(f.id, note="outdated")

    assert result is not None
    assert result.status.value == "invalidated"
    assert result.invalidation_note == "outdated"
    assert result.invalidated_at is not None


@pytest.mark.integration
def test_invalidate_missing_returns_none(pg_store):
    _agent()
    assert pg_store.invalidate_fact(uuid4()) is None


@pytest.mark.integration
def test_invalidate_with_superseded_by_creates_relations(pg_store):
    _agent()
    old = pg_store.add_fact(_make_fact(content="old version", source="s"))
    new = pg_store.add_fact(_make_fact(content="new version", source="s"))

    pg_store.invalidate_fact(old.id, superseded_by=new.id)

    old_fetched = pg_store.get_fact(old.id)
    new_fetched = pg_store.get_fact(new.id)

    assert old_fetched is not None
    old_rel_types = [r.relation_type for r in old_fetched.relations]
    assert "superseded_by" in old_rel_types

    assert new_fetched is not None
    new_rel_types = [r.relation_type for r in new_fetched.relations]
    assert "supersedes" in new_rel_types


@pytest.mark.integration
def test_confirm_fact(pg_store):
    _agent()
    f = pg_store.add_fact(_make_fact(content="fact to confirm", source="s"))
    assert f.confirmation_count == 0

    ok = pg_store.confirm_fact(f.id)
    assert ok is True

    fetched = pg_store.get_fact(f.id)
    assert fetched is not None
    assert fetched.confirmation_count == 1
    assert fetched.salience == pytest.approx(0.6)
    assert fetched.last_confirmed_at is not None


@pytest.mark.integration
def test_confirm_missing_returns_false(pg_store):
    _agent()
    assert pg_store.confirm_fact(uuid4()) is False


@pytest.mark.integration
def test_decay_stale_facts(pg_store):
    _agent()
    f = pg_store.add_fact(_make_fact(content="stale fact", source="s"))

    cutoff = datetime.now(UTC) + timedelta(seconds=1)
    count = pg_store.decay_stale_facts(before=cutoff, decay_factor=0.5)
    assert count == 1

    fetched = pg_store.get_fact(f.id)
    assert fetched is not None
    assert fetched.salience == pytest.approx(0.25)


@pytest.mark.integration
def test_decay_skips_confirmed_recently(pg_store):
    _agent()
    f = pg_store.add_fact(_make_fact(content="fresh fact", source="s"))
    pg_store.confirm_fact(f.id)

    # cutoff in the past — fact was confirmed after cutoff, should NOT decay
    cutoff = datetime.now(UTC) - timedelta(seconds=1)
    count = pg_store.decay_stale_facts(before=cutoff)
    assert count == 0


@pytest.mark.integration
def test_list_recent_order(pg_store):
    _agent()
    pg_store.add_fact(_make_fact(content="first", source="s"))
    pg_store.add_fact(_make_fact(content="second", source="s"))
    pg_store.add_fact(_make_fact(content="third", source="s"))

    recent = pg_store.list_recent(limit=2)
    assert len(recent) == 2
    assert recent[0].content == "third"
    assert recent[1].content == "second"


@pytest.mark.integration
def test_list_invalidated(pg_store):
    _agent()
    active = pg_store.add_fact(_make_fact(content="active fact", source="s"))
    inv = pg_store.add_fact(_make_fact(content="dead fact", source="s"))
    pg_store.invalidate_fact(inv.id)

    results = pg_store.list_invalidated()
    ids = [r.id for r in results]
    assert inv.id in ids
    assert active.id not in ids


@pytest.mark.integration
def test_list_invalidated_since_filter(pg_store):
    _agent()
    old = pg_store.add_fact(_make_fact(content="old dead", source="s"))
    pg_store.invalidate_fact(old.id)

    cutoff = datetime.now(UTC)

    new = pg_store.add_fact(_make_fact(content="new dead", source="s"))
    pg_store.invalidate_fact(new.id)

    results = pg_store.list_invalidated(since=cutoff)
    ids = [r.id for r in results]
    assert new.id in ids
    assert old.id not in ids


@pytest.mark.integration
def test_rls_isolation(pg_store):
    """
    RLS isolates facts per agent when the connection runs as atman_app.

    PostgreSQL superusers bypass RLS unconditionally, so this test opens a
    fresh connection and switches to the non-superuser atman_app role via
    SET ROLE before querying. Superusers can SET ROLE to any role without
    needing an explicit GRANT.

    The atman_app role and its GRANT are created by migration 0002 (the same
    SQL applied by the pg_store fixture above).
    """
    import psycopg
    from psycopg.rows import dict_row

    agent_a = str(uuid4())
    agent_b = str(uuid4())

    from uuid import UUID

    from atman.core.models.fact import FactRecord

    # Write facts as the superuser owner — RLS is not enforced for the owner,
    # but facts land in the table with the correct agent_id FK.
    os.environ["ATMAN_CURRENT_AGENT"] = agent_a
    pg_store.add_fact(FactRecord(agent_id=UUID(agent_a), content="Agent A secret", source="s"))
    os.environ["ATMAN_CURRENT_AGENT"] = agent_b
    pg_store.add_fact(FactRecord(agent_id=UUID(agent_b), content="Agent B data", source="s"))

    url = _test_db_url()
    if url is None:
        pytest.skip("No test DB URL (set TEST_DATABASE_URL or DATABASE_URL in .env)")
    # autocommit=True so that SET ROLE is session-level (not rolled back with the transaction)
    # and set_config(..., false) persists across statements.
    with psycopg.connect(url, row_factory=cast(Any, dict_row), autocommit=True) as rls_conn:
        try:
            rls_conn.execute("SET ROLE atman_app")
        except psycopg.errors.UndefinedObject:
            pytest.skip("atman_app role not found — re-apply migration 0002 to atman_test")

        # ── Agent B sees only its own facts ───────────────────────────────────
        rls_conn.execute("SELECT set_config('atman.current_agent', %s, false)", [agent_b])
        with rls_conn.cursor() as cur:
            cur.execute("SELECT content FROM public.facts")
            contents_b = [cast(dict[str, Any], r)["content"] for r in cur.fetchall()]

        assert "Agent B data" in contents_b, "Agent B cannot see its own fact"
        assert "Agent A secret" not in contents_b, "RLS leak: Agent B sees Agent A's fact"

        # ── Agent A sees only its own facts ───────────────────────────────────
        rls_conn.execute("SELECT set_config('atman.current_agent', %s, false)", [agent_a])
        with rls_conn.cursor() as cur:
            cur.execute("SELECT content FROM public.facts")
            contents_a = [cast(dict[str, Any], r)["content"] for r in cur.fetchall()]

        assert "Agent A secret" in contents_a, "Agent A cannot see its own fact"
        assert "Agent B data" not in contents_a, "RLS leak: Agent A sees Agent B's fact"


@pytest.mark.integration
@pytest.mark.requires_ollama
def test_search_vector_semantic(pg_store):
    """Vector search finds semantically similar facts even without exact keyword match."""
    from atman.adapters.memory.ollama_embedding import OllamaEmbeddingAdapter
    from atman.adapters.memory.postgres_backend import PostgresFactualMemory

    url = _test_db_url()
    embed = OllamaEmbeddingAdapter()
    vec_store = PostgresFactualMemory(db_url=url, embedding=embed)
    vec_store._conn = pg_store._conn

    _agent()
    # Add facts via vec_store so embeddings are generated and stored
    vec_store.add_fact(_make_fact(content="The user enjoys programming in Python", source="s"))
    vec_store.add_fact(_make_fact(content="The user hates rainy weather", source="s"))

    # Query is semantically similar to Python fact, not weather
    results = vec_store.search(query="coding and software development", limit=2)
    assert len(results) > 0
    assert "Python" in results[0].content
