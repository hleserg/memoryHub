"""Tests for PassiveMemoryInjector (E24.6, E24.8)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from atman.adapters.memory.bm25_embedding import BM25EmbeddingAdapter
from atman.adapters.memory.in_memory_backend import InMemoryBackend
from atman.adapters.memory.mock_embedding import MockEmbeddingAdapter
from atman.adapters.storage.in_memory_state_store import InMemoryStateStore
from atman.core.models import KeyMoment, SessionExperience
from atman.core.models.experience import EmotionalDepth, ExperienceRecord, FeltSense
from atman.core.models.fact import FactRecord, FactStatus, Relation
from atman.core.services.passive_memory_injector import (
    PassiveMemoryInjector,
    SurfacedMemoryItem,
    _surfaced_text,
    build_rag_context,
    estimate_tokens,
)
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
    # The service now passes query=None to the backend so the substring
    # filter is bypassed; every candidate is scored by embedding similarity
    # and only those above min_similarity_threshold are kept.
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


# ---------------------------------------------------------------------------
# Tests for build_rag_context, estimate_tokens, _surfaced_text
# ---------------------------------------------------------------------------


def _fact(content: str = "hello world") -> FactRecord:
    return FactRecord(content=content, source="test", status=FactStatus.ACTIVE)


def _key_moment(what: str = "something", why: str = "matters") -> KeyMoment:
    return KeyMoment(
        what_happened=what,
        when=datetime.now(UTC),
        how_i_felt=FeltSense(
            emotional_valence=0.0,
            emotional_intensity=0.5,
            depth=EmotionalDepth.MEANINGFUL,
        ),
        why_it_matters=why,
    )


def _surfaced(item, score: float = 1.0, source: str = "similarity") -> SurfacedMemoryItem:
    return SurfacedMemoryItem(item=item, source=source, score=score)


def test_estimate_tokens_basic():
    # UTF-8 byte-length / 3 — ASCII characters are 1 byte each, so "abcd"
    # is 4 bytes → max(1, 4//3) = 1; empty string → 0.
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("") == 0
    assert estimate_tokens("a" * 400) == 133


def test_estimate_tokens_cyrillic_density():
    """Cyrillic chars take ~2 bytes each in UTF-8, so the estimate should
    be ~2x higher than a same-length ASCII string. This calibration matters
    because LLM tokenizers split Cyrillic into more tokens per char than
    English."""
    ascii_estimate = estimate_tokens("a" * 100)
    cyrillic_estimate = estimate_tokens("а" * 100)
    assert cyrillic_estimate > ascii_estimate
    assert cyrillic_estimate >= 2 * ascii_estimate - 1


def test_surfaced_text_fact():
    f = _fact("Paris is the capital of France")
    assert _surfaced_text(_surfaced(f)) == "Paris is the capital of France"


def test_surfaced_text_key_moment():
    km = _key_moment(what="I helped someone", why="it felt meaningful")
    text = _surfaced_text(_surfaced(km))
    assert "I helped someone" in text
    assert "it felt meaningful" in text


def test_surfaced_text_session_experience_uses_agent_recap():
    exp = SessionExperience(
        session_id=uuid4(),
        key_moment_ids=[uuid4()],
        avg_emotional_intensity=0.5,
        has_profound_moment=False,
        agent_recap="A productive session",
    )
    mem = _surfaced(exp)
    assert _surfaced_text(mem) == "A productive session"


def test_surfaced_text_session_experience_none_recap():
    exp = SessionExperience(
        session_id=uuid4(),
        key_moment_ids=[uuid4()],
        avg_emotional_intensity=0.5,
        has_profound_moment=False,
        agent_recap=None,
    )
    assert _surfaced_text(_surfaced(exp)) == ""


def test_build_rag_context_empty():
    ctx = build_rag_context([], budget=1000)
    assert ctx.items == []
    assert ctx.tokens_used == 0


def test_build_rag_context_fits_within_budget():
    # Each fact is 4 chars = 1 token; budget is 3 tokens
    items = [_surfaced(_fact("abcd")) for _ in range(5)]
    ctx = build_rag_context(items, budget=3)
    assert len(ctx.items) == 3
    assert ctx.tokens_used == 3


def test_build_rag_context_stops_before_overflow():
    small = _surfaced(_fact("a" * 4))  # 1 token
    large = _surfaced(_fact("b" * 400))  # 100 tokens
    ctx = build_rag_context([small, large], budget=50)
    assert ctx.items == [small]
    assert ctx.tokens_used == 1


def test_build_rag_context_all_fit():
    items = [_surfaced(_fact("abcd")) for _ in range(3)]
    ctx = build_rag_context(items, budget=10)
    assert len(ctx.items) == 3


# ---------------------------------------------------------------------------
# Audit-driven regression tests: semantic recall, BM25 fusion, reranker
# ---------------------------------------------------------------------------


def test_surface_for_context_recalls_semantic_match_without_substring():
    """The key audit scenario: a fact phrased in synonyms must still surface.

    Backend would previously drop the fact because the query "расстроен" is
    not a substring of "тревогу и подавленность". After Fix 1.1 (query=None
    in the backend call) the embedding scorer sees every active fact and
    can rank by semantic similarity.
    """
    backend = InMemoryBackend()
    target = backend.add_fact(
        FactRecord(content="агент заметил тревогу и подавленность", source="t")
    )
    backend.add_fact(FactRecord(content="разговор о погоде", source="t"))
    backend.add_fact(FactRecord(content="обсуждение технических проблем", source="t"))

    embed = _StaticEmbedding()
    embed.add("расстроен", [1.0, 0.0, 0.0, 0.0])
    embed.add("агент заметил тревогу и подавленность", [0.9, 0.1, 0.0, 0.0])
    embed.add("разговор о погоде", [0.0, 1.0, 0.0, 0.0])
    embed.add("обсуждение технических проблем", [0.0, 0.0, 1.0, 0.0])

    injector = PassiveMemoryInjector(
        embedding=embed,
        factual_memory=backend,
        state_store=InMemoryStateStore(),
        top_k_similarity=1,
        min_similarity_threshold=0.3,
        associative_expand=False,
    )
    surfaced = injector.surface_for_context("расстроен")
    assert len(surfaced) == 1
    assert surfaced[0].item.id == target.id


def test_surface_for_context_respects_candidate_pool_size():
    """With many low-salience facts and one high-salience semantic match,
    the candidate pool must include the salient one because backend now
    sorts by salience DESC before applying the limit."""
    backend = InMemoryBackend()
    # 60 noisy facts with low salience
    for i in range(60):
        backend.add_fact(FactRecord(content=f"noise fact {i}", source="t", salience=0.1))
    # The high-salience target lands in the pool because backend sorts by salience
    target = backend.add_fact(FactRecord(content="important target fact", source="t", salience=0.9))

    embed = _StaticEmbedding()
    embed.add("target", [1.0, 0.0, 0.0, 0.0])
    embed.add("important target fact", [1.0, 0.0, 0.0, 0.0])
    for i in range(60):
        embed.add(f"noise fact {i}", [0.0, 1.0, 0.0, 0.0])

    injector = PassiveMemoryInjector(
        embedding=embed,
        factual_memory=backend,
        state_store=InMemoryStateStore(),
        top_k_similarity=1,
        min_similarity_threshold=0.3,
        associative_expand=False,
        candidate_pool_size=50,
    )
    surfaced = injector.surface_for_context("target")
    assert len(surfaced) == 1
    assert surfaced[0].item.id == target.id


def test_surface_for_context_bm25_rrf_lifts_exact_lexical_match():
    """RRF fusion boosts a candidate that matches lexically even when its
    dense embedding rank is mediocre. Without BM25 the dense scorer alone
    would pick the embedding-best candidate; with BM25 RRF, the exact
    lexical match wins because it ranks #1 on the BM25 side."""
    backend = InMemoryBackend()
    lexical = backend.add_fact(FactRecord(content="deployment rollback playbook", source="t"))
    dense_near = backend.add_fact(FactRecord(content="release reversion guide", source="t"))

    embed = _StaticEmbedding()
    # The dense encoder considers "release reversion guide" slightly closer
    # to the query than the exact lexical match.
    embed.add("deployment rollback", [1.0, 0.0, 0.0, 0.0])
    embed.add("deployment rollback playbook", [0.6, 0.4, 0.0, 0.0])
    embed.add("release reversion guide", [0.7, 0.3, 0.0, 0.0])

    bm25 = BM25EmbeddingAdapter(dimension=128)

    injector = PassiveMemoryInjector(
        embedding=embed,
        factual_memory=backend,
        state_store=InMemoryStateStore(),
        top_k_similarity=1,
        min_similarity_threshold=0.3,
        associative_expand=False,
        bm25=bm25,
    )
    surfaced = injector.surface_for_context("deployment rollback")
    assert len(surfaced) == 1
    # BM25 promotes the exact lexical match over the dense-near candidate
    assert surfaced[0].item.id == lexical.id
    # Sanity: without BM25, the dense-near candidate would have won
    injector_no_bm25 = PassiveMemoryInjector(
        embedding=embed,
        factual_memory=backend,
        state_store=InMemoryStateStore(),
        top_k_similarity=1,
        min_similarity_threshold=0.3,
        associative_expand=False,
    )
    surfaced_no_bm25 = injector_no_bm25.surface_for_context("deployment rollback")
    assert surfaced_no_bm25[0].item.id == dense_near.id


