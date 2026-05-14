from __future__ import annotations

import json
from pathlib import Path


def test_jsonl_reporter_writes_lifecycle_events(tmp_path: Path) -> None:
    from atman.eval.reporters.jsonl_reporter import JsonlReporter
    from atman.eval.run_context import RunContext
    from atman.eval.runner_core import BenchmarkItemResult, BenchmarkRunOutcome

    output = tmp_path / "events.jsonl"
    reporter = JsonlReporter(output)
    context = RunContext.create(benchmark_key="noop", seed=1, git_sha="sha")
    item = BenchmarkItemResult(item_key="it-1", verdict="pass", score=1.0)
    outcome = BenchmarkRunOutcome(
        context=context,
        status="completed",
        total_items=1,
        passed_items=1,
        failed_items=0,
        started_at=context.started_at,
        completed_at=context.started_at,
        items=[item],
        metadata={"source": "test"},
    )

    reporter.on_run_start(context)
    reporter.on_run_item(context, item)
    reporter.on_run_complete(outcome)

    lines = output.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    events = [json.loads(line)["event"] for line in lines]
    assert events == ["run_start", "run_item", "run_complete"]
