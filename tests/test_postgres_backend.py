"""Unit tests for the PostgreSQL Factual Memory adapter without a real database."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from atman.adapters.memory.postgres_backend import PostgresFactualMemory, _parse_fact, _vec_str
from atman.core.models.fact import FactRecord, FactStatus, Relation

_CREATED_AT = datetime(2026, 5, 11, 10, 0, tzinfo=UTC)


class _FakeCursor:
    def __init__(
        self,
        *,
        rows: list[dict[str, Any]] | None = None,
        fetchone_results: list[dict[str, Any] | None] | None = None,
        rowcount: int = 0,
    ) -> None:
        self.rows = rows or []
        self.fetchone_results = fetchone_results or []
        self.rowcount = rowcount
        self.executed: list[tuple[Any, list[Any] | None]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, query: Any, params: list[Any] | None = None) -> None:
        self.executed.append((query, params))

    def fetchall(self) -> list[dict[str, Any]]:
        return self.rows

    def fetchone(self) -> dict[str, Any] | None:
        if self.fetchone_results:
            return self.fetchone_results.pop(0)
        return None


class _FakeConnection:
    closed = False

    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor
        self.executed: list[tuple[Any, list[Any] | None]] = []
        self.commits = 0
        self.closed_count = 0

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def execute(self, query: Any, params: list[Any] | None = None) -> None:
        self.executed.append((query, params))

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        self.closed_count += 1
        self.closed = True


class _FailingEmbedding:
    def embed(self, text: str) -> list[float]:
        raise RuntimeError(f"embedding service unavailable for {text}")

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] for _ in texts]

    def dimension(self) -> int:
        return 1

    def model_name(self) -> str:
        return "failing"

    def similarity(self, vec1: list[float], vec2: list[float]) -> float:
        return 0.0


class _FixedEmbedding:
    def embed(self, text: str) -> list[float]:
        return [0.25, 0.75]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]

    def dimension(self) -> int:
        return 2

    def model_name(self) -> str:
        return "fixed"

    def similarity(self, vec1: list[float], vec2: list[float]) -> float:
        return 1.0 if vec1 == vec2 else 0.0


def _row(
    *,
    fact_id: UUID | None = None,
    agent_id: UUID | None = None,
    content: str = "stored fact",
    status: str = "active",
    rels: object | None = None,
) -> dict[str, Any]:
    return {
        "id": fact_id or uuid4(),
        "agent_id": agent_id or uuid4(),
        "content": content,
        "source": "session",
        "tags": ["task"],
        "created_at": _CREATED_AT,
        "metadata": {"priority": "high"},
        "status": status,
        "invalidated_at": None,
        "invalidation_note": "",
        "superseded_by": None,
        "disputed_at": None,
        "confirmation_count": 0,
        "last_confirmed_at": None,
        "salience": 0.5,
        "rels": rels if rels is not None else [],
    }


def _memory_with(
    conn: _FakeConnection, *, embedding: object | None = None
) -> PostgresFactualMemory:
    memory = PostgresFactualMemory(
        db_url="postgresql://atman_app:test@localhost:5432/atman",
        embedding=cast(Any, embedding),
    )
    memory._conn = cast(Any, conn)
    return memory


def test_vec_str_serializes_postgres_vector_literal() -> None:
    assert _vec_str([0.1, 2.0, -3.5]) == "[0.1,2.0,-3.5]"


def test_parse_fact_accepts_json_relation_payload() -> None:
    target_id = uuid4()
    relation_payload = json.dumps(
        [
            {
                "target_id": str(target_id),
                "relation_type": "caused_by",
                "created_at": _CREATED_AT.isoformat(),
                "metadata": {"weight": 1},
            }
        ]
    )

    parsed = _parse_fact(_row(rels=relation_payload))

    assert parsed.content == "stored fact"
    assert parsed.relations == [
        Relation(
            target_id=target_id,
            relation_type="caused_by",
            created_at=_CREATED_AT,
            metadata={"weight": 1},
        )
    ]


def test_parse_fact_rejects_malformed_relation_json() -> None:
    with pytest.raises(json.JSONDecodeError):
        _parse_fact(_row(rels="not-json"))


def test_search_falls_back_to_text_when_embedding_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATMAN_CURRENT_AGENT", str(uuid4()))
    cursor = _FakeCursor(rows=[_row(content="needle fact")])
    conn = _FakeConnection(cursor)
    memory = _memory_with(conn, embedding=_FailingEmbedding())

    with pytest.warns(RuntimeWarning, match="Embedding failed"):
        results = memory.search(query="needle", tags=["task"], limit=3)

    assert [fact.content for fact in results] == ["needle fact"]
    assert conn.commits == 1
    assert conn.executed[0][0] == "SELECT set_config('atman.current_agent', %s, true)"
    query, params = cursor.executed[0]
    assert "f.status = 'active'" in query
    assert "f.tags @> %s::text[]" in query
    assert "f.content ILIKE %s" in query
    assert params == [["task"], "%needle%", 3]


def test_search_uses_halfvec_literal_for_semantic_ordering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATMAN_CURRENT_AGENT", str(uuid4()))
    cursor = _FakeCursor(rows=[_row(content="semantic fact")])
    conn = _FakeConnection(cursor)
    memory = _memory_with(conn, embedding=_FixedEmbedding())

    results = memory.search(query="semantic", limit=5)

    assert [fact.content for fact in results] == ["semantic fact"]
    query, params = cursor.executed[0]
    assert "f.embedding <=> '[0.25,0.75]'::halfvec" in query
    assert "f.content ILIKE" not in query
    assert params == [5]


def test_add_fact_persists_embedding_relations_and_agent_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent_id = uuid4()
    monkeypatch.setenv("ATMAN_CURRENT_AGENT", str(agent_id))
    cursor = _FakeCursor()
    conn = _FakeConnection(cursor)
    memory = _memory_with(conn, embedding=_FixedEmbedding())
    target_id = uuid4()
    record = FactRecord(
        content="new fact",
        source="session",
        relations=[Relation(target_id=target_id, relation_type="supports", metadata={"rank": 1})],
    )

    stored = memory.add_fact(record)

    assert stored.agent_id == agent_id
    assert conn.commits == 1
    assert conn.executed == [
        ("SELECT set_config('atman.current_agent', %s, true)", [str(agent_id)])
    ]
    assert len(cursor.executed) == 2
    insert_query, insert_params = cursor.executed[0]
    relation_query, relation_params = cursor.executed[1]
    assert "INSERT INTO public.facts" in insert_query
    assert insert_params is not None
    assert insert_params[-1] == "[0.25,0.75]"
    assert "INSERT INTO public.fact_relations" in relation_query
    assert relation_params is not None
    assert relation_params[:3] == [str(record.id), str(target_id), "supports"]


def test_invalidate_fact_returns_none_when_update_misses() -> None:
    cursor = _FakeCursor(fetchone_results=[None])
    conn = _FakeConnection(cursor)
    memory = _memory_with(conn)

    result = memory.invalidate_fact(uuid4(), note="not found")

    assert result is None
    assert conn.commits == 1
    assert "UPDATE public.facts" in cursor.executed[0][0]


def test_invalidate_fact_links_supersession_and_reloads() -> None:
    fact_id = uuid4()
    superseded_by = uuid4()
    cursor = _FakeCursor(fetchone_results=[{"id": fact_id}], rows=[_row(fact_id=fact_id)])
    conn = _FakeConnection(cursor)
    memory = _memory_with(conn)

    result = memory.invalidate_fact(
        fact_id,
        status=FactStatus.SUPERSEDED,
        note="replaced",
        superseded_by=superseded_by,
    )

    assert result is not None
    assert result.id == fact_id
    assert conn.commits == 2
    relation_params = [
        params
        for query, params in cursor.executed
        if "fact_relations" in query and params is not None
    ]
    assert relation_params[0][:3] == [str(fact_id), str(superseded_by), "superseded_by"]
    assert relation_params[1][:3] == [str(superseded_by), str(fact_id), "supersedes"]


def test_link_returns_false_without_both_facts() -> None:
    cursor = _FakeCursor(fetchone_results=[{"count": 1}])
    conn = _FakeConnection(cursor)
    memory = _memory_with(conn)

    assert memory.link(uuid4(), uuid4(), "related_to") is False
    assert conn.commits == 1
    assert len(cursor.executed) == 1


def test_link_inserts_relation_when_both_facts_exist() -> None:
    source_id = uuid4()
    target_id = uuid4()
    cursor = _FakeCursor(fetchone_results=[{"count": 2}])
    conn = _FakeConnection(cursor)
    memory = _memory_with(conn)

    assert memory.link(source_id, target_id, "related_to") is True

    assert conn.commits == 1
    assert len(cursor.executed) == 2
    relation_params = cursor.executed[1][1]
    assert relation_params is not None
    assert relation_params[:3] == [str(source_id), str(target_id), "related_to"]


def test_confirm_fact_and_decay_stale_facts_return_database_results() -> None:
    confirm_cursor = _FakeCursor(fetchone_results=[{"id": uuid4()}])
    confirm_conn = _FakeConnection(confirm_cursor)
    confirm_memory = _memory_with(confirm_conn)

    assert confirm_memory.confirm_fact(uuid4()) is True
    assert confirm_conn.commits == 1
    assert "confirmation_count = confirmation_count + 1" in confirm_cursor.executed[0][0]

    decay_cursor = _FakeCursor(rowcount=7)
    decay_conn = _FakeConnection(decay_cursor)
    decay_memory = _memory_with(decay_conn)

    assert decay_memory.decay_stale_facts(_CREATED_AT, decay_factor=0.25) == 7
    assert decay_conn.commits == 1
    assert decay_cursor.executed[0][1] == [0.25, _CREATED_AT]


def test_list_helpers_delegate_to_expected_filters() -> None:
    recent_cursor = _FakeCursor(rows=[_row(content="recent")])
    recent_memory = _memory_with(_FakeConnection(recent_cursor))
    assert recent_memory.list_recent(limit=2)[0].content == "recent"
    assert "WHERE TRUE" in recent_cursor.executed[0][0]
    assert recent_cursor.executed[0][1] == [2]

    invalid_cursor = _FakeCursor(rows=[_row(content="invalid", status="invalidated")])
    invalid_memory = _memory_with(_FakeConnection(invalid_cursor))
    assert invalid_memory.list_invalidated(since=_CREATED_AT)[0].content == "invalid"
    assert "f.status != 'active'" in invalid_cursor.executed[0][0]
    assert invalid_cursor.executed[0][1] == [_CREATED_AT]
