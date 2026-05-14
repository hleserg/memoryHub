"""Module entrypoint for E1 benchmark runner CLI.

Run via:
    python -m atman.eval.benchmark_runner list
    python -m atman.eval.benchmark_runner run noop
"""

from __future__ import annotations

from pathlib import Path

import click

from atman.eval import benchmarks
from atman.eval.registry import list_benchmarks
from atman.eval.reporters.base import Reporter
from atman.eval.reporters.db_reporter import DbReporter
from atman.eval.reporters.jsonl_reporter import JsonlReporter
from atman.eval.runner_core import RunnerCore
from atman.term import print_banner, print_err, print_info, print_ok, print_section

# Keep an explicit reference so static analyzers do not treat import as unused.
_BENCHMARKS_IMPORTED = benchmarks


@click.group(name="benchmark-runner")
def cli() -> None:
    """Evaluation benchmark runner."""


@cli.command(name="list")
def list_command() -> None:
    """List registered benchmark keys."""
    print_banner("Atman Eval Runner", "Registered benchmarks")
    registered = list_benchmarks()
    if not registered:
        print_err("No benchmarks registered.")
        raise SystemExit(1)
    for key in registered:
        print_info(f"- {key}")
    print_ok(f"Total benchmarks: {len(registered)}")


@cli.command(name="run")
@click.argument("benchmark_key", type=str)
@click.option("--seed", type=int, default=None, help="Deterministic seed override.")
@click.option("--git-sha", type=str, default=None, help="Git SHA for idempotent run reuse.")
@click.option("--agent-config-id", type=str, default=None, help="Optional agent config ID.")
@click.option(
    "--identity-snapshot-id",
    type=int,
    default=None,
    help="Optional identity snapshot ID for DB linkage.",
)
@click.option(
    "--jsonl-output",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Write lifecycle events into JSONL file.",
)
@click.option(
    "--db-dsn",
    type=str,
    default=None,
    help="PostgreSQL DSN to write into existing eval schema.",
)
def run_command(
    benchmark_key: str,
    seed: int | None,
    git_sha: str | None,
    agent_config_id: str | None,
    identity_snapshot_id: int | None,
    jsonl_output: Path | None,
    db_dsn: str | None,
) -> None:
    """Run a single benchmark by key."""
    reporters: list[Reporter] = []
    if jsonl_output is not None:
        reporters.append(JsonlReporter(jsonl_output))
    if db_dsn is not None:
        reporters.append(DbReporter(db_dsn))

    print_banner("Atman Eval Runner", f"Running benchmark '{benchmark_key}'")
    runner = RunnerCore(reporters=reporters)
    outcome = runner.run(
        benchmark_key,
        seed=seed,
        git_sha=git_sha,
        agent_config_id=agent_config_id,
        identity_snapshot_id=identity_snapshot_id,
    )

    print_section("Run summary")
    print_info(f"status={outcome.status}")
    print_info(f"total_items={outcome.total_items}")
    print_info(f"passed_items={outcome.passed_items}")
    print_info(f"failed_items={outcome.failed_items}")
    print_info(f"run_id={outcome.context.run_id}")
    if outcome.reporter_errors:
        print_err("Reporter errors:")
        for err in outcome.reporter_errors:
            print_err(f"  {err}")
    else:
        print_ok("Reporters completed without errors.")
    if outcome.status == "failed":
        raise SystemExit(1)


def main() -> None:
    cli(prog_name="python -m atman.eval.benchmark_runner")


if __name__ == "__main__":
    main()
