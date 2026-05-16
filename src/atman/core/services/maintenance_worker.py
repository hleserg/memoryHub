"""MaintenanceWorker — dispatch and execute maintenance jobs from the queue."""

import logging
from datetime import UTC, datetime
from enum import Enum

from atman.core.models.maintenance import JobName, MaintenanceJob
from atman.core.ports.maintenance_queue import MaintenanceQueue
from atman.core.ports.memory_guardian import MemoryGuardian
from atman.core.ports.salience_decay import SalienceDecayService

_LOG = logging.getLogger(__name__)


class _DispatchOutcome(Enum):
    """Result of `_handle` — distinguishes done vs already-skipped vs no-op."""

    DONE = "done"
    SKIPPED = "skipped"


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
            outcome, result = self._handle(job)
            # _handle returns SKIPPED when it has already called mark_skipped
            # (e.g. unknown job type). Only call mark_done for DONE outcomes.
            # This avoids relying on object-identity mutations of `job.status`,
            # which would break under DB-backed queues that don't share state.
            if outcome is _DispatchOutcome.DONE:
                self._queue.mark_done(job.id, result=result)
        except Exception as exc:
            _LOG.exception("maintenance job %s failed", job.id)
            self._queue.mark_failed(job.id, error=str(exc))

    def _handle(self, job: MaintenanceJob) -> tuple[_DispatchOutcome, dict | None]:
        if job.job_name == JobName.salience_decay:
            return _DispatchOutcome.DONE, self._run_decay(job)
        if job.job_name == JobName.memory_guardian_scan:
            return _DispatchOutcome.DONE, self._run_guardian(job)
        _LOG.warning("unknown job %s, skipping", job.job_name)
        self._queue.mark_skipped(job.id, reason="unknown job type")
        return _DispatchOutcome.SKIPPED, None

    def _run_decay(self, job: MaintenanceJob) -> dict:
        if self._decay is None:
            raise RuntimeError("SalienceDecayService not configured")
        # agent_id is a top-level field on MaintenanceJob — not in payload.
        if job.agent_id is None:
            raise ValueError(f"salience_decay job {job.id} requires agent_id")
        agent_id = job.agent_id
        cutoff_str = job.payload.get("cutoff")
        cutoff = datetime.fromisoformat(cutoff_str) if cutoff_str else datetime.now(UTC)
        count = self._decay.decay_pass(agent_id, cutoff=cutoff)
        return {"updated": count}

    def _run_guardian(self, job: MaintenanceJob) -> dict:
        if self._guardian is None:
            raise RuntimeError("MemoryGuardian not configured")
        if job.agent_id is None:
            raise ValueError(f"memory_guardian_scan job {job.id} requires agent_id")
        agent_id = job.agent_id
        findings = (
            self._guardian.scan_orphan_entities(agent_id)
            + self._guardian.scan_merge_candidates(agent_id)
            + self._guardian.scan_embedding_gaps(agent_id)
            + self._guardian.scan_stale_moments(agent_id)
        )
        for f in findings:
            self._guardian.write_finding(f)
        return {"findings": len(findings)}
