"""In-memory MaintenanceQueue adapter for tests."""

import threading
from datetime import UTC, datetime
from uuid import UUID

from atman.core.models.maintenance import JobName, JobStatus, MaintenanceJob
from atman.core.ports.maintenance_queue import MaintenanceQueue


class InMemoryMaintenanceQueue(MaintenanceQueue):
    """Thread-safe in-memory MaintenanceQueue for tests and lightweight use."""

    def __init__(self) -> None:
        self._jobs: list[MaintenanceJob] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Enqueue
    # ------------------------------------------------------------------

    def enqueue(
        self,
        job_name: JobName,
        *,
        agent_id: UUID | None = None,
        payload: dict | None = None,
        run_key: str | None = None,
        scheduled_at: datetime | None = None,
    ) -> MaintenanceJob:
        """
        Enqueue job. If run_key matches an existing pending/running job,
        return that existing job (idempotent).
        """
        with self._lock:
            if run_key is not None:
                for job in self._jobs:
                    if job.run_key == run_key and job.status in (
                        JobStatus.pending,
                        JobStatus.running,
                    ):
                        return job

            new_job = MaintenanceJob(
                job_name=job_name,
                agent_id=agent_id,
                payload=payload or {},
                run_key=run_key,
                scheduled_at=scheduled_at or datetime.now(UTC),
            )
            self._jobs.append(new_job)
        return new_job

    # ------------------------------------------------------------------
    # Claiming
    # ------------------------------------------------------------------

    def claim_batch(
        self,
        job_name: JobName | None = None,
        *,
        batch_size: int = 10,
    ) -> list[MaintenanceJob]:
        """
        Atomically claim up to batch_size pending jobs (SKIP LOCKED semantics).
        Returns claimed jobs with status=running.
        """
        claimed: list[MaintenanceJob] = []
        now = datetime.now(UTC)

        with self._lock:
            for job in self._jobs:
                if len(claimed) >= batch_size:
                    break
                if job.status != JobStatus.pending:
                    continue
                if job_name is not None and job.job_name != job_name:
                    continue
                job.status = JobStatus.running
                job.started_at = now
                claimed.append(job)

        return claimed

    # ------------------------------------------------------------------
    # Completion transitions
    # ------------------------------------------------------------------

    def mark_done(self, job_id: UUID, *, result: dict | None = None) -> None:
        """Mark job as succeeded."""
        with self._lock:
            job = self._find(job_id)
            if job is not None:
                job.status = JobStatus.succeeded
                job.finished_at = datetime.now(UTC)
                job.result = result

    def mark_failed(self, job_id: UUID, *, error: str) -> None:
        """Mark job as failed."""
        with self._lock:
            job = self._find(job_id)
            if job is not None:
                job.status = JobStatus.failed
                job.finished_at = datetime.now(UTC)
                job.error = error

    def mark_skipped(self, job_id: UUID, *, reason: str = "") -> None:
        """Mark job as skipped (duplicate or not applicable)."""
        with self._lock:
            job = self._find(job_id)
            if job is not None:
                job.status = JobStatus.skipped
                job.finished_at = datetime.now(UTC)
                job.error = reason

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------

    def list_jobs(
        self,
        status: JobStatus | None = None,
        agent_id: UUID | None = None,
        *,
        limit: int = 100,
    ) -> list[MaintenanceJob]:
        """List jobs filtered by status and/or agent, newest scheduled_at first."""
        with self._lock:
            matches = [
                j
                for j in self._jobs
                if (status is None or j.status == status)
                and (agent_id is None or j.agent_id == agent_id)
            ]
        matches.sort(key=lambda j: j.scheduled_at, reverse=True)
        return matches[:limit]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find(self, job_id: UUID) -> MaintenanceJob | None:
        """Return job by id, or None. Must be called under self._lock."""
        for job in self._jobs:
            if job.id == job_id:
                return job
        return None
