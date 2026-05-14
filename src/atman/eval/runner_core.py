"""Core benchmark runner lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Literal

from atman.eval.hardware import collect_hardware_metadata
from atman.eval.reporters.base import Reporter
from atman.eval.run_context import RunContext
from atman.eval.seed_manager import apply_global_seed, resolve_seed

from . import registry

Verdict = Literal["pass", "fail", "partial", "inconclusive"]
RunStatus = Literal["completed", "failed", "skipped"]


@dataclass(frozen=True, slots=True)
class BenchmarkItemResult:
    item_key: str
    verdict: Verdict
    score: float | None = None
    expected_value: str | None = None
    actual_value: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    items: list[BenchmarkItemResult]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BenchmarkRunOutcome:
    context: RunContext
    status: RunStatus
    total_items: int
    passed_items: int
    failed_items: int
    started_at: datetime
    completed_at: datetime
    items: list[BenchmarkItemResult]
    metadata: dict[str, Any] = field(default_factory=dict)
    reporter_errors: tuple[str, ...] = ()


class RunnerCore:
    """Runs a benchmark and sends lifecycle events to reporters."""

    def __init__(
        self,
        *,
        reporters: list[Reporter] | None = None,
        runner_version: str = "E1",
    ) -> None:
        self._reporters = reporters or []
        self._runner_version = runner_version
        self._completed_by_idempotency_key: dict[str, BenchmarkRunOutcome] = {}

    # PLAYBOOK-START
    # id: deterministic-idempotency-run-keys
    # category: design-patterns
    # title: Idempotent Runner via Deterministic Keys
    # status: draft
    #
    # Pattern: compute a deterministic idempotency key from benchmark identity
    # and source revision (`git_sha`). If a terminal successful run with the same
    # key already exists in this runner process, return it as skipped instead of
    # re-executing side effects.
    #
    # Why generalizable: batch jobs, benchmark pipelines, and CI retries often
    # rerun the same inputs. Deterministic keys reduce duplicate writes and make
    # retried orchestration safer without changing benchmark logic.
    # PLAYBOOK-END
    def run(
        self,
        benchmark_key: str,
        *,
        seed: int | None = None,
        git_sha: str | None = None,
        agent_config_id: str | None = None,
        identity_snapshot_id: int | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> BenchmarkRunOutcome:
        idempotency_key = self._idempotency_key(
            benchmark_key=benchmark_key,
            git_sha=git_sha,
            agent_config_id=agent_config_id,
            identity_snapshot_id=identity_snapshot_id,
        )
        if idempotency_key is not None and idempotency_key in self._completed_by_idempotency_key:
            cached = self._completed_by_idempotency_key[idempotency_key]
            metadata = dict(cached.metadata)
            metadata["idempotent_reuse"] = True
            return replace(cached, status="skipped", metadata=metadata)

        effective_seed = resolve_seed(seed)
        apply_global_seed(effective_seed)
        context = RunContext.create(
            benchmark_key=benchmark_key,
            seed=effective_seed,
            agent_config_id=agent_config_id,
            identity_snapshot_id=identity_snapshot_id,
            git_sha=git_sha,
            runner_version=self._runner_version,
            hardware=collect_hardware_metadata(),
            extra_metadata=extra_metadata,
        )
        started_at = datetime.now(UTC)
        reporter_errors: list[str] = []
        self._fanout(
            lambda reporter: reporter.on_run_start(context),
            reporter_errors,
        )

        try:
            benchmark = registry.get(benchmark_key)
            result = benchmark(context)
            for item in result.items:
                self._fanout(
                    lambda reporter, current_item=item: reporter.on_run_item(context, current_item),
                    reporter_errors,
                )
            status: RunStatus = "completed"
            items = result.items
            metadata = dict(result.metadata)
        except Exception as exc:
            status = "failed"
            items = [
                BenchmarkItemResult(
                    item_key="runner_exception",
                    verdict="fail",
                    error_message=f"{type(exc).__name__}: {exc}",
                )
            ]
            metadata = {"runner_exception": f"{type(exc).__name__}: {exc}"}

        passed_items = sum(1 for item in items if item.verdict == "pass")
        failed_items = sum(1 for item in items if item.verdict == "fail")
        outcome = BenchmarkRunOutcome(
            context=context,
            status=status,
            total_items=len(items),
            passed_items=passed_items,
            failed_items=failed_items,
            started_at=started_at,
            completed_at=datetime.now(UTC),
            items=items,
            metadata=metadata,
            reporter_errors=tuple(reporter_errors),
        )

        self._fanout(lambda reporter: reporter.on_run_complete(outcome), reporter_errors)
        if idempotency_key is not None and outcome.status == "completed":
            self._completed_by_idempotency_key[idempotency_key] = outcome
        return outcome

    def _fanout(
        self,
        callback: Any,
        errors: list[str],
    ) -> None:
        for reporter in self._reporters:
            try:
                callback(reporter)
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _idempotency_key(
        *,
        benchmark_key: str,
        git_sha: str | None,
        agent_config_id: str | None,
        identity_snapshot_id: int | None,
    ) -> str | None:
        if not git_sha:
            return None
        return f"{benchmark_key}:{git_sha}:{agent_config_id or ''}:{identity_snapshot_id or ''}"