def test_surface_for_context_applies_reranker_in_ambient_mode():
    """When both linguistic_analyzer and memory_reranker are wired, the
    reranker reorders the top candidates and the final_score reaches the
    SurfacedMemoryItem output."""
    from atman.core.ports.memory_reranker import MemoryReranker

    backend = InMemoryBackend()
    a = backend.add_fact(FactRecord(content="alpha doc body", source="t"))
    b = backend.add_fact(FactRecord(content="beta doc body", source="t"))

    embed = _StaticEmbedding()
    embed.add("query", [1.0, 0.0, 0.0, 0.0])
    # Dense order: alpha (0.9) > beta (0.6)
    embed.add("alpha doc body", [0.9, 0.4, 0.0, 0.0])
    embed.add("beta doc body", [0.6, 0.8, 0.0, 0.0])

    class _ReverseReranker(MemoryReranker):
        """Trivial reranker: assigns final_score that reverses the order."""

        def rerank(self, query, candidates, *, top_n=10):
            reordered = sorted(candidates, key=lambda c: c.score)
            return [
                c.model_copy(update={"final_score": 0.99 - 0.1 * i})
                for i, c in enumerate(reordered[:top_n])
            ]

    injector = PassiveMemoryInjector(
        embedding=embed,
        factual_memory=backend,
        state_store=InMemoryStateStore(),
        top_k_similarity=2,
        min_similarity_threshold=0.3,
        associative_expand=False,
        linguistic_analyzer=object(),  # any non-None enables ambient mode
        memory_reranker=_ReverseReranker(),
    )
    surfaced = injector.surface_for_context("query")
    assert len(surfaced) == 2
    # Reranker inverted dense order: beta (lower dense) now ranks first
    assert surfaced[0].item.id == b.id
    assert surfaced[1].item.id == a.id
    # final_score from reranker propagates to the SurfacedMemoryItem
    assert surfaced[0].score == pytest.approx(0.99, abs=1e-6)


