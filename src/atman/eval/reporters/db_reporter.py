"""Database reporter writing into existing eval schema tables."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from atman.eval.run_context import RunContext
from atman.eval.runner_core import BenchmarkItemResult, BenchmarkRunOutcome


class DbReporter:
    """Persist run summary/items into ``eval.benchmark_runs`` and ``eval.run_items``."""

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
        self._run_items: dict[str, list[BenchmarkItemResult]] = {}

    def on_run_start(self, context: RunContext) -> None:
        self._run_items[context.run_id] = []

    def on_run_item(self, context: RunContext, item: BenchmarkItemResult) -> None:
        self._run_items.setdefault(context.run_id, []).append(item)

    def on_run_complete(self, outcome: BenchmarkRunOutcome) -> None:
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - covered by dependency checks in runtime
            raise RuntimeError("psycopg is required for DbReporter") from exc

        metadata = outcome.context.to_db_metadata()
        metadata.update(outcome.metadata)
        metadata["reporter_errors"] = list(outcome.reporter_errors)

        with psycopg.connect(self._dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO eval.benchmark_runs (
                        benchmark_key,
                        agent_config_id,
                        identity_snapshot_id,
                        started_at,
                        completed_at,
                        status,
                        total_items,
                        passed_items,
                        failed_items,
                        metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                    RETURNING id;
                    """,
                    (
                        outcome.context.benchmark_key,
                        outcome.context.agent_config_id,
                        outcome.context.identity_snapshot_id,
                        outcome.started_at,
                        outcome.completed_at,
                        outcome.status,
                        outcome.total_items,
                        outcome.passed_items,
                        outcome.failed_items,
                        json.dumps(metadata),
                    ),
                )
                row = cur.fetchone()
                assert row is not None
                run_id = int(row[0])
                for item in self._run_items.get(outcome.context.run_id, []):
                    self._insert_item(cur, run_id=run_id, item=item)
            conn.commit()
        self._run_items.pop(outcome.context.run_id, None)

    @staticmethod
    def _insert_item(cur: Any, *, run_id: int, item: BenchmarkItemResult) -> None:
        cur.execute(
            """
            INSERT INTO eval.run_items (
                run_id,
                item_key,
                verdict,
                score,
                expected_value,
                actual_value,
                error_message,
                metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                run_id,
                item.item_key,
                item.verdict,
                item.score,
                item.expected_value,
                item.actual_value,
                item.error_message,
                json.dumps(asdict(item).get("metadata", {})),
            ),
        )
