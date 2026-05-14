"""JSONL reporter for local benchmark run artifacts."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from atman.eval.run_context import RunContext
from atman.eval.runner_core import BenchmarkItemResult, BenchmarkRunOutcome


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _json_ready(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_ready(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


class JsonlReporter:
    """Append benchmark lifecycle events to a JSONL file."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def on_run_start(self, context: RunContext) -> None:
        self._append(
            {
                "event": "run_start",
                "run_id": context.run_id,
                "benchmark_key": context.benchmark_key,
                "started_at": context.started_at,
                "metadata": context.to_db_metadata(),
            }
        )

    def on_run_item(self, context: RunContext, item: BenchmarkItemResult) -> None:
        self._append(
            {
                "event": "run_item",
                "run_id": context.run_id,
                "benchmark_key": context.benchmark_key,
                "item": asdict(item),
            }
        )

    def on_run_complete(self, outcome: BenchmarkRunOutcome) -> None:
        self._append(
            {
                "event": "run_complete",
                "run_id": outcome.context.run_id,
                "benchmark_key": outcome.context.benchmark_key,
                "status": outcome.status,
                "total_items": outcome.total_items,
                "passed_items": outcome.passed_items,
                "failed_items": outcome.failed_items,
                "completed_at": outcome.completed_at,
                "metadata": outcome.metadata,
                "reporter_errors": list(outcome.reporter_errors),
            }
        )

    def _append(self, payload: dict[str, Any]) -> None:
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_json_ready(payload), ensure_ascii=False))
            handle.write("\n")
