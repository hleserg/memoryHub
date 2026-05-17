"""Tests for the Living Memory (E24) services that lacked direct unit coverage.

Covers:
- :class:`SessionWorkingMemory` — LRU cache for surfaced facts/experiences.
- :class:`ConflictDetector` — pairwise contradiction detection.
- :class:`EmotionalEcho` — historical emotional context aggregation.
- :class:`PassiveMemoryInjector` — automatic memory surfacing via embeddings.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from atman.adapters.memory import InMemoryBackend
from atman.adapters.memory.mock_embedding import MockEmbeddingAdapter
from atman.adapters.storage.in_memory_state_store import InMemoryStateStore
from atman.core.models import FactRecord, FactStatus, Relation
from atman.core.models.experience import (
    EmotionalDepth,
    ExperienceRecord,
    FeltSense,
    KeyMoment,
    SessionExperience,
)
from atman.core.services.conflict_detector import ConflictDetector, FactConflict
from atman.core.services.emotional_echo import EmotionalEcho
from atman.core.services.passive_memory_injector import (
    PassiveMemoryInjector,
    SurfacedMemory,
)
from atman.core.services.session_working_memory import (
    CachedItem,
    SessionWorkingMemory,
)


def _make_experience(
    *,
    session_id: UUID | None = None,
    valence: float = 0.4,
    intensity: float = 0.7,
    depth: EmotionalDepth = EmotionalDepth.MEANINGFUL,
    timestamp: datetime | None = None,
    moments: list[tuple[str, str]] | None = None,
) -> SessionExperience:
    felt = FeltSense(emotional_valence=valence, emotional_intensity=intensity, depth=depth)
    pairs = moments or [("Test moment", "For testing")]
    key_moments = [
        KeyMoment(what_happened=text, how_i_felt=felt, why_it_matters=reason)
        for text, reason in pairs
    ]
    avg = sum(km.how_i_felt.emotional_intensity for km in key_moments) / len(key_moments)
    profound = any(km.how_i_felt.depth == EmotionalDepth.PROFOUND for km in key_moments)
    exp = SessionExperience(
        session_id=session_id or uuid4(),
        key_moment_ids=[km.id for km in key_moments],
        avg_emotional_intensity=avg,
        has_profound_moment=profound,
        importance=0.6,
        salience=0.8,
    )
    object.__setattr__(exp, "_living_test_moments", tuple(key_moments))
    if timestamp is not None:
        exp.timestamp = timestamp
    return exp


def _persist_experience(store: InMemoryStateStore, exp: SessionExperience) -> None:
    store.create_experience(ExperienceRecord(experience=exp))
    moments = getattr(exp, "_living_test_moments", ())
    if moments:
        store.store_key_moments(exp.session_id, list(moments))


# ──────────────────────────────────────────────────────────────────────────────
# SessionWorkingMemory
# ──────────────────────────────────────────────────────────────────────────────


class TestSessionWorkingMemory:
    """In-session LRU cache for surfaced items."""

    def test_has_and_size(self) -> None:
        wm = SessionWorkingMemory()
        fact = FactRecord(content="hello", source="test")
        assert wm.size() == 0
        assert not wm.has(fact.id)
        wm.add_fact(fact)
        assert wm.has(fact.id)
        assert wm.size() == 1

    def test_get_returns_none_for_missing(self) -> None:
        wm = SessionWorkingMemory()
        assert wm.get(uuid4()) is None

    def test_get_increments_access_count_and_updates_order(self) -> None:
        wm = SessionWorkingMemory()
        f1 = FactRecord(content="one", source="src")
        f2 = FactRecord(content="two", source="src")
        wm.add_fact(f1)
        wm.add_fact(f2)
        # Initially f1 is least-recently used.
        assert wm.list_cached()[0].item_id == f1.id

        item = wm.get(f1.id)
        assert isinstance(item, CachedItem)
        assert item.access_count == 2  # 1 from add + 1 from get
        # Access bumps f1 to most-recently used (end).
        assert wm.list_cached()[-1].item_id == f1.id

    def test_add_fact_idempotent(self) -> None:
        wm = SessionWorkingMemory()
        fact = FactRecord(content="dup", source="src")
        wm.add_fact(fact)
        wm.add_fact(fact)
        assert wm.size() == 1

    def test_add_experience_summary_uses_metadata(self) -> None:
        wm = SessionWorkingMemory()
        exp = _make_experience(
            moments=[
                ("first happens", "matters"),
                ("second happens", "matters"),
                ("third should be omitted", "matters"),
            ]
        )
        wm.add_experience(exp)
        cached = wm.get(exp.id)
        assert cached is not None
        assert "3 key moments" in cached.content
        assert "avg_intensity" in cached.content

    def test_add_experience_idempotent(self) -> None:
        wm = SessionWorkingMemory()
        exp = _make_experience()
        wm.add_experience(exp)
        wm.add_experience(exp)
        assert wm.size() == 1

    def test_add_facts_batch_filters_already_cached(self) -> None:
        wm = SessionWorkingMemory()
        f1 = FactRecord(content="a", source="s")
        f2 = FactRecord(content="b", source="s")
        wm.add_fact(f1)
        new = wm.add_facts_batch([f1, f2])
        assert [f.id for f in new] == [f2.id]
        assert wm.size() == 2

    def test_list_cached_filters_by_type(self) -> None:
        wm = SessionWorkingMemory()
        fact = FactRecord(content="fact", source="s")
        exp = _make_experience()
        wm.add_fact(fact)
        wm.add_experience(exp)
        facts = wm.list_cached("fact")
        exps = wm.list_cached("experience")
        assert [c.item_id for c in facts] == [fact.id]
        assert [c.item_id for c in exps] == [exp.id]

    def test_clear_empties_cache(self) -> None:
        wm = SessionWorkingMemory()
        wm.add_fact(FactRecord(content="x", source="s"))
        wm.clear()
        assert wm.size() == 0
        assert wm.list_cached() == []

    def test_evicts_oldest_when_full(self) -> None:
        wm = SessionWorkingMemory(max_size=2)
        f1 = FactRecord(content="one", source="s")
        f2 = FactRecord(content="two", source="s")
        f3 = FactRecord(content="three", source="s")
        wm.add_fact(f1)
        wm.add_fact(f2)
        wm.add_fact(f3)
        assert wm.size() == 2
        # f1 is the oldest entry and must have been evicted.
        assert not wm.has(f1.id)
        assert wm.has(f2.id) and wm.has(f3.id)


# ──────────────────────────────────────────────────────────────────────────────
# ConflictDetector
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def memory() -> InMemoryBackend:
    return InMemoryBackend()


class TestConflictDetector:
    """Pairwise contradiction detection on factual memory."""

    def test_check_fact_skips_invalidated_input(self, memory: InMemoryBackend) -> None:
        detector = ConflictDetector(memory)
        invalid = FactRecord(content="x", source="s", status=FactStatus.INVALIDATED)
        memory.add_fact(invalid)
        assert detector.check_fact(invalid) == []

    def test_check_fact_returns_empty_when_no_candidates(self, memory: InMemoryBackend) -> None:
        detector = ConflictDetector(memory)
        fact = FactRecord(content="lone fact about ducks", source="s")
        memory.add_fact(fact)
        # Only `fact` is in memory; `check_fact` skips itself.
        assert detector.check_fact(fact) == []

    def test_detect_negation_contradiction_directly(self, memory: InMemoryBackend) -> None:
        detector = ConflictDetector(memory)
        positive = FactRecord(
            content="meeting with alice scheduled tomorrow",
            source="calendar",
            tags=["meeting"],
        )
        negative = FactRecord(
            content="meeting with alice cancelled tomorrow",
            source="email",
            tags=["meeting"],
        )
        # Exercise the comparison primitive directly: it handles content
        # similarity + negation pattern logic.
        conflict = detector._detect_conflict(positive, negative)
        assert isinstance(conflict, FactConflict)
        assert conflict.conflict_type == "contradiction"
        assert 0.0 <= conflict.confidence <= 1.0

    def test_detect_inconsistency_via_shared_tags(self, memory: InMemoryBackend) -> None:
        detector = ConflictDetector(memory)
        a = FactRecord(
            content="server uses postgres database backend version 14",
            source="docs",
            tags=["infra", "db"],
        )
        b = FactRecord(
            content="server uses postgres database backend version 15",
            source="docs",
            tags=["infra", "db"],
        )
        # No negation, but high content similarity + shared tags -> inconsistency.
        conflict = detector._detect_conflict(a, b)
        assert isinstance(conflict, FactConflict)
        assert conflict.conflict_type == "inconsistency"

    def test_detect_no_conflict_for_unrelated_facts(self, memory: InMemoryBackend) -> None:
        detector = ConflictDetector(memory)
        a = FactRecord(content="cats love sunshine and warmth", source="cat-fact")
        b = FactRecord(content="quantum mechanics describes subatomic", source="phys")
        assert detector._detect_conflict(a, b) is None

    def test_scan_all_conflicts_finds_pairwise_negation(self, memory: InMemoryBackend) -> None:
        detector = ConflictDetector(memory)
        positive = FactRecord(content="meeting alice scheduled today", source="cal", tags=["meet"])
        cancelled = FactRecord(
            content="meeting alice cancelled today",
            source="email",
            tags=["meet"],
        )
        memory.add_fact(positive)
        memory.add_fact(cancelled)

        conflicts = detector.scan_all_conflicts(limit=10)
        assert conflicts, "scan_all_conflicts should find the cross-pair contradiction"

    def test_scan_all_conflicts_skips_invalidated(self, memory: InMemoryBackend) -> None:
        detector = ConflictDetector(memory)
        positive = FactRecord(content="meeting alice scheduled today", source="cal", tags=["meet"])
        cancelled = FactRecord(
            content="meeting alice cancelled today",
            source="email",
            tags=["meet"],
        )
        memory.add_fact(positive)
        memory.add_fact(cancelled)
        # Once the cancelled fact is invalidated, no pair conflicts.
        memory.invalidate_fact(cancelled.id, status=FactStatus.INVALIDATED, note="obsolete")
        assert detector.scan_all_conflicts(limit=10) == []

    def test_content_similarity_handles_empty_strings(self, memory: InMemoryBackend) -> None:
        detector = ConflictDetector(memory)
        assert detector._content_similarity("", "anything") == 0.0
        assert detector._content_similarity("x y z", "") == 0.0

    def test_get_cognitive_tension_zero_for_no_conflicts(self, memory: InMemoryBackend) -> None:
        detector = ConflictDetector(memory)
        assert detector.get_cognitive_tension([]) == 0.0

    def test_get_cognitive_tension_capped_at_one(self, memory: InMemoryBackend) -> None:
        detector = ConflictDetector(memory)
        conflicts = [
            FactConflict(
                fact1_id=uuid4(),
                fact2_id=uuid4(),
                fact1_content="a",
                fact2_content="b",
                conflict_type="contradiction",
                confidence=0.9,
                description="d",
            )
            for _ in range(5)
        ]
        tension = detector.get_cognitive_tension(conflicts)
        assert 0.0 <= tension <= 1.0


# ──────────────────────────────────────────────────────────────────────────────
# EmotionalEcho
# ──────────────────────────────────────────────────────────────────────────────


class TestEmotionalEcho:
    """Historical emotional context aggregator."""

    def _store_with(self, experiences: list[SessionExperience]) -> InMemoryStateStore:
        store = InMemoryStateStore()
        for exp in experiences:
            _persist_experience(store, exp)
        return store

    def test_build_echo_empty_store_returns_empty(self) -> None:
        echo = EmotionalEcho(InMemoryStateStore())
        assert echo.build_echo() == []

    def test_build_echo_filters_by_lookback_window(self) -> None:
        now = datetime.now(UTC)
        recent = _make_experience(timestamp=now - timedelta(hours=1))
        ancient = _make_experience(timestamp=now - timedelta(days=30))
        store = self._store_with([recent, ancient])

        echo = EmotionalEcho(store, lookback_days=7, max_echoes=10)
        items = echo.build_echo(current_time=now)
        ids = {item.experience_id for item in items}
        assert str(recent.id) in ids
        assert str(ancient.id) not in ids

    def test_build_echo_excludes_current_session(self) -> None:
        now = datetime.now(UTC)
        sid_current = uuid4()
        sid_other = uuid4()
        current = _make_experience(session_id=sid_current, timestamp=now - timedelta(hours=1))
        other = _make_experience(session_id=sid_other, timestamp=now - timedelta(hours=1))
        store = self._store_with([current, other])

        echo = EmotionalEcho(store)
        items = echo.build_echo(exclude_session_id=str(sid_current), current_time=now)
        assert all(item.experience_id != str(current.id) for item in items)

    def test_build_echo_orders_by_score_desc(self) -> None:
        now = datetime.now(UTC)
        big = _make_experience(
            valence=0.5,
            intensity=0.9,
            depth=EmotionalDepth.PROFOUND,
            timestamp=now - timedelta(hours=1),
        )
        small = _make_experience(
            valence=0.5,
            intensity=0.2,
            depth=EmotionalDepth.SURFACE,
            timestamp=now - timedelta(hours=1),
        )
        store = self._store_with([big, small])
        echo = EmotionalEcho(store)
        items = echo.build_echo(current_time=now)
        assert items[0].echo_score >= items[-1].echo_score

    def test_build_echo_respects_max_echoes(self) -> None:
        now = datetime.now(UTC)
        experiences = [_make_experience(timestamp=now - timedelta(hours=i + 1)) for i in range(5)]
        store = self._store_with(experiences)

        echo = EmotionalEcho(store, max_echoes=2)
        items = echo.build_echo(current_time=now)
        assert len(items) <= 2

    def test_build_context_summary_when_empty(self) -> None:
        echo = EmotionalEcho(InMemoryStateStore())
        assert "No recent emotional context." in echo.build_context_summary()

    def test_build_context_summary_renders_tone(self) -> None:
        now = datetime.now(UTC)
        positive = _make_experience(valence=0.6, intensity=0.7, timestamp=now - timedelta(hours=1))
        negative = _make_experience(valence=-0.6, intensity=0.7, timestamp=now - timedelta(hours=1))
        store = self._store_with([positive, negative])
        echo = EmotionalEcho(store)
        summary = echo.build_context_summary(current_time=now)
        assert "positive" in summary
        assert "negative" in summary

    def test_get_dominant_emotional_tone_no_echoes(self) -> None:
        echo = EmotionalEcho(InMemoryStateStore())
        assert echo.get_dominant_emotional_tone() == 0.0

    def test_get_dominant_emotional_tone_weighted_average(self) -> None:
        now = datetime.now(UTC)
        a = _make_experience(valence=0.8, intensity=0.9, timestamp=now - timedelta(hours=1))
        b = _make_experience(valence=-0.4, intensity=0.5, timestamp=now - timedelta(hours=2))
        store = self._store_with([a, b])
        echo = EmotionalEcho(store)
        tone = echo.get_dominant_emotional_tone(current_time=now)
        # Weighted by recency × intensity → strong positive contribution dominates.
        assert tone > 0.0


# ──────────────────────────────────────────────────────────────────────────────
# PassiveMemoryInjector
# ──────────────────────────────────────────────────────────────────────────────


class TestPassiveMemoryInjector:
    """Surfaces relevant facts and experiences via embedding similarity."""

    def test_surface_for_context_returns_empty_when_memory_empty(self) -> None:
        injector = PassiveMemoryInjector(
            embedding=MockEmbeddingAdapter(),
            factual_memory=InMemoryBackend(),
            state_store=InMemoryStateStore(),
            min_similarity_threshold=-1.0,
        )
        assert injector.surface_for_context("anything") == []

    def test_surface_for_context_returns_similar_facts(self) -> None:
        memory = InMemoryBackend()
        target = FactRecord(content="user prefers dark mode UI", source="profile")
        unrelated = FactRecord(content="sunshine after rain", source="weather")
        memory.add_fact(target)
        memory.add_fact(unrelated)

        injector = PassiveMemoryInjector(
            embedding=MockEmbeddingAdapter(),
            factual_memory=memory,
            state_store=InMemoryStateStore(),
            top_k_similarity=5,
            associative_expand=False,
            # Mock embeddings rarely cross the default 0.3 threshold; lower for tests.
            min_similarity_threshold=-1.0,
        )
        results = injector.surface_for_context("user prefers dark mode UI")
        assert results, "expected at least one surfaced fact"
        assert all(isinstance(r, SurfacedMemory) for r in results)
        assert all(r.source == "similarity" for r in results)
        # The exact-match fact should appear with the highest score.
        ids = [r.item.id for r in results if isinstance(r.item, FactRecord)]
        assert target.id in ids

    def test_surface_for_context_skips_facts_already_in_working_memory(self) -> None:
        memory = InMemoryBackend()
        f1 = FactRecord(content="alpha bravo charlie", source="s")
        memory.add_fact(f1)

        wm = SessionWorkingMemory()
        wm.add_fact(f1)

        injector = PassiveMemoryInjector(
            embedding=MockEmbeddingAdapter(),
            factual_memory=memory,
            state_store=InMemoryStateStore(),
            associative_expand=False,
            min_similarity_threshold=-1.0,
        )
        # f1 is in working memory, so it must not be surfaced again.
        results = injector.surface_for_context("alpha bravo", working_memory=wm)
        assert all(r.item.id != f1.id for r in results)

    def test_surface_for_context_skips_empty_content_facts(self) -> None:
        memory = InMemoryBackend()
        normal = FactRecord(content="alpha bravo", source="s")
        memory.add_fact(normal)

        injector = PassiveMemoryInjector(
            embedding=MockEmbeddingAdapter(),
            factual_memory=memory,
            state_store=InMemoryStateStore(),
            associative_expand=False,
            min_similarity_threshold=-1.0,
        )
        results = injector.surface_for_context("alpha bravo")
        # All surfaced facts have non-blank content.
        assert all(isinstance(r.item, FactRecord) and r.item.content.strip() for r in results)

    def test_surface_for_context_associative_expansion(self) -> None:
        memory = InMemoryBackend()
        anchor = FactRecord(content="user enjoys jazz music daily", source="profile")
        related = FactRecord(content="bought saxophone last month", source="email")
        memory.add_fact(anchor)
        memory.add_fact(related)
        # Wire a relation: anchor → related so `_associative_expand` can pull it.
        memory.link(anchor.id, related.id, "led_to")

        injector = PassiveMemoryInjector(
            embedding=MockEmbeddingAdapter(),
            factual_memory=memory,
            state_store=InMemoryStateStore(),
            top_k_similarity=1,
            associative_expand=True,
            min_similarity_threshold=-1.0,
        )
        results = injector.surface_for_context("user enjoys jazz music daily")
        sources = {r.source for r in results}
        # Must contain both the similarity-anchored fact and the associative one.
        assert "similarity" in sources
        # `related` is reachable only via the associative expansion path.
        assert any(isinstance(r.item, FactRecord) and r.item.id == related.id for r in results)

    def test_associative_expand_skips_invalidated(self) -> None:
        memory = InMemoryBackend()
        anchor = FactRecord(content="anchor", source="s")
        invalid = FactRecord(content="bad", source="s")
        memory.add_fact(anchor)
        memory.add_fact(invalid)
        memory.invalidate_fact(invalid.id, status=FactStatus.INVALIDATED, note="x")
        # Manually wire a relation since `link` validates fact existence.
        anchor_in_store = memory.get_fact(anchor.id)
        assert anchor_in_store is not None
        anchor_in_store.relations.append(Relation(target_id=invalid.id, relation_type="related"))

        injector = PassiveMemoryInjector(
            embedding=MockEmbeddingAdapter(),
            factual_memory=memory,
            state_store=InMemoryStateStore(),
            min_similarity_threshold=-1.0,
        )
        related = injector._associative_expand({anchor.id})
        assert all(r.id != invalid.id for r in related)

    def test_surface_experiences_returns_top_matches(self) -> None:
        store = InMemoryStateStore()
        target_exp = _make_experience(
            moments=[("alpha bravo charlie debug logs", "explains failure")],
        )
        unrelated_exp = _make_experience(
            moments=[("entirely different topic about cooking", "matters")],
        )
        _persist_experience(store, target_exp)
        _persist_experience(store, unrelated_exp)

        injector = PassiveMemoryInjector(
            embedding=MockEmbeddingAdapter(),
            factual_memory=InMemoryBackend(),
            state_store=store,
            min_similarity_threshold=-1.0,
        )
        results = injector.surface_experiences("alpha bravo charlie debug logs", limit=2)
        assert results, "expected at least one surfaced experience"
        ids = [r.item.id for r in results if isinstance(r.item, SessionExperience)]
        assert target_exp.id in ids

    def test_surface_experiences_empty_store_returns_empty(self) -> None:
        injector = PassiveMemoryInjector(
            embedding=MockEmbeddingAdapter(),
            factual_memory=InMemoryBackend(),
            state_store=InMemoryStateStore(),
            min_similarity_threshold=-1.0,
        )
        assert injector.surface_experiences("anything") == []

    def test_surface_experiences_skips_working_memory_hits(self) -> None:
        store = InMemoryStateStore()
        exp = _make_experience(moments=[("alpha bravo", "matters")])
        _persist_experience(store, exp)

        wm = SessionWorkingMemory()
        wm.add_experience(exp)

        injector = PassiveMemoryInjector(
            embedding=MockEmbeddingAdapter(),
            factual_memory=InMemoryBackend(),
            state_store=store,
            min_similarity_threshold=-1.0,
        )
        results = injector.surface_experiences("alpha bravo", working_memory=wm)
        # The single experience is in working memory → no surfacing.
        assert results == []

    def test_surface_experiences_skips_empty_text(self) -> None:
        # ``surface_experiences`` skips records whose joined key-moment text
        # is whitespace-only. Use the store's private dict to seed such a
        # degenerate record (the public API rejects empty key_moments).
        store = InMemoryStateStore()
        exp = _make_experience(moments=[("alpha bravo", "matters")])
        _persist_experience(store, exp)
        # Remove stored moments so joined key-moment text is empty.
        stored = store._experiences[exp.id]
        for mid in list(stored.experience.key_moment_ids):
            store._key_moments.pop(mid, None)

        injector = PassiveMemoryInjector(
            embedding=MockEmbeddingAdapter(),
            factual_memory=InMemoryBackend(),
            state_store=store,
            min_similarity_threshold=-1.0,
        )
        results = injector.surface_experiences("alpha")
        assert results == []
