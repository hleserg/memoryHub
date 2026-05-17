"""MaintenanceWorker — dispatch and execute maintenance jobs from the queue."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from enum import Enum
from uuid import UUID

from atman.core.models.entity import EntityRelation
from atman.core.models.maintenance import JobName, MaintenanceJob
from atman.core.ports.entity_registry import EntityRegistry
from atman.core.ports.entity_relation_store import EntityRelationStore
from atman.core.ports.entity_relations import EntityRelationExtractor
from atman.core.ports.linguistic import DetectedEntity, LinguisticAnalyzer
from atman.core.ports.maintenance_queue import MaintenanceQueue
from atman.core.ports.memory_guardian import MemoryGuardian
from atman.core.ports.salience_decay import SalienceDecayService
from atman.core.ports.state_store import StateStore

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
        *,
        state_store: StateStore | None = None,
        entity_relation_extractor: EntityRelationExtractor | None = None,
        entity_relation_store: EntityRelationStore | None = None,
        entity_registry: EntityRegistry | None = None,
        linguistic_analyzer: LinguisticAnalyzer | None = None,
    ) -> None:
        self._queue = queue
        self._decay = salience_decay
        self._guardian = memory_guardian
        # Enrichment dependencies (HLE-28). All optional — a worker without
        # them will mark mrebel_extract / lingvo_enrich jobs as skipped with
        # an explanatory reason rather than crashing, which is the right
        # behaviour for in-memory dev runs that lack ML models.
        self._state_store = state_store
        self._relation_extractor = entity_relation_extractor
        self._relation_store = entity_relation_store
        self._entity_registry = entity_registry
        self._analyzer = linguistic_analyzer

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
        if job.job_name == JobName.mrebel_extract:
            return self._run_mrebel(job)
        if job.job_name == JobName.lingvo_enrich:
            return self._run_lingvo(job)
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

    def _run_mrebel(self, job: MaintenanceJob) -> tuple[_DispatchOutcome, dict | None]:
        """Async relation-extraction for a single KeyMoment (HLE-28).

        Reads the moment from state_store, runs the configured extractor
        on its narrative, and persists each ExtractedRelation in
        ``agent_N.entity_relations`` with ``learned_by='mrebel'``.
        Skipped (not failed) when the worker has no extractor / store /
        registry — that is a valid lean-deploy configuration, not an error.
        """
        if (
            self._relation_extractor is None
            or self._relation_store is None
            or self._state_store is None
            or self._entity_registry is None
        ):
            self._queue.mark_skipped(job.id, reason="relation enrichment not configured")
            return _DispatchOutcome.SKIPPED, None
        agent_id, moment_id = _require_moment_payload(job)
        moment = self._state_store.get_key_moment(moment_id)
        if moment is None:
            self._queue.mark_skipped(job.id, reason=f"key moment {moment_id} not found")
            return _DispatchOutcome.SKIPPED, None
        text = _moment_narrative(moment)
        if not text.strip():
            self._queue.mark_skipped(job.id, reason="empty moment narrative")
            return _DispatchOutcome.SKIPPED, None
        relations = self._relation_extractor.extract_relations(text, entities=[])
        written = 0
        for rel in relations:
            subj = self._resolve_entity(agent_id, rel.subject)
            obj = self._resolve_entity(agent_id, rel.object)
            if subj is None or obj is None or subj == obj:
                continue
            self._relation_store.add_relation(
                EntityRelation(
                    agent_id=agent_id,
                    from_entity_id=subj,
                    to_entity_id=obj,
                    relation_type=rel.relation_type,
                    confidence=rel.confidence,
                    learned_by="mrebel",
                )
            )
            written += 1
        return _DispatchOutcome.DONE, {"relations_written": written}

    def _run_lingvo(self, job: MaintenanceJob) -> tuple[_DispatchOutcome, dict | None]:
        """Async deeper linguistic analysis for a single KeyMoment (HLE-28).

        Calls ``LinguisticAnalyzer.analyze_key_moment`` on the moment's
        narrative fields and stores the structured markers via
        ``state_store.update_moment_structured_markers``. Idempotent —
        skipped when ``structured_markers`` already populated.
        """
        if self._analyzer is None or self._state_store is None:
            self._queue.mark_skipped(job.id, reason="linguistic enrichment not configured")
            return _DispatchOutcome.SKIPPED, None
        _agent_id, moment_id = _require_moment_payload(job)
        moment = self._state_store.get_key_moment(moment_id)
        if moment is None:
            self._queue.mark_skipped(job.id, reason=f"key moment {moment_id} not found")
            return _DispatchOutcome.SKIPPED, None
        if _moment_has_markers(moment):
            self._queue.mark_skipped(job.id, reason="structured_markers already populated")
            return _DispatchOutcome.SKIPPED, None
        analysis = self._analyzer.analyze_key_moment(
            moment.what_happened or "", moment.why_it_matters or ""
        )
        markers = analysis.model_dump(mode="json") if hasattr(analysis, "model_dump") else {}
        self._state_store.update_moment_structured_markers(
            moment_id,
            markers,
            "1.0",
        )
        return _DispatchOutcome.DONE, {"moment_id": str(moment_id)}

    def _resolve_entity(self, agent_id: UUID, entity: DetectedEntity) -> UUID | None:
        """Look up entity by surface form; skip when nothing matches.

        We deliberately avoid creating new entities here — entity registration
        is the responsibility of the user-message ingestion path, not the
        async enrichment worker.
        """
        if self._entity_registry is None:
            return None
        try:
            matches = self._entity_registry.find_by_name(agent_id, entity.text)
        except Exception:
            _LOG.warning("entity lookup failed for %r", entity.text, exc_info=True)
            return None
        return matches[0].id if matches else None


def _require_moment_payload(job: MaintenanceJob) -> tuple[UUID, UUID]:
    """Extract (agent_id, moment_id) from a moment-scoped enrichment job."""
    if job.agent_id is None:
        raise ValueError(f"{job.job_name.value} job {job.id} requires agent_id")
    raw = job.payload.get("key_moment_id")
    if not raw:
        raise ValueError(f"{job.job_name.value} job {job.id} missing key_moment_id payload")
    return job.agent_id, UUID(str(raw))


def _moment_narrative(moment: object) -> str:
    """Join the narrative-bearing fields of a KeyMoment for extraction."""
    what = getattr(moment, "what_happened", "") or ""
    why = getattr(moment, "why_it_matters", "") or ""
    if what and why:
        return f"{what}\n\n{why}"
    return what or why


def _moment_has_markers(moment: object) -> bool:
    """True when the moment already carries non-empty ``structured_markers``."""
    markers = getattr(moment, "structured_markers", None)
    return bool(markers)
