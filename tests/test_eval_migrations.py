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
from importlib.abc import Loader
from pathlib import Path
from typing import Protocol, cast

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "eval"
    / "migrations"
    / "versions"
    / "0011_create_benchmark_runs.py"
)


class _RecordingOp:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def execute(self, statement: str) -> None:
        self.statements.append(statement)


class _FakeAlembicModule(types.ModuleType):
    op: _RecordingOp


class _BenchmarkRunsMigration(Protocol):
    def upgrade(self) -> None: ...


def _load_benchmark_runs_migration(recording_op: _RecordingOp) -> _BenchmarkRunsMigration:
    fake_alembic = _FakeAlembicModule("alembic")
    fake_alembic.op = recording_op
    previous_alembic = sys.modules.get("alembic")
    sys.modules["alembic"] = fake_alembic
    try:
        spec = importlib.util.spec_from_file_location(
            "atman_eval_migration_0011_create_benchmark_runs",
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
