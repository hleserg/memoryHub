from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from types import ModuleType

import pytest


class FakeCursor:
    def __init__(self) -> None:
        self.statements: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> bool:
        _ = exc_type, exc, traceback
        return False

    def execute(self, query: str, params: tuple[object, ...]) -> None:
        self.statements.append((query, params))

    def fetchone(self) -> tuple[int]:
        return (123,)


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self.cursor_obj = cursor
        self.committed = False

    def __enter__(self) -> FakeConnection:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> bool:
        _ = exc_type, exc, traceback
        return False

    def cursor(self) -> FakeCursor:
        return self.cursor_obj

    def commit(self) -> None:
        self.committed = True


def test_db_reporter_persists_run_and_items_without_real_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from atman.eval.reporters.db_reporter import DbReporter
    from atman.eval.run_context import RunContext
    from atman.eval.runner_core import BenchmarkItemResult, BenchmarkRunOutcome

    cursor = FakeCursor()
    connection = FakeConnection(cursor)
    connect_calls: list[str] = []

    def connect(dsn: str) -> FakeConnection:
        connect_calls.append(dsn)
        return connection

    fake_psycopg = ModuleType("psycopg")
    fake_psycopg.__dict__["connect"] = connect
    monkeypatch.setitem(sys.modules, "psycopg", fake_psycopg)

    context = RunContext.create(
        benchmark_key="noop",
        seed=7,
        git_sha="abc123",
        agent_config_id="agent-a",
        identity_snapshot_id=42,
        hardware={"cpu": "fake"},
        extra_metadata={"suite": "db-reporter"},
    )
    item = BenchmarkItemResult(
        item_key="item-1",
        verdict="pass",
        score=0.99,
        expected_value="expected",
        actual_value="actual",
        metadata={"case": "happy-path"},
    )
    outcome = BenchmarkRunOutcome(
        context=context,
        status="completed",
        total_items=1,
        passed_items=1,
        failed_items=0,
        started_at=context.started_at,
        completed_at=datetime(2026, 5, 16, 10, 0, tzinfo=UTC),
        items=[item],
        metadata={"benchmark_metadata": "kept"},
        reporter_errors=("previous reporter warning",),
    )

    reporter = DbReporter("postgresql://example/eval")
    reporter.on_run_start(context)
    reporter.on_run_item(context, item)
    reporter.on_run_complete(outcome)

    assert connect_calls == ["postgresql://example/eval"]
    assert connection.committed is True
    assert len(cursor.statements) == 2

    run_sql, run_params = cursor.statements[0]
    assert "INSERT INTO eval.benchmark_runs" in run_sql
    assert run_params[:9] == (
        "noop",
        "agent-a",
        42,
        context.started_at,
        outcome.completed_at,
        "completed",
        1,
        1,
        0,
    )
    run_metadata = json.loads(str(run_params[9]))
    assert run_metadata["app_run_id"] == context.run_id
    assert run_metadata["git_sha"] == "abc123"
    assert run_metadata["seed"] == 7
    assert run_metadata["hardware"] == {"cpu": "fake"}
    assert run_metadata["extra"] == {"suite": "db-reporter"}
    assert run_metadata["benchmark_metadata"] == "kept"
    assert run_metadata["reporter_errors"] == ["previous reporter warning"]

    item_sql, item_params = cursor.statements[1]
    assert "INSERT INTO eval.run_items" in item_sql
    assert item_params == (
        123,
        "item-1",
        "pass",
        0.99,
        "expected",
        "actual",
        None,
        '{"case": "happy-path"}',
    )
