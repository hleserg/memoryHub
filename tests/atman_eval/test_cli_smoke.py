from __future__ import annotations

import importlib
from pathlib import Path

import pytest
from click import Group
from click.testing import CliRunner


def _cli_with_noop_registered() -> Group:
    from atman.eval import registry
    from atman.eval.benchmark_runner import cli
    from atman.eval.benchmarks import noop

    registry.clear()
    importlib.reload(noop)
    return cli


def test_cli_list_shows_noop() -> None:
    runner = CliRunner()
    cli = _cli_with_noop_registered()

    result = runner.invoke(cli, ["list"])

    assert result.exit_code == 0
    assert "noop" in result.output


def test_cli_run_noop_writes_jsonl(tmp_path: Path) -> None:
    output_path = tmp_path / "runner.jsonl"
    runner = CliRunner()
    cli = _cli_with_noop_registered()

    result = runner.invoke(
        cli,
        [
            "run",
            "noop",
            "--git-sha",
            "test-sha",
            "--jsonl-output",
            str(output_path),
        ],
    )

    assert result.exit_code == 0
    assert "status=completed" in result.output
    assert output_path.exists()


def test_cli_run_unknown_benchmark_exits_nonzero() -> None:
    runner = CliRunner()
    cli = _cli_with_noop_registered()

    result = runner.invoke(cli, ["run", "missing-benchmark"])

    assert result.exit_code == 1
    assert "status=failed" in result.output
    assert "failed_items=1" in result.output


def test_cli_run_surfaces_reporter_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    from atman.eval import benchmark_runner

    class FailingReporter:
        def __init__(self, dsn: str) -> None:
            self.dsn = dsn

        def on_run_start(self, context: object) -> None:
            _ = context

        def on_run_item(self, context: object, item: object) -> None:
            _ = context, item

        def on_run_complete(self, outcome: object) -> None:
            _ = outcome
            raise RuntimeError("report sink unavailable")

    monkeypatch.setattr(benchmark_runner, "DbReporter", FailingReporter)
    runner = CliRunner()
    cli = _cli_with_noop_registered()

    result = runner.invoke(cli, ["run", "noop", "--db-dsn", "postgresql://example/eval"])

    assert result.exit_code == 0
    assert "status=completed" in result.output
    assert "Reporter errors:" in result.output
    assert "RuntimeError: report sink unavailable" in result.output
