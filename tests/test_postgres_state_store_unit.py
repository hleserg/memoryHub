"""DB-free unit tests for PostgresStateStore v2 row-parsing helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from atman.adapters.state.postgres_state_store import _row_to_key_moment, _row_to_session
from atman.core.models import EmotionalDepth, FeltSense, KeyMoment
from atman.core.models.session import Session


def _moment_row(**overrides) -> dict:
    base = {
        "id": uuid4(),
        "session_id": uuid4(),
        "agent_id": uuid4(),
        "what_happened": "Persisted via v2 schema",
        "emotional_valence": 0.2,
        "emotional_intensity": 0.7,
        "depth": "meaningful",
        "why_it_matters": "Test coverage",
        "values_touched": ["reliability"],
        "principles_confirmed": ["test_storage_boundaries"],
        "principles_questioned": [],
        "what_changed": None,
        "recorded_at": datetime(2026, 5, 12, 10, 30, 0, tzinfo=UTC),
        "salience": 1.0,
        "salience_at": datetime(2026, 5, 12, 10, 30, 0, tzinfo=UTC),
        "last_accessed_at": datetime(2026, 5, 12, 10, 30, 0, tzinfo=UTC),
        "access_count": 0,
        "incomplete_coloring": False,
        "recorded_by": "session_manager",
        "identity_snapshot_id": None,
        "importance": 0.5,
        "fact_refs": [uuid4()],
        "structured_markers": None,
        "structured_markers_version": None,
        "embedding": None,
    }
    base.update(overrides)
    return base


def test_row_to_key_moment_round_trips_basic_fields() -> None:
    row = _moment_row()
    moment = _row_to_key_moment(row)
    assert isinstance(moment, KeyMoment)
    assert moment.id == row["id"]
    assert moment.session_id == row["session_id"]
    assert moment.what_happened == "Persisted via v2 schema"
    assert moment.how_i_felt == FeltSense(
        emotional_valence=0.2, emotional_intensity=0.7, depth=EmotionalDepth.MEANINGFUL
    )
    assert moment.values_touched == ["reliability"]
    assert moment.principles_confirmed == ["test_storage_boundaries"]
    assert moment.salience == 1.0


def test_row_to_key_moment_drops_embedding_column() -> None:
    """The DB column `embedding` is search-side state; the domain model
    intentionally does not surface it."""
    row = _moment_row(embedding="[0.1,0.2,0.3]")
    moment = _row_to_key_moment(row)
    # Domain model doesn't expose embedding — verify by attribute absence
    assert not hasattr(moment, "embedding")


def test_row_to_key_moment_rejects_invalid_depth() -> None:
    row = _moment_row(depth="bogus_depth")
    with pytest.raises(ValueError):
        _row_to_key_moment(row)


def test_row_to_key_moment_preserves_structured_markers() -> None:
    markers = {"cognitive_load": 0.8, "boundary_event": True}
    row = _moment_row(structured_markers=markers, structured_markers_version="1.0")
    moment = _row_to_key_moment(row)
    assert moment.structured_markers == markers
    assert moment.structured_markers_version == "1.0"


def _session_row(**overrides) -> dict:
    base = {
        "id": uuid4(),
        "agent_id": uuid4(),
        "started_at": datetime(2026, 5, 12, 10, 0, 0, tzinfo=UTC),
        "ended_at": None,
        "status": "active",
        "identity_snapshot_id": None,
        "close_reason": None,
        "agent_recap": None,
        "restart_reason": "",
        "user_language": "ru",
        "overall_tone": None,
        "key_insight": None,
        "unexamined_fact_refs": [],
    }
    base.update(overrides)
    return base


def test_row_to_session_round_trips_basic_fields() -> None:
    row = _session_row(status="completed", close_reason="forced", agent_recap="ok")
    session = _row_to_session(row)
    assert isinstance(session, Session)
    assert session.id == row["id"]
    assert session.agent_id == row["agent_id"]
    assert session.status == "completed"
    assert session.close_reason == "forced"
    assert session.agent_recap == "ok"


def test_row_to_session_defaults_for_null_text_fields() -> None:
    row = _session_row(restart_reason=None, user_language=None)
    session = _row_to_session(row)
    assert session.restart_reason == ""
    assert session.user_language == "ru"


def test_row_to_session_preserves_unexamined_fact_refs() -> None:
    fact_ids = [uuid4(), uuid4()]
    row = _session_row(unexamined_fact_refs=fact_ids)
    session = _row_to_session(row)
    assert session.unexamined_fact_refs == fact_ids


def test_list_agent_schemas_query_restricts_to_numeric_serial_suffix() -> None:
    pytest.importorskip("psycopg")
    from atman.adapters.state.postgres_state_store import PostgresStateStore

    store = PostgresStateStore(serial_id=1)
    captured: list[str] = []

    class _FakeCursor:
        def execute(self, query: str, params: object = None) -> None:
            captured.append(query)

        def fetchall(self) -> list[dict[str, str]]:
            return []

    store._list_agent_schemas(_FakeCursor())
    assert captured
    assert "^agent_[0-9]+$" in captured[0]
