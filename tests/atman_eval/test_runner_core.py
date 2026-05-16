from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from atman.eval.run_context import RunContext
    from atman.eval.runner_core import BenchmarkItemResult, BenchmarkRunOutcome


def test_runner_core_idempotent_reuse_for_same_git_sha_and_seed() -> None:
    from atman.eval import registry
    from atman.eval.benchmarks import noop
    from atman.eval.runner_core import RunnerCore

    registry.clear()
    importlib.reload(noop)
    runner = RunnerCore()
    first = runner.run("noop", git_sha="same-sha", seed=1)
    second = runner.run("noop", git_sha="same-sha", seed=1)

    assert first.status == "completed"
    assert second.status == "skipped"
    assert second.metadata.get("idempotent_reuse") is True


def test_runner_core_runs_distinct_seeds_for_same_git_sha() -> None:
    from atman.eval import registry
    from atman.eval.benchmarks import noop
    from atman.eval.runner_core import RunnerCore

    registry.clear()
    importlib.reload(noop)
    runner = RunnerCore()
    first = runner.run("noop", git_sha="same-sha", seed=1)
    second = runner.run("noop", git_sha="same-sha", seed=2)

    assert first.status == "completed"
    assert second.status == "completed"
    assert first.context.seed == 1
    assert second.context.seed == 2
    assert "idempotent_reuse" not in second.metadata


def test_runner_core_reports_on_complete_failures() -> None:
    from atman.eval import registry
    from atman.eval.benchmarks import noop
    from atman.eval.runner_core import RunnerCore

    class FailingCompleteReporter:
        def on_run_start(self, context: RunContext) -> None:
            _ = context

        def on_run_item(self, context: RunContext, item: BenchmarkItemResult) -> None:
            _ = context, item

        def on_run_complete(self, outcome: BenchmarkRunOutcome) -> None:
            _ = outcome
            raise RuntimeError("complete sink unavailable")

    registry.clear()
    importlib.reload(noop)
    outcome = RunnerCore(reporters=[FailingCompleteReporter()]).run("noop", seed=7)

    assert outcome.status == "completed"
    assert outcome.reporter_errors == ("RuntimeError: complete sink unavailable",)


def test_runner_core_does_not_cache_failed_runs_for_same_idempotency_key() -> None:
    from atman.eval import registry
    from atman.eval.benchmarks import noop
    from atman.eval.runner_core import BenchmarkResult, RunnerCore

    calls = {"count": 0}

    registry.clear()

    @registry.register("boom")
    def boom(context: RunContext) -> BenchmarkResult:
        _ = context
        calls["count"] += 1
        raise RuntimeError(f"boom {calls['count']}")

    try:
        runner = RunnerCore()
        first = runner.run("boom", git_sha="same-sha", seed=42)
        second = runner.run("boom", git_sha="same-sha", seed=42)
    finally:
        registry.clear()
        importlib.reload(noop)

    assert calls["count"] == 2
    assert first.status == "failed"
    assert second.status == "failed"
    assert first.items[0].error_message == "RuntimeError: boom 1"
    assert second.items[0].error_message == "RuntimeError: boom 2"
