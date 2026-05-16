"""Unit tests for new v3 adapters (entity registry, stance, reranker, queue, compat)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from atman.adapters.linguistic.noop_adapter import NoOpLinguisticAnalyzer
from atman.adapters.maintenance.in_memory_queue import InMemoryMaintenanceQueue
from atman.adapters.memory.in_memory_entity_registry import InMemoryEntityRegistry
from atman.adapters.memory.in_memory_entity_stance import InMemoryEntityStanceStore
from atman.adapters.memory.noop_reranker import NoOpReranker
from atman.adapters.reflection_compat.experience_view_repository import (
    ExperienceViewRepository,
)
from atman.adapters.storage.in_memory_state_store import InMemoryStateStore
from atman.core.models.entity import EntityType, ResolutionMethod
from atman.core.models.experience import EmotionalDepth, FeltSense, KeyMoment, ReframingNote
from atman.core.models.maintenance import JobName, JobStatus
from atman.core.models.session import Session
from atman.core.ports.memory_reranker import SurfacedMemory

# ---------------------------------------------------------------------------
# InMemoryEntityRegistry
# ---------------------------------------------------------------------------


class TestInMemoryEntityRegistry:
    def test_l3_create_new_entity(self) -> None:
        reg = InMemoryEntityRegistry()
        agent = uuid4()
        ent, method = reg.resolve_or_create(agent, "Alice", EntityType.person)
        assert method is ResolutionMethod.L3_new
        assert ent.canonical_name == "Alice"
        assert reg.count() == 1

    def test_l1_exact_canonical_returns_existing(self) -> None:
        reg = InMemoryEntityRegistry()
        agent = uuid4()
        first, _ = reg.resolve_or_create(agent, "Alice", EntityType.person)
        second, method = reg.resolve_or_create(agent, "alice", EntityType.person)
        assert method is ResolutionMethod.L1_exact
        assert second.id == first.id

    def test_l1_exact_via_alias_resolves(self) -> None:
        reg = InMemoryEntityRegistry()
        agent = uuid4()
        ent, _ = reg.resolve_or_create(agent, "Alice", EntityType.person, alias_text="Al")
        again, method = reg.resolve_or_create(agent, "Bob", EntityType.person, alias_text="Al")
        assert method is ResolutionMethod.L1_exact
        assert again.id == ent.id

    def test_l2_embedding_match_above_threshold(self) -> None:
        reg = InMemoryEntityRegistry()
        agent = uuid4()
        a, _ = reg.resolve_or_create(agent, "ProjectX", EntityType.topic, embedding=[1.0, 0.0, 0.0])
        # Slightly different embedding but cosine ~1.0
        b, method = reg.resolve_or_create(
            agent,
            "Project-X",
            EntityType.topic,
            embedding=[0.99, 0.01, 0.01],
        )
        assert method is ResolutionMethod.L2_embedding
        assert b.id == a.id

    def test_l2_embedding_below_threshold_creates_new(self) -> None:
        reg = InMemoryEntityRegistry()
        agent = uuid4()
        reg.resolve_or_create(agent, "Alpha", EntityType.topic, embedding=[1.0, 0.0])
        _b, method = reg.resolve_or_create(
            agent,
            "Beta",
            EntityType.topic,
            embedding=[0.0, 1.0],
        )
        assert method is ResolutionMethod.L3_new
        assert reg.count() == 2

    def test_get_entity(self) -> None:
        reg = InMemoryEntityRegistry()
        agent = uuid4()
        ent, _ = reg.resolve_or_create(agent, "X", EntityType.topic)
        assert reg.get_entity(ent.id) is ent
        assert reg.get_entity(uuid4()) is None

    def test_find_by_name_returns_match_via_canonical_and_alias(self) -> None:
        reg = InMemoryEntityRegistry()
        agent = uuid4()
        ent, _ = reg.resolve_or_create(agent, "Alice", EntityType.person, alias_text="Al")
        results = reg.find_by_name(agent, "Alice")
        assert [e.id for e in results] == [ent.id]
        results_alias = reg.find_by_name(agent, "Al")
        assert [e.id for e in results_alias] == [ent.id]
        results_filtered = reg.find_by_name(agent, "Alice", entity_type=EntityType.organization)
        assert results_filtered == []

    def test_add_alias_appends_and_dedupes(self) -> None:
        reg = InMemoryEntityRegistry()
        agent = uuid4()
        ent, _ = reg.resolve_or_create(agent, "Alice", EntityType.person)
        a1 = reg.add_alias(ent.id, "Liz")
        a2 = reg.add_alias(ent.id, "liz")  # case dedup
        assert a1.alias_text == "liz"
        assert a2.alias_text == "liz"
        assert a1.id == a2.id

    def test_add_alias_unknown_entity_raises(self) -> None:
        reg = InMemoryEntityRegistry()
        with pytest.raises(KeyError):
            reg.add_alias(uuid4(), "x")

    def test_merge_entities_moves_aliases(self) -> None:
        reg = InMemoryEntityRegistry()
        agent = uuid4()
        src, _ = reg.resolve_or_create(agent, "AliceA", EntityType.person, alias_text="A1")
        tgt, _ = reg.resolve_or_create(agent, "AliceB", EntityType.person)
        reg.merge_entities(src.id, tgt.id, reason="duplicate")
        # Aliases of source should now also be queryable on target
        results = reg.find_by_name(agent, "A1")
        assert tgt.id in [e.id for e in results]
        loaded_src = reg.get_entity(src.id)
        assert loaded_src is not None
        assert loaded_src.needs_disambiguation is True

    def test_merge_entities_unknown_raises(self) -> None:
        reg = InMemoryEntityRegistry()
        agent = uuid4()
        ent, _ = reg.resolve_or_create(agent, "x", EntityType.topic)
        with pytest.raises(KeyError):
            reg.merge_entities(uuid4(), ent.id, reason="r")
        with pytest.raises(KeyError):
            reg.merge_entities(ent.id, uuid4(), reason="r")

    def test_update_last_seen_increments_mention(self) -> None:
        reg = InMemoryEntityRegistry()
        agent = uuid4()
        ent, _ = reg.resolve_or_create(agent, "x", EntityType.topic)
        before = ent.mention_count
        reg.update_last_seen(ent.id)
        loaded = reg.get_entity(ent.id)
        assert loaded is not None
        assert loaded.mention_count == before + 1
        # Unknown is no-op
        reg.update_last_seen(uuid4())

    def test_list_entities_orders_by_last_seen_desc(self) -> None:
        reg = InMemoryEntityRegistry()
        agent = uuid4()
        _a, _ = reg.resolve_or_create(agent, "A", EntityType.topic)
        b, _ = reg.resolve_or_create(agent, "B", EntityType.topic)
        # Mutate b's last_seen_at to be later
        b.last_seen_at = datetime.now(UTC) + timedelta(seconds=10)
        result = reg.list_entities(agent)
        assert next(e.id for e in result) == b.id
        # Filter by entity_type
        only_topic = reg.list_entities(agent, entity_type=EntityType.topic)
        assert len(only_topic) == 2
        only_person = reg.list_entities(agent, entity_type=EntityType.person)
        assert only_person == []

    def test_flag_disambiguation(self) -> None:
        reg = InMemoryEntityRegistry()
        agent = uuid4()
        ent, _ = reg.resolve_or_create(agent, "x", EntityType.topic)
        reg.flag_disambiguation(ent.id)
        loaded = reg.get_entity(ent.id)
        assert loaded is not None
        assert loaded.needs_disambiguation is True
        # unknown is no-op
        reg.flag_disambiguation(uuid4())

    def test_clear_resets_state(self) -> None:
        reg = InMemoryEntityRegistry()
        agent = uuid4()
        reg.resolve_or_create(agent, "x", EntityType.topic)
        reg.clear()
        assert reg.count() == 0


# ---------------------------------------------------------------------------
# InMemoryEntityStanceStore
# ---------------------------------------------------------------------------


class TestInMemoryEntityStanceStore:
    def test_no_stance_returns_none(self) -> None:
        store = InMemoryEntityStanceStore()
        assert store.get_current_stance(uuid4(), uuid4()) is None

    def test_write_and_get_current(self) -> None:
        store = InMemoryEntityStanceStore()
        agent = uuid4()
        ent = uuid4()
        s = store.write_stance(agent, ent, "trusts deeply", valence=0.8, intensity=0.6)
        current = store.get_current_stance(agent, ent)
        assert current is not None
        assert current.id == s.id
        assert current.stance_text == "trusts deeply"
        assert current.is_active is True

    def test_writing_supersedes_previous(self) -> None:
        store = InMemoryEntityStanceStore()
        agent = uuid4()
        ent = uuid4()
        first = store.write_stance(agent, ent, "neutral")
        second = store.write_stance(agent, ent, "warming up")
        history = store.get_stance_history(agent, ent)
        assert [s.id for s in history] == [second.id, first.id]
        # First should be superseded by second
        first_in_store = next(s for s in history if s.id == first.id)
        assert first_in_store.superseded_at is not None
        assert first_in_store.superseded_by == second.id

    def test_supersede_stance_explicit(self) -> None:
        store = InMemoryEntityStanceStore()
        agent = uuid4()
        ent = uuid4()
        first = store.write_stance(agent, ent, "x")
        replacement_id = uuid4()
        store.supersede_stance(first.id, superseded_by_id=replacement_id)
        history = store.get_stance_history(agent, ent)
        s = next(s for s in history if s.id == first.id)
        assert s.superseded_by == replacement_id
        # Unknown id is no-op
        store.supersede_stance(uuid4(), superseded_by_id=uuid4())

    def test_list_active_stances_filters_and_sorts(self) -> None:
        store = InMemoryEntityStanceStore()
        agent = uuid4()
        e1 = uuid4()
        e2 = uuid4()
        s1 = store.write_stance(agent, e1, "first")
        s2 = store.write_stance(agent, e2, "second")
        active = store.list_active_stances(agent)
        ids = {s.id for s in active}
        assert ids == {s1.id, s2.id}
        # formed_after filter
        future = datetime.now(UTC) + timedelta(hours=1)
        assert store.list_active_stances(agent, formed_after=future) == []


# ---------------------------------------------------------------------------
# NoOpReranker
# ---------------------------------------------------------------------------


class TestNoOpReranker:
    def _make(self, score: float, source: str = "dense") -> SurfacedMemory:
        return SurfacedMemory(
            key_moment_id=uuid4(),
            text=f"text {score}",
            score=score,
            source=source,
        )

    def test_sorts_desc_and_sets_final_score(self) -> None:
        rer = NoOpReranker()
        a = self._make(0.3)
        b = self._make(0.9)
        c = self._make(0.5)
        result = rer.rerank("query", [a, b, c], top_n=10)
        assert [m.score for m in result] == [0.9, 0.5, 0.3]
        assert all(m.final_score == m.score for m in result)

    def test_top_n_truncates(self) -> None:
        rer = NoOpReranker()
        candidates = [self._make(s / 10.0) for s in range(10)]
        result = rer.rerank("q", candidates, top_n=3)
        assert len(result) == 3
        assert result[0].score == 0.9

    def test_empty_input_returns_empty(self) -> None:
        rer = NoOpReranker()
        assert rer.rerank("q", [], top_n=5) == []


# ---------------------------------------------------------------------------
# NoOpLinguisticAnalyzer
# ---------------------------------------------------------------------------


class TestNoOpLinguisticAnalyzer:
    def test_user_message_returns_text_and_empty(self) -> None:
        a = NoOpLinguisticAnalyzer().analyze_user_message("hello")
        assert a.text == "hello"
        assert a.entities == []
        assert a.anchors == []

    def test_agent_message_defaults(self) -> None:
        a = NoOpLinguisticAnalyzer().analyze_agent_message("response", thinking="thinking")
        assert a.divergence_signals == []
        assert a.cognitive_load_high is False

    def test_key_moment_defaults(self) -> None:
        a = NoOpLinguisticAnalyzer().analyze_key_moment("what", "why")
        assert a.entities == []


# ---------------------------------------------------------------------------
# InMemoryMaintenanceQueue
# ---------------------------------------------------------------------------


class TestInMemoryMaintenanceQueue:
    def test_enqueue_creates_pending(self) -> None:
        q = InMemoryMaintenanceQueue()
        agent = uuid4()
        job = q.enqueue(JobName.salience_decay, agent_id=agent)
        assert job.status is JobStatus.pending
        assert job.agent_id == agent

    def test_enqueue_idempotent_via_run_key(self) -> None:
        q = InMemoryMaintenanceQueue()
        a = q.enqueue(JobName.salience_decay, run_key="day-2026-05-16-decay")
        b = q.enqueue(JobName.salience_decay, run_key="day-2026-05-16-decay")
        assert a.id == b.id
        assert len(q.list_jobs()) == 1

    def test_claim_batch_marks_running(self) -> None:
        q = InMemoryMaintenanceQueue()
        for _ in range(3):
            q.enqueue(JobName.salience_decay)
        claimed = q.claim_batch(batch_size=2)
        assert len(claimed) == 2
        assert all(c.status is JobStatus.running for c in claimed)
        # Remaining still pending
        pending = q.list_jobs(status=JobStatus.pending)
        assert len(pending) == 1

    def test_claim_batch_filters_by_job_name(self) -> None:
        q = InMemoryMaintenanceQueue()
        q.enqueue(JobName.salience_decay)
        q.enqueue(JobName.memory_guardian_scan)
        claimed = q.claim_batch(job_name=JobName.memory_guardian_scan, batch_size=10)
        assert len(claimed) == 1
        assert claimed[0].job_name is JobName.memory_guardian_scan

    def test_mark_done_failed_skipped(self) -> None:
        q = InMemoryMaintenanceQueue()
        j1 = q.enqueue(JobName.salience_decay)
        j2 = q.enqueue(JobName.salience_decay)
        j3 = q.enqueue(JobName.salience_decay)
        q.claim_batch(batch_size=10)
        q.mark_done(j1.id, result={"updated": 5})
        q.mark_failed(j2.id, error="boom")
        q.mark_skipped(j3.id, reason="dup")
        all_jobs = {j.id: j for j in q.list_jobs()}
        assert all_jobs[j1.id].status is JobStatus.succeeded
        assert all_jobs[j1.id].result == {"updated": 5}
        assert all_jobs[j2.id].status is JobStatus.failed
        assert all_jobs[j2.id].error == "boom"
        assert all_jobs[j3.id].status is JobStatus.skipped
        # Mark unknown id is silent
        q.mark_done(uuid4())
        q.mark_failed(uuid4(), error="x")
        q.mark_skipped(uuid4())

    def test_list_jobs_filter_and_order(self) -> None:
        q = InMemoryMaintenanceQueue()
        agent = uuid4()
        j1 = q.enqueue(JobName.salience_decay, agent_id=agent)
        j2 = q.enqueue(JobName.salience_decay)
        all_jobs = q.list_jobs()
        assert {j.id for j in all_jobs} == {j1.id, j2.id}
        only_agent = q.list_jobs(agent_id=agent)
        assert {j.id for j in only_agent} == {j1.id}


# ---------------------------------------------------------------------------
# ExperienceViewRepository
# ---------------------------------------------------------------------------


def _moment(session_id):
    return KeyMoment(
        what_happened="event",
        how_i_felt=FeltSense(
            emotional_valence=0.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
        ),
        why_it_matters="reason",
        session_id=session_id,
    )


class TestExperienceViewRepository:
    def test_get_unknown_returns_none(self) -> None:
        store = InMemoryStateStore()
        repo = ExperienceViewRepository(store)
        assert repo.get(uuid4()) is None

    def test_get_returns_session_experience(self) -> None:
        store = InMemoryStateStore()
        repo = ExperienceViewRepository(store)
        s = Session(agent_id=uuid4())
        store.create_session(s)
        m = _moment(s.id)
        store.store_key_moment(m)
        store.store_key_moments(s.id, [m])
        exp = repo.get(s.id)
        assert exp is not None
        assert exp.session_id == s.id
        assert m.id in exp.key_moment_ids

    def test_get_all_returns_only_sessions_with_moments(self) -> None:
        store = InMemoryStateStore()
        repo = ExperienceViewRepository(store)
        s1 = Session(agent_id=uuid4())
        store.create_session(s1)
        m = _moment(s1.id)
        store.store_key_moment(m)
        store.store_key_moments(s1.id, [m])
        # session without moment
        s2 = Session(agent_id=uuid4())
        store.create_session(s2)
        result = repo.get_all()
        assert {e.session_id for e in result} == {s1.id}

    def test_get_recent_respects_limit(self) -> None:
        store = InMemoryStateStore()
        repo = ExperienceViewRepository(store)
        for _ in range(3):
            s = Session(agent_id=uuid4())
            store.create_session(s)
            m = _moment(s.id)
            store.store_key_moment(m)
            store.store_key_moments(s.id, [m])
        recent = repo.get_recent(limit=2)
        assert len(recent) == 2

    def test_get_in_range(self) -> None:
        store = InMemoryStateStore()
        repo = ExperienceViewRepository(store)
        now = datetime.now(UTC)
        s = Session(agent_id=uuid4(), started_at=now)
        store.create_session(s)
        m = _moment(s.id)
        store.store_key_moment(m)
        store.store_key_moments(s.id, [m])
        result = repo.get_in_range(now - timedelta(hours=1), now + timedelta(hours=1))
        assert len(result) == 1
        out_of_range = repo.get_in_range(now + timedelta(hours=2), now + timedelta(hours=3))
        assert out_of_range == []

    def test_get_by_session(self) -> None:
        store = InMemoryStateStore()
        repo = ExperienceViewRepository(store)
        s = Session(agent_id=uuid4())
        store.create_session(s)
        m = _moment(s.id)
        store.store_key_moment(m)
        store.store_key_moments(s.id, [m])
        result = repo.get_by_session(s.id)
        assert len(result) == 1
        assert repo.get_by_session(uuid4()) == []

    def test_update_is_noop(self) -> None:
        store = InMemoryStateStore()
        repo = ExperienceViewRepository(store)
        s = Session(agent_id=uuid4())
        store.create_session(s)
        m = _moment(s.id)
        store.store_key_moment(m)
        store.store_key_moments(s.id, [m])
        exp = repo.get(s.id)
        assert exp is not None
        # update is documented as no-op for compat
        repo.update(exp)

    def test_add_reframing_note_on_existing_session(self) -> None:
        store = InMemoryStateStore()
        repo = ExperienceViewRepository(store)
        s = Session(agent_id=uuid4())
        store.create_session(s)
        m = _moment(s.id)
        store.store_key_moment(m)
        store.store_key_moments(s.id, [m])
        # Compat layer treats experience_id == session_id; need an experience
        # record because state_store.add_reframing_note targets ExperienceRecord.
        from atman.core.models import ExperienceRecord, SessionExperience

        exp = SessionExperience(
            id=s.id,
            session_id=s.id,
            timestamp=datetime.now(UTC),
            key_moment_ids=[m.id],
        )
        store.create_experience(ExperienceRecord(experience=exp))
        note = ReframingNote(reflection="r", reflection_type="growth")
        from atman.core.models.experience import ReframingNoteAppendResult

        outcome = repo.add_reframing_note(s.id, note)
        assert outcome is ReframingNoteAppendResult.STORED

    def test_add_reframing_note_on_unknown_returns_not_found(self) -> None:
        store = InMemoryStateStore()
        repo = ExperienceViewRepository(store)
        from atman.core.models.experience import ReframingNoteAppendResult

        result = repo.add_reframing_note(
            uuid4(), ReframingNote(reflection="r", reflection_type="growth")
        )
        assert result is ReframingNoteAppendResult.EXPERIENCE_NOT_FOUND


# ---------------------------------------------------------------------------
# Regression: ExperienceViewRepository.get returns None for sessions with
# zero key moments instead of crashing with ValidationError (key_moment_ids
# requires min_length=1).
# ---------------------------------------------------------------------------


def test_experience_view_repo_get_session_with_no_moments_returns_none() -> None:
    store = InMemoryStateStore()
    repo = ExperienceViewRepository(store)
    s = Session(agent_id=uuid4())
    store.create_session(s)
    # No key moments stored yet
    assert repo.get(s.id) is None


# ---------------------------------------------------------------------------
# Regression: FileStateStore.store_key_moment is a true upsert (replaces
# existing record by id, not just append-only no-op). Required for
# salience_decay_service to actually persist updates against FileStateStore.
# ---------------------------------------------------------------------------


def test_file_state_store_store_key_moment_replaces_existing(tmp_path) -> None:
    from atman.adapters.storage.file_state_store import FileStateStore

    store = FileStateStore(tmp_path)
    session_id = uuid4()
    m = KeyMoment(
        what_happened="initial",
        how_i_felt=FeltSense(
            emotional_valence=0.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
        ),
        why_it_matters="reason",
        session_id=session_id,
        salience=1.0,
    )
    store.store_key_moment(m)
    # Now mutate salience and re-store
    m.salience = 0.42
    store.store_key_moment(m)
    # Should reflect the updated salience, not the original
    loaded = store.get_key_moment(m.id)
    assert loaded is not None
    assert loaded.salience == pytest.approx(0.42)


# ---------------------------------------------------------------------------
# Regression: default StateStore.store_key_moment raises NotImplementedError
# on attempted update via store with no override (rather than silently
# no-op'ing or crashing with ValueError). Concrete adapters that need
# upsert MUST override.
# ---------------------------------------------------------------------------


def test_default_store_key_moment_raises_not_implemented_on_duplicate() -> None:
    """A bare StateStore subclass that doesn't override store_key_moment
    must NOT silently accept an update — it must surface NotImplementedError
    so adapter authors know to implement true upsert."""
    from atman.core.ports.state_store import StateStore

    class _Bare(StateStore):
        def __init__(self) -> None:
            self._km: dict = {}

        # Only KeyMoment ops are needed for this test; minimal stubs for
        # the abstract members are below.

        def create_key_moment(self, key_moment):
            if key_moment.id in self._km:
                raise ValueError(f"KeyMoment {key_moment.id} already exists")
            self._km[key_moment.id] = key_moment
            return key_moment

        def get_key_moment(self, moment_id):
            return self._km.get(moment_id)

        def list_key_moments(self, session_id=None):
            return list(self._km.values())

        def store_key_moments(self, session_id, moments):
            for m in moments:
                self._km[m.id] = m

        def get_key_moments_for_session(self, session_id):
            return [m for m in self._km.values() if m.session_id == session_id]

        # Bare minimum to satisfy ABC — all other ops are out of scope
        def create_experience(self, record):
            raise NotImplementedError

        def get_experience(self, experience_id):
            return None

        def add_reframing_note(self, experience_id, note):
            return None

        def mark_accessed(self, experience_id):
            return None

        def search_experiences(self, query=None, limit=10):
            return []

        def list_recent_experiences(self, limit=10):
            return []

        def load_identity(self, agent_id):
            return None

        def save_identity(self, identity, expected_version=None):
            return identity

        def create_identity_snapshot(self, snapshot):
            return snapshot

        def list_identity_snapshots(self, identity_id, limit=10):
            return []

        def load_narrative(self, identity_id):
            return None

        def save_narrative(self, narrative, expected_version=None, expected_updated_at=None):
            return narrative

        def archive_narrative(self, narrative_id, reason):
            return None

        def list_archived_narratives(self, identity_id, limit=10):
            return []

        def save_eigenstate(self, eigenstate):
            return eigenstate

        def load_latest_eigenstate(self, session_id=None, identity_id=None):
            return None

    store = _Bare()
    m = KeyMoment(
        what_happened="x",
        how_i_felt=FeltSense(
            emotional_valence=0.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
        ),
        why_it_matters="why",
        session_id=uuid4(),
    )
    # First call succeeds (delegate to create_key_moment)
    store.store_key_moment(m)
    # Second call must raise NotImplementedError (not ValueError or silent no-op)
    with pytest.raises(NotImplementedError, match="must override"):
        store.store_key_moment(m)


# ---------------------------------------------------------------------------
# Regression: FileStateStore.store_key_moment must update ALL three storage
# layers — JSONL, per-moment .json (read first by get_key_moment), and the
# per-session _moments.json (read by get_key_moments_for_session). Decay
# updates were previously silently lost because only the JSONL was rewritten.
# ---------------------------------------------------------------------------


def test_file_state_store_store_key_moment_updates_per_moment_file(tmp_path) -> None:
    from atman.adapters.storage.file_state_store import FileStateStore

    store = FileStateStore(tmp_path)
    session_id = uuid4()
    m = KeyMoment(
        what_happened="initial",
        how_i_felt=FeltSense(
            emotional_valence=0.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
        ),
        why_it_matters="reason",
        session_id=session_id,
        salience=1.0,
    )
    # Initial creation via store_key_moments (writes both .json and JSONL)
    store.store_key_moments(session_id, [m])
    # Now update salience and call store_key_moment (singular)
    m.salience = 0.42
    store.store_key_moment(m)
    # get_key_moment reads the per-moment .json first — must show new value
    loaded = store.get_key_moment(m.id)
    assert loaded is not None
    assert loaded.salience == pytest.approx(0.42)


def test_file_state_store_store_key_moment_updates_session_file(tmp_path) -> None:
    from atman.adapters.storage.file_state_store import FileStateStore

    store = FileStateStore(tmp_path)
    session_id = uuid4()
    m = KeyMoment(
        what_happened="initial",
        how_i_felt=FeltSense(
            emotional_valence=0.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
        ),
        why_it_matters="reason",
        session_id=session_id,
        salience=1.0,
    )
    store.store_key_moments(session_id, [m])
    m.salience = 0.42
    store.store_key_moment(m)
    # get_key_moments_for_session reads the per-session file — must show new value
    moments = store.get_key_moments_for_session(session_id)
    assert len(moments) == 1
    assert moments[0].salience == pytest.approx(0.42)
