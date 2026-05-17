"""Tests for HLE-27 / HLE-28 — PostWriteScheduler ↔ SessionManager wiring
and MaintenanceWorker dispatch for ``mrebel_extract`` / ``lingvo_enrich``."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from atman.adapters.maintenance.in_memory_queue import InMemoryMaintenanceQueue
from atman.adapters.memory.in_memory_entity_registry import InMemoryEntityRegistry
from atman.adapters.memory.in_memory_entity_relation_store import InMemoryEntityRelationStore
from atman.adapters.storage.in_memory_state_store import InMemoryStateStore
from atman.core.models.entity import Entity, EntityType
from atman.core.models.experience import EmotionalDepth, FeltSense, KeyMoment
from atman.core.models.identity import Identity
from atman.core.models.maintenance import JobName, JobStatus
from atman.core.models.narrative import LayerType, NarrativeDocument, NarrativeLayer
from atman.core.ports.entity_relations import EntityRelationExtractor, ExtractedRelation
from atman.core.ports.linguistic import (
    AgentMessageAnalysis,
    DetectedEntity,
    KeyMomentAnalysis,
    LinguisticAnalyzer,
    UserMessageAnalysis,
)
from atman.core.services.maintenance_worker import MaintenanceWorker
from atman.core.services.post_write_scheduler import PostWriteScheduler
from atman.core.services.session_manager import SessionManager


def _bootstrap(store: InMemoryStateStore) -> UUID:
    """Persist a minimal identity + narrative and return the agent id."""
    identity = Identity(self_description="t")
    store.save_identity(identity)
    store.save_narrative(
        NarrativeDocument(
            identity_id=identity.id,
            core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="c"),
            recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="r"),
        )
    )
    return identity.id


def _moment(text: str = "agent did the thing", why: str = "matters") -> KeyMoment:
    return KeyMoment(
        what_happened=text,
        how_i_felt=FeltSense(
            emotional_valence=0.1, emotional_intensity=0.5, depth=EmotionalDepth.MEANINGFUL
        ),
        why_it_matters=why,
    )


# ---------- HLE-27: SessionManager fires the scheduler on finish_session ----------
#
# Enrichment scheduling intentionally deferred until finish_session: jobs need
# the moments to be visible in state_store before the worker runs them, and
# state_store.create_key_moment only happens at finish time. Scheduling earlier
# would race the worker — see _schedule_post_write call sites for details.


def _finish(mgr: SessionManager, session_id: UUID) -> None:
    mgr.finish_session(
        session_id,
        overall_emotional_tone=0.0,
        key_insight="t",
        alignment_check=True,
        alignment_notes="",
    )


def test_session_manager_schedules_on_finish_after_persist(tmp_path) -> None:
    store = InMemoryStateStore()
    queue = InMemoryMaintenanceQueue()
    scheduler = PostWriteScheduler(queue)
    mgr = SessionManager(store, workspace=tmp_path, post_write_scheduler=scheduler)

    agent_id = _bootstrap(store)
    ctx = mgr.start_session(agent_id)
    moment = _moment()
    mgr.append_key_moment(ctx.session_id, moment)

    # No jobs yet — scheduling waits until the moment is durable in state_store.
    assert queue.list_jobs(agent_id=agent_id) == []

    _finish(mgr, ctx.session_id)

    jobs = queue.list_jobs(agent_id=agent_id)
    names = {j.job_name for j in jobs}
    assert JobName.mrebel_extract in names
    assert JobName.lingvo_enrich in names
    for j in jobs:
        assert j.payload["key_moment_id"] == str(moment.id)
    # And the moment is actually retrievable for the worker now.
    assert store.get_key_moment(moment.id) is not None


def test_session_manager_swallow_scheduler_errors(tmp_path) -> None:
    """A broken scheduler must not bring the finish path down."""

    class _Boom:
        def schedule_for_key_moment(self, *_a, **_kw):
            raise RuntimeError("queue offline")

    store = InMemoryStateStore()
    mgr = SessionManager(
        store,
        workspace=tmp_path,
        post_write_scheduler=_Boom(),  # type: ignore[arg-type]
    )
    agent_id = _bootstrap(store)
    ctx = mgr.start_session(agent_id)
    mgr.append_key_moment(ctx.session_id, _moment())
    # finish_session must complete despite the scheduler raising for every
    # moment — the exception is swallowed inside _schedule_post_write.
    _finish(mgr, ctx.session_id)
    assert mgr.get_active_session(ctx.session_id) is None


def test_session_manager_no_scheduler_is_noop(tmp_path) -> None:
    """SessionManager without a scheduler keeps the previous behaviour."""
    store = InMemoryStateStore()
    mgr = SessionManager(store, workspace=tmp_path)
    agent_id = _bootstrap(store)
    ctx = mgr.start_session(agent_id)
    mgr.append_key_moment(ctx.session_id, _moment())
    _finish(mgr, ctx.session_id)


# ---------- HLE-28: MaintenanceWorker dispatch handlers ----------


class _StubExtractor(EntityRelationExtractor):
    def __init__(self, triples: list[tuple[str, str, str]]) -> None:
        self._triples = triples

    def extract_relations(
        self, text: str, entities: list[DetectedEntity]
    ) -> list[ExtractedRelation]:
        return [
            ExtractedRelation(
                subject=DetectedEntity(text=s, entity_type=EntityType.person, confidence=0.9),
                object=DetectedEntity(text=o, entity_type=EntityType.person, confidence=0.9),
                relation_type=r,
                confidence=0.9,
                learned_by="mrebel",
            )
            for s, o, r in self._triples
        ]


class _StubAnalyzer(LinguisticAnalyzer):
    def analyze_user_message(self, text: str) -> UserMessageAnalysis:  # type: ignore[override]
        return UserMessageAnalysis(text=text)

    def analyze_agent_message(  # type: ignore[override]
        self, message: str, *, thinking: str | None = None
    ) -> AgentMessageAnalysis:
        return AgentMessageAnalysis()

    def analyze_key_moment(  # type: ignore[override]
        self, what_happened: str, why_it_matters: str
    ) -> KeyMomentAnalysis:
        return KeyMomentAnalysis(principle_invocations=["honesty"])


def _seed_entity(registry: InMemoryEntityRegistry, agent: UUID, name: str) -> Entity:
    entity, _method = registry.resolve_or_create(
        agent_id=agent,
        canonical_name=name,
        entity_type=EntityType.person,
    )
    return entity


def _enqueue_moment_job(
    queue: InMemoryMaintenanceQueue, job_name: JobName, agent: UUID, moment_id: UUID
) -> None:
    queue.enqueue(
        job_name,
        agent_id=agent,
        payload={"key_moment_id": str(moment_id)},
        run_key=f"{job_name.value}:moment:{moment_id}",
    )


def test_worker_mrebel_writes_relations() -> None:
    agent = uuid4()
    store = InMemoryStateStore()
    moment = _moment("Alice mentored Bob")
    store.store_key_moments(uuid4(), [moment])

    registry = InMemoryEntityRegistry()
    relation_store = InMemoryEntityRelationStore()
    _seed_entity(registry, agent, "Alice")
    _seed_entity(registry, agent, "Bob")

    queue = InMemoryMaintenanceQueue()
    worker = MaintenanceWorker(
        queue,
        state_store=store,
        entity_relation_extractor=_StubExtractor([("Alice", "Bob", "mentored")]),
        entity_relation_store=relation_store,
        entity_registry=registry,
    )
    _enqueue_moment_job(queue, JobName.mrebel_extract, agent, moment.id)

    processed = worker.run_once()
    assert processed == 1

    relations = relation_store.list_for_agent(agent)
    assert len(relations) == 1
    assert relations[0].learned_by == "mrebel"
    # The original job is now succeeded
    jobs = queue.list_jobs(status=JobStatus.succeeded, agent_id=agent)
    assert any(j.job_name == JobName.mrebel_extract for j in jobs)


def test_worker_mrebel_skips_when_unconfigured() -> None:
    queue = InMemoryMaintenanceQueue()
    agent = uuid4()
    _enqueue_moment_job(queue, JobName.mrebel_extract, agent, uuid4())

    worker = MaintenanceWorker(queue)  # no extractor / store / registry / state
    worker.run_once()

    skipped = queue.list_jobs(status=JobStatus.skipped, agent_id=agent)
    assert len(skipped) == 1


def test_worker_lingvo_updates_structured_markers() -> None:
    agent = uuid4()
    store = InMemoryStateStore()
    moment = _moment("agent acted on a principle", "why it matters")
    store.store_key_moments(uuid4(), [moment])

    queue = InMemoryMaintenanceQueue()
    worker = MaintenanceWorker(queue, state_store=store, linguistic_analyzer=_StubAnalyzer())
    _enqueue_moment_job(queue, JobName.lingvo_enrich, agent, moment.id)

    worker.run_once()

    refreshed = store.get_key_moment(moment.id)
    assert refreshed is not None
    assert refreshed.structured_markers
    assert refreshed.structured_markers_version == "1.0"


def test_worker_lingvo_idempotent_when_markers_present() -> None:
    agent = uuid4()
    store = InMemoryStateStore()
    pre_filled: dict[str, Any] = {"boundary_markers": ["principle:already"]}
    moment = KeyMoment(
        what_happened="prefilled",
        how_i_felt=FeltSense(
            emotional_valence=0.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
        ),
        why_it_matters="why",
        structured_markers=pre_filled,
        structured_markers_version="1.0",
    )
    store.store_key_moments(uuid4(), [moment])

    queue = InMemoryMaintenanceQueue()
    worker = MaintenanceWorker(queue, state_store=store, linguistic_analyzer=_StubAnalyzer())
    _enqueue_moment_job(queue, JobName.lingvo_enrich, agent, moment.id)

    worker.run_once()

    refreshed = store.get_key_moment(moment.id)
    assert refreshed is not None
    # markers untouched
    assert refreshed.structured_markers == pre_filled
    skipped = queue.list_jobs(status=JobStatus.skipped, agent_id=agent)
    assert len(skipped) == 1


def test_worker_skips_missing_moment() -> None:
    agent = uuid4()
    store = InMemoryStateStore()
    queue = InMemoryMaintenanceQueue()
    worker = MaintenanceWorker(
        queue,
        state_store=store,
        entity_relation_extractor=_StubExtractor([]),
        entity_relation_store=InMemoryEntityRelationStore(),
        entity_registry=InMemoryEntityRegistry(),
    )
    _enqueue_moment_job(queue, JobName.mrebel_extract, agent, uuid4())  # nonexistent

    worker.run_once()
    skipped = queue.list_jobs(status=JobStatus.skipped, agent_id=agent)
    assert len(skipped) == 1


def test_worker_requires_moment_payload() -> None:
    agent = uuid4()
    queue = InMemoryMaintenanceQueue()
    queue.enqueue(JobName.mrebel_extract, agent_id=agent, payload={}, run_key="bad")

    worker = MaintenanceWorker(
        queue,
        state_store=InMemoryStateStore(),
        entity_relation_extractor=_StubExtractor([]),
        entity_relation_store=InMemoryEntityRelationStore(),
        entity_registry=InMemoryEntityRegistry(),
    )
    worker.run_once()
    failed = queue.list_jobs(status=JobStatus.failed, agent_id=agent)
    assert len(failed) == 1
    assert "key_moment_id" in (failed[0].error or "")
