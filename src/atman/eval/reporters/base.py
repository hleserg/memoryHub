"""Reporter interfaces for benchmark runner lifecycle hooks."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from atman.eval.run_context import RunContext

if TYPE_CHECKING:
    from atman.eval.runner_core import BenchmarkItemResult, BenchmarkRunOutcome


class Reporter(Protocol):
    """Reporting sink interface."""

    def on_run_start(self, context: RunContext) -> None: ...

    def on_run_item(self, context: RunContext, item: BenchmarkItemResult) -> None: ...

    def on_run_complete(self, outcome: BenchmarkRunOutcome) -> None: ...
