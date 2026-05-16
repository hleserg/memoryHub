"""PostWriteScheduler — fire-and-forget enqueue of enrichment jobs after a write.

After a KeyMoment is persisted, the agent's main control loop should not block
on heavy enrichment (mREBEL relation extraction, deeper linguistic analysis,
embedding computation for offline reranker). This service enqueues those
tasks onto the :class:`MaintenanceQueue` so they run asynchronously, either
via `asyncio.create_task` for in-process execution or via the
`atman-maintenance` worker for out-of-process execution.

Idempotency: a deterministic ``run_key`` is derived from
``(job_name, key_moment_id)`` so multiple post-write hooks for the same
moment don't create duplicate jobs.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID

from atman.core.models.experience import KeyMoment
from atman.core.models.maintenance import JobName
from atman.core.ports.maintenance_queue import MaintenanceQueue

_LOG = logging.getLogger(__name__)


def _moment_run_key(job_name: JobName, moment_id: UUID) -> str:
    """Deterministic idempotency key for moment-scoped enrichment jobs."""
    return f"{job_name.value}:moment:{moment_id}"


class PostWriteScheduler:
    """Enqueue enrichment jobs onto a MaintenanceQueue after a write event."""

    def __init__(
        self,
        queue: MaintenanceQueue,
        *,
        jobs: tuple[JobName, ...] = (
            JobName.mrebel_extract,
            JobName.lingvo_enrich,
        ),
    ) -> None:
        self._queue = queue
        self._jobs = jobs

    def schedule_for_key_moment(
        self,
        moment: KeyMoment,
        agent_id: UUID,
        *,
        scheduled_at: datetime | None = None,
    ) -> None:
        """Synchronously enqueue all configured jobs for ``moment``.

        Safe to call from request-handler hot path — enqueuing is cheap
        (one INSERT per job in the Postgres impl, dict mutation in the
        in-memory impl). Use :meth:`schedule_for_key_moment_async` when
        you specifically want to detach from the current event loop turn.
        """
        when = scheduled_at or datetime.now(UTC)
        for job_name in self._jobs:
            try:
                self._queue.enqueue(
                    job_name,
                    agent_id=agent_id,
                    payload={"key_moment_id": str(moment.id)},
                    run_key=_moment_run_key(job_name, moment.id),
                    scheduled_at=when,
                )
            except Exception:
                _LOG.exception(
                    "Failed to enqueue %s for moment %s — continuing", job_name.value, moment.id
                )

    async def schedule_for_key_moment_async(
        self,
        moment: KeyMoment,
        agent_id: UUID,
        *,
        scheduled_at: datetime | None = None,
    ) -> None:
        """Fire-and-forget variant — schedules via ``asyncio.create_task``.

        Returns immediately. If no running event loop is available, falls
        back to synchronous enqueue so callers can use this method
        unconditionally.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No event loop — degrade to sync.
            self.schedule_for_key_moment(moment, agent_id, scheduled_at=scheduled_at)
            return

        async def _run() -> None:
            self.schedule_for_key_moment(moment, agent_id, scheduled_at=scheduled_at)

        # Keep a strong reference until the task completes — bare create_task
        # would let the task be garbage-collected mid-flight per asyncio docs.
        task = loop.create_task(_run())
        task.add_done_callback(_log_task_exception)


def _log_task_exception(task: asyncio.Task[None]) -> None:
    """Surface unhandled exceptions from fire-and-forget tasks via logger."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        _LOG.exception(
            "post-write enrichment task failed: %s",
            exc,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
