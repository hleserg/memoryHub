from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner


def test_cli_list_shows_noop() -> None:
    from atman.eval.benchmark_runner import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["list"])
    assert result.exit_code == 0
    assert "noop" in result.output


def test_cli_run_noop_writes_jsonl(tmp_path: Path) -> None:
    from atman.eval.benchmark_runner import cli

    output_path = tmp_path / "runner.jsonl"
    runner = CliRunner()
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
