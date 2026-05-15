"""MaintenanceWorker — dispatch and execute maintenance jobs from the queue."""

import logging
from datetime import UTC, datetime
from uuid import UUID

from atman.core.models.maintenance import JobName, MaintenanceJob
from atman.core.ports.maintenance_queue import MaintenanceQueue
from atman.core.ports.memory_guardian import MemoryGuardian
from atman.core.ports.salience_decay import SalienceDecayService

_LOG = logging.getLogger(__name__)


class MaintenanceWorker:
    """Dispatch and execute maintenance jobs claimed from the queue."""

    def __init__(
        self,
        queue: MaintenanceQueue,
        salience_decay: SalienceDecayService | None = None,
        memory_guardian: MemoryGuardian | None = None,
    ) -> None:
        self._queue = queue
        self._decay = salience_decay
        self._guardian = memory_guardian

    def run_once(self, batch_size: int = 20) -> int:
        """Claim and execute one batch of pending jobs. Returns number processed."""
        jobs = self._queue.claim_batch(batch_size=batch_size)
        for job in jobs:
            self._dispatch(job)
        return len(jobs)

    def _dispatch(self, job: MaintenanceJob) -> None:
        try:
            result = self._handle(job)
            # _handle may call mark_skipped internally and return None;
            # only call mark_done if the job wasn't already terminated.
            if not job.is_terminal:
                self._queue.mark_done(job.id, result=result)
        except Exception as exc:
            _LOG.exception("maintenance job %s failed", job.id)
            self._queue.mark_failed(job.id, error=str(exc))

    def _handle(self, job: MaintenanceJob) -> dict | None:
        if job.job_name == JobName.salience_decay:
            return self._run_decay(job)
        if job.job_name == JobName.memory_guardian_scan:
            return self._run_guardian(job)
        _LOG.warning("unknown job %s, skipping", job.job_name)
        self._queue.mark_skipped(job.id, reason="unknown job type")
        return None

    def _run_decay(self, job: MaintenanceJob) -> dict:
        if self._decay is None:
            raise RuntimeError("SalienceDecayService not configured")
        agent_id = UUID(job.payload["agent_id"])
        cutoff_str = job.payload.get("cutoff")
        cutoff = datetime.fromisoformat(cutoff_str) if cutoff_str else datetime.now(UTC)
        count = self._decay.decay_pass(agent_id, cutoff=cutoff)
        return {"updated": count}

    def _run_guardian(self, job: MaintenanceJob) -> dict:
        if self._guardian is None:
            raise RuntimeError("MemoryGuardian not configured")
        agent_id = UUID(job.payload["agent_id"])
        findings = (
            self._guardian.scan_orphan_entities(agent_id)
            + self._guardian.scan_merge_candidates(agent_id)
            + self._guardian.scan_embedding_gaps(agent_id)
        )
        for f in findings:
            self._guardian.write_finding(f)
        return {"findings": len(findings)}