def test_surface_for_context_associative_score_is_embedding_based():
    """Associative-expansion candidates must get a real embedding similarity
    score (capped at 0.5) so a weakly-related neighbor cannot outrank a
    semantically strong direct match in downstream sorts."""
    backend = InMemoryBackend()
    weak_target = backend.add_fact(FactRecord(content="weakly related target", source="t"))
    backend.add_fact(
        FactRecord(
            content="seed body content",
            source="t",
            relations=[Relation(target_id=weak_target.id, relation_type="related_to")],
        )
    )

    embed = _StaticEmbedding()
    embed.add("seed", [1.0, 0.0, 0.0, 0.0])
    embed.add("seed body content", [1.0, 0.0, 0.0, 0.0])
    # Target shares almost no dimension with the query.
    embed.add("weakly related target", [0.1, 0.9, 0.0, 0.0])

    injector = PassiveMemoryInjector(
        embedding=embed,
        factual_memory=backend,
        state_store=InMemoryStateStore(),
        top_k_similarity=1,
        min_similarity_threshold=0.5,
        associative_expand=True,
    )
    surfaced = injector.surface_for_context("seed")
    associative = [s for s in surfaced if s.source == "associative"]
    assert len(associative) == 1
    # Score is the real embedding similarity (~0.1), not the legacy 0.5 stub.
    assert associative[0].score <= 0.5
    assert associative[0].score == pytest.approx(0.1, abs=1e-6)
