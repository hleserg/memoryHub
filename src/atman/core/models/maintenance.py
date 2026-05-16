"""Domain models for maintenance job queue."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class JobStatus(StrEnum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    skipped = "skipped"


class JobName(StrEnum):
    salience_decay = "salience_decay"
    memory_guardian_scan = "memory_guardian_scan"
    mrebel_extract = "mrebel_extract"
    lingvo_enrich = "lingvo_enrich"
    entity_merge = "entity_merge"
    other = "other"


class MaintenanceJob(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    id: UUID = Field(default_factory=uuid4)
    job_name: JobName
    agent_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    run_key: str | None = None
    status: JobStatus = JobStatus.pending
    scheduled_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    result: dict[str, Any] | None = None

    @property
    def is_terminal(self) -> bool:
        """True if status is in a terminal state (no further transitions possible)."""
        return self.status in (JobStatus.succeeded, JobStatus.failed, JobStatus.skipped)

    @property
    def duration_seconds(self) -> float | None:
        """Wall-clock seconds between started_at and finished_at, or None if not available."""
        if self.started_at is not None and self.finished_at is not None:
            return (self.finished_at - self.started_at).total_seconds()
        return None
