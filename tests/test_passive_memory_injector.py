"""Tests for PassiveMemoryInjector (E24.6, E24.8)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from atman.adapters.memory.bm25_embedding import BM25EmbeddingAdapter
from atman.adapters.memory.in_memory_backend import InMemoryBackend
from atman.adapters.memory.mock_embedding import MockEmbeddingAdapter
from atman.adapters.storage.in_memory_state_store import InMemoryStateStore
from atman.core.models import KeyMoment, SessionExperience
from atman.core.models.experience import EmotionalDepth, ExperienceRecord, FeltSense
from atman.core.models.fact import FactRecord, FactStatus, Relation
from atman.core.services.passive_memory_injector import PassiveMemoryInjector
from atman.core.services.session_working_memory import SessionWorkingMemory


class _StaticEmbedding:
    """Embedding stub returning fixed vectors for a known text -> vector map.

    Used to exercise PassiveMemoryInjector without depending on stochastic
    similarity from MockEmbeddingAdapter.
    """

    def __init__(self) -> None:
        self.dim = 4
        self.vectors: dict[str, list[float]] = {}

    def add(self, text: str, vec: list[float]) -> None:
        self.vectors[text] = vec

    def embed(self, text: str) -> list[float]:
        return self.vectors.get(text, [0.0] * self.dim)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]

    def dimension(self) -> int:
        return self.dim

    def model_name(self) -> str:
        return "static-test-embedding"

    def similarity(self, vec1: list[float], vec2: list[float]) -> float:
        a, b = vec1, vec2
        if len(a) != len(b):
            raise ValueError
        # Use dot product since the test vectors are unit-ish
        return sum(x * y for x, y in zip(a, b, strict=True))


def _experience(
    *, what_happened: str, timestamp: datetime | None = None
) -> tuple[SessionExperience, KeyMoment]:
    ts = timestamp or datetime.now(UTC)
    moment = KeyMoment(
        what_happened=what_happened,
        when=ts,
        how_i_felt=FeltSense(
            emotional_valence=0.0,
            emotional_intensity=0.5,
            depth=EmotionalDepth.MEANINGFUL,
        ),
        why_it_matters="why",
    )
    exp = SessionExperience(
        session_id=uuid4(),
        timestamp=ts,
        key_moment_ids=[moment.id],
        avg_emotional_intensity=moment.how_i_felt.emotional_intensity,
        has_profound_moment=moment.how_i_felt.depth == EmotionalDepth.PROFOUND,
    )
    return exp, moment


def _save_experience(store: InMemoryStateStore, exp: SessionExperience, moment: KeyMoment) -> None:
    store.create_experience(ExperienceRecord(experience=exp))
    store.store_key_moments(exp.session_id, [moment])


def test_surface_for_context_filters_below_threshold():
    # InMemoryBackend.search() uses substring matching, so context_text must
    # be a substring of fact content for the fact to even reach the embedding
    # similarity stage.
    backend = InMemoryBackend()
    backend.add_fact(FactRecord(content="alpha tag content", source="t"))

    embed = _StaticEmbedding()
    embed.add("alpha", [1.0, 0.0, 0.0, 0.0])
    embed.add("alpha tag content", [0.0, 1.0, 0.0, 0.0])  # orthogonal to query

    injector = PassiveMemoryInjector(
        embedding=embed,
        factual_memory=backend,
        state_store=InMemoryStateStore(),
        top_k_similarity=5,
        min_similarity_threshold=0.3,
        associative_expand=False,
    )
    surfaced = injector.surface_for_context("alpha")
    assert surfaced == []


def test_surface_for_context_returns_top_k_by_similarity():
    backend = InMemoryBackend()
    near = backend.add_fact(FactRecord(content="match near", source="t"))
    far = backend.add_fact(FactRecord(content="match far", source="t"))

    embed = _StaticEmbedding()
    embed.add("match", [1.0, 0.0, 0.0, 0.0])
    embed.add("match near", [0.9, 0.1, 0.0, 0.0])
    embed.add("match far", [0.4, 0.5, 0.0, 0.0])

    injector = PassiveMemoryInjector(
        embedding=embed,
        factual_memory=backend,
        state_store=InMemoryStateStore(),
        top_k_similarity=1,
        min_similarity_threshold=0.3,
        associative_expand=False,
    )
    surfaced = injector.surface_for_context("match")
    assert len(surfaced) == 1
    assert surfaced[0].item.id == near.id
    assert surfaced[0].source == "similarity"
    # `far` was filtered out
    assert all(s.item.id != far.id for s in surfaced)


def test_surface_for_context_skips_facts_in_working_memory():
    backend = InMemoryBackend()
    cached = backend.add_fact(FactRecord(content="cached fact body", source="t"))

    embed = _StaticEmbedding()
    embed.add("cached", [1.0, 0.0, 0.0, 0.0])
    embed.add("cached fact body", [1.0, 0.0, 0.0, 0.0])

    wm = SessionWorkingMemory()
    wm.add_fact(cached)
    injector = PassiveMemoryInjector(
        embedding=embed,
        factual_memory=backend,
        state_store=InMemoryStateStore(),
        associative_expand=False,
    )
    surfaced = injector.surface_for_context("cached", working_memory=wm)
    assert surfaced == []


def test_surface_for_context_expands_via_associative_links():
    backend = InMemoryBackend()
    target = backend.add_fact(FactRecord(content="orthogonal target body", source="t"))
    seed = backend.add_fact(
        FactRecord(
            content="seed body content",
            source="t",
            relations=[Relation(target_id=target.id, relation_type="related_to")],
        )
    )

    embed = _StaticEmbedding()
    embed.add("seed", [1.0, 0.0, 0.0, 0.0])
    embed.add("seed body content", [1.0, 0.0, 0.0, 0.0])
    # The associative expansion does not re-check similarity; it simply links
    # whatever fact is on the other end of an active relation.
    embed.add("orthogonal target body", [0.0, 1.0, 0.0, 0.0])

    injector = PassiveMemoryInjector(
        embedding=embed,
        factual_memory=backend,
        state_store=InMemoryStateStore(),
        top_k_similarity=1,
        min_similarity_threshold=0.5,
        associative_expand=True,
    )
    surfaced = injector.surface_for_context("seed")
    sources = {s.source for s in surfaced}
    assert sources == {"similarity", "associative"}
    ids = {s.item.id for s in surfaced}
    assert ids == {seed.id, target.id}


def test_surface_for_context_skips_non_active_associative_neighbors():
    """Associative expansion must compare via FactStatus enum, not raw string.

    Regression: a previous version compared ``status.value == "active"`` which
    would silently break if the enum's wire value were ever renamed. Non-ACTIVE
    neighbors (DISPUTED / INVALIDATED / SUPERSEDED) must not bleed back into
    the surfaced set.
    """
    backend = InMemoryBackend()
    disputed_target = backend.add_fact(FactRecord(content="disputed target body", source="t"))
    invalidated_target = backend.add_fact(FactRecord(content="invalidated target body", source="t"))
    seed = backend.add_fact(
        FactRecord(
            content="seed body content",
            source="t",
            relations=[
                Relation(target_id=disputed_target.id, relation_type="related_to"),
                Relation(target_id=invalidated_target.id, relation_type="related_to"),
            ],
        )
    )
    backend.invalidate_fact(disputed_target.id, status=FactStatus.DISPUTED, note="conflict")
    backend.invalidate_fact(invalidated_target.id, status=FactStatus.INVALIDATED, note="stale")

    embed = _StaticEmbedding()
    embed.add("seed", [1.0, 0.0, 0.0, 0.0])
    embed.add("seed body content", [1.0, 0.0, 0.0, 0.0])

    injector = PassiveMemoryInjector(
        embedding=embed,
        factual_memory=backend,
        state_store=InMemoryStateStore(),
        top_k_similarity=1,
        min_similarity_threshold=0.5,
        associative_expand=True,
    )
    surfaced = injector.surface_for_context("seed")
    ids = {s.item.id for s in surfaced}
    assert ids == {seed.id}, "DISPUTED/INVALIDATED neighbors must be filtered out"


def test_surface_for_context_returns_high_similarity_match():
    backend = InMemoryBackend()
    backend.add_fact(FactRecord(content="real fact body", source="t"))

    embed = _StaticEmbedding()
    embed.add("real", [1.0, 0.0, 0.0, 0.0])
    embed.add("real fact body", [1.0, 0.0, 0.0, 0.0])

    injector = PassiveMemoryInjector(
        embedding=embed,
        factual_memory=backend,
        state_store=InMemoryStateStore(),
        associative_expand=False,
    )
    surfaced = injector.surface_for_context("real")
    assert len(surfaced) == 1


def test_surface_for_context_works_with_bm25_embedding_adapter():
    """Regression: the real zero-dependency embedding adapter must fit the injector."""
    backend = InMemoryBackend()
    fact = backend.add_fact(
        FactRecord(
            content="deployment rollback playbook prevents repeated outage",
            source="runbook",
        )
    )
    backend.add_fact(FactRecord(content="identity narrative review cadence", source="notes"))

    injector = PassiveMemoryInjector(
        embedding=BM25EmbeddingAdapter(dimension=64),
        factual_memory=backend,
        state_store=InMemoryStateStore(),
        top_k_similarity=1,
        associative_expand=False,
        min_similarity_threshold=0.1,
    )

    surfaced = injector.surface_for_context("deployment rollback")

    assert len(surfaced) == 1
    assert surfaced[0].item.id == fact.id
    assert surfaced[0].source == "similarity"
    assert surfaced[0].score > 0.0


def test_surface_experiences_returns_empty_when_no_experiences():
    injector = PassiveMemoryInjector(
        embedding=MockEmbeddingAdapter(),
        factual_memory=InMemoryBackend(),
        state_store=InMemoryStateStore(),
    )
    assert injector.surface_experiences("query") == []


def test_surface_experiences_returns_top_matches():
    store = InMemoryStateStore()
    matching, m1 = _experience(what_happened="matching event")
    other, m2 = _experience(what_happened="unrelated event")
    _save_experience(store, matching, m1)
    _save_experience(store, other, m2)

    embed = _StaticEmbedding()
    embed.add("query", [1.0, 0.0, 0.0, 0.0])
    embed.add("matching event", [0.95, 0.05, 0.0, 0.0])
    embed.add("unrelated event", [0.0, 1.0, 0.0, 0.0])

    injector = PassiveMemoryInjector(
        embedding=embed,
        factual_memory=InMemoryBackend(),
        state_store=store,
        min_similarity_threshold=0.3,
    )
    surfaced = injector.surface_experiences("query", limit=1)
    assert len(surfaced) == 1
    assert surfaced[0].item.id == matching.id


def test_surface_experiences_skips_cached_experiences():
    store = InMemoryStateStore()
    exp, moment = _experience(what_happened="meaningful event")
    _save_experience(store, exp, moment)

    embed = _StaticEmbedding()
    embed.add("query", [1.0, 0.0, 0.0, 0.0])
    embed.add("meaningful event", [1.0, 0.0, 0.0, 0.0])

    wm = SessionWorkingMemory()
    wm.add_experience(exp)
    injector = PassiveMemoryInjector(
        embedding=embed,
        factual_memory=InMemoryBackend(),
        state_store=store,
    )
    assert injector.surface_experiences("query", working_memory=wm) == []


def test_surface_for_context_uses_lookback_window_in_state_store():
    """List_recent_experiences should hand back records ordered by recency."""
    store = InMemoryStateStore()
    older, mo = _experience(
        what_happened="older",
        timestamp=datetime.now(UTC) - timedelta(days=2),
    )
    newer, mn = _experience(
        what_happened="newer",
        timestamp=datetime.now(UTC) - timedelta(hours=1),
    )
    _save_experience(store, older, mo)
    _save_experience(store, newer, mn)

    records = store.list_recent_experiences(limit=2)
    assert [r.experience.id for r in records] == [newer.id, older.id]
