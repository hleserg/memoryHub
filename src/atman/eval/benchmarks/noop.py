"""Minimal benchmark for smoke-testing the E1 runner framework."""

from __future__ import annotations

from atman.eval.registry import register
from atman.eval.run_context import RunContext
from atman.eval.runner_core import BenchmarkItemResult, BenchmarkResult


@register("noop")
def run_noop(context: RunContext) -> BenchmarkResult:
    item = BenchmarkItemResult(
        item_key="noop:smoke",
        verdict="pass",
        score=1.0,
        expected_value="runner executes one synthetic item",
        actual_value="ok",
        metadata={"run_id": context.run_id},
    )
    return BenchmarkResult(items=[item], metadata={"benchmark": "noop"})
