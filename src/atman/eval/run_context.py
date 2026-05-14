"""Typed run context for eval benchmark executions."""

from __future__ import annotations

import platform
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class RunContext:
    """Execution context passed to benchmark callables."""

    benchmark_key: str
    run_id: str
    started_at: datetime
    seed: int
    agent_config_id: str | None = None
    identity_snapshot_id: int | None = None
    git_sha: str | None = None
    runner_version: str = "E1"
    hardware: dict[str, Any] = field(default_factory=dict)
    extra_metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        benchmark_key: str,
        seed: int,
        agent_config_id: str | None = None,
        identity_snapshot_id: int | None = None,
        git_sha: str | None = None,
        runner_version: str = "E1",
        hardware: dict[str, Any] | None = None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> RunContext:
        return cls(
            benchmark_key=benchmark_key,
            run_id=uuid.uuid4().hex,
            started_at=_utc_now(),
            seed=seed,
            agent_config_id=agent_config_id,
            identity_snapshot_id=identity_snapshot_id,
            git_sha=git_sha,
            runner_version=runner_version,
            hardware=hardware or {},
            extra_metadata=extra_metadata or {},
        )

    def to_db_metadata(self) -> dict[str, Any]:
        """Serialize context metadata for ``eval.*.metadata`` JSONB columns."""
        return {
            "app_run_id": self.run_id,
            "runner_version": self.runner_version,
            "git_sha": self.git_sha,
            "seed": self.seed,
            "hostname": platform.node(),
            "python_version": platform.python_version(),
            "hardware": self.hardware,
            "extra": self.extra_metadata,
        }
