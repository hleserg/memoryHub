"""
Regression tests for eval Alembic migrations.

SYSTEM_MAP §5.1 regression freeze: eval.benchmark_runs must keep accepting
writes after the calendar month changes, even before monthly partition
maintenance exists.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import UTC, datetime, tzinfo
from importlib.abc import Loader
from pathlib import Path
from typing import Protocol, cast

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "eval"
    / "migrations"
    / "versions"
    / "0020_create_benchmark_runs.py"
)
_SQL_MIRROR_PATH = _MIGRATION_PATH.with_suffix(".sql")


class _MockConnection:
    def execute(self, statement: str) -> _MockConnection:
        return self

    def fetchone(self) -> tuple[int]:
        return (1,)


class _RecordingOp:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement: str) -> None:
        self.statements.append(statement)

    def get_bind(self) -> _MockConnection:
        return _MockConnection()


class _FakeAlembicModule(types.ModuleType):
    op: _RecordingOp


class _BenchmarkRunsMigration(Protocol):
    datetime: type[datetime]

    def upgrade(self) -> None: ...

    def _current_month_partition_sql(self) -> str: ...


def _load_benchmark_runs_migration(recording_op: _RecordingOp) -> _BenchmarkRunsMigration:
    fake_alembic = _FakeAlembicModule("alembic")
    fake_alembic.op = recording_op
    previous_alembic = sys.modules.get("alembic")
    sys.modules["alembic"] = fake_alembic
    try:
        spec = importlib.util.spec_from_file_location(
            "atman_eval_migration_0020_create_benchmark_runs",
            _MIGRATION_PATH,
        )
        assert spec is not None
        loader = spec.loader
        assert isinstance(loader, Loader)
        module = importlib.util.module_from_spec(spec)
        loader.exec_module(module)
        return cast(_BenchmarkRunsMigration, module)
    finally:
        if previous_alembic is None:
            sys.modules.pop("alembic", None)
        else:
            sys.modules["alembic"] = previous_alembic


def test_benchmark_runs_migration_creates_default_partition_safety_net() -> None:
    recording_op = _RecordingOp()
    migration = _load_benchmark_runs_migration(recording_op)

    migration.upgrade()

    current_partition_index = next(
        index
        for index, statement in enumerate(recording_op.statements)
        if "PARTITION OF eval.benchmark_runs" in statement and "DEFAULT" not in statement
    )
    default_partition_index = next(
        index
        for index, statement in enumerate(recording_op.statements)
        if "PARTITION OF eval.benchmark_runs DEFAULT" in statement
    )
    assert current_partition_index < default_partition_index
    assert any("eval.benchmark_runs_default" in statement for statement in recording_op.statements)


def test_benchmark_runs_migration_rolls_december_partition_to_next_year() -> None:
    class _FixedDatetime(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:
            return datetime(2026, 12, 31, 23, 59, tzinfo=UTC)

    recording_op = _RecordingOp()
    migration = _load_benchmark_runs_migration(recording_op)
    migration.datetime = _FixedDatetime

    partition_sql = migration._current_month_partition_sql()

    assert "eval.benchmark_runs_2026_12" in partition_sql
    assert "FOR VALUES FROM ('2026-12-01 00:00:00+00')" in partition_sql
    assert "TO ('2027-01-01 00:00:00+00')" in partition_sql


def test_benchmark_runs_sql_mirror_documents_default_partition_safety_net() -> None:
    sql_mirror = _SQL_MIRROR_PATH.read_text(encoding="utf-8")

    current_partition_index = sql_mirror.index(
        "CREATE TABLE IF NOT EXISTS eval.benchmark_runs_YYYY_MM"
    )
    default_partition_index = sql_mirror.index(
        "CREATE TABLE IF NOT EXISTS eval.benchmark_runs_default"
    )

    assert current_partition_index < default_partition_index
    assert "PARTITION OF eval.benchmark_runs DEFAULT" in sql_mirror
