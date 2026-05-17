"""
PassiveMemoryInjector - automatic memory surfacing.

Surfaces relevant facts and experiences automatically based on:
1. Embedding similarity (top-K semantic search)
2. Optional BM25 lexical signal fused with embedding via Reciprocal Rank Fusion
3. Optional cross-encoder reranking (when reranker is configured)
4. 1-hop associative graph expansion (related facts via relations)

When LinguisticAnalyzer + MemoryReranker are provided (LINGUISTIC_ENABLED=True),
uses ambient-anchor mode: parallel queries per entity/anchor type, then reranking.
"""

from dataclasses import dataclass, field
from uuid import UUID

from atman.core.models import FactRecord, KeyMoment, SessionExperience
from atman.core.models.fact import FactStatus
from atman.core.ports import EmbeddingPort, FactualMemory
from atman.core.ports.state_store import StateStore
from atman.core.services.session_working_memory import SessionWorkingMemory

RRF_K = 60


@dataclass
class SurfacedMemory:
    """A memory item surfaced by the injector."""

    item: FactRecord | SessionExperience | KeyMoment
    source: str  # "similarity" or "associative" or "dense" or "ambient_rerank"
    score: float  # relevance score


@dataclass
class RagContext:
    """Result of token-budget-capped RAG selection."""

    items: list[SurfacedMemory] = field(default_factory=list)
    tokens_used: int = 0


def estimate_tokens(text: str) -> int:
    """Token count heuristic. UTF-8 byte length / 3 — calibrated to work
    reasonably for both ASCII (~1 token per 4 chars) and multibyte scripts
    like Cyrillic where each char is ~2 bytes and tokenizes more densely."""
    return max(1, len(text.encode("utf-8")) // 3) if text else 0


def _surfaced_text(mem: SurfacedMemory) -> str:
    """Return the primary text of a surfaced memory item for token estimation."""
    item = mem.item
    if isinstance(item, FactRecord):
        return item.content
    if isinstance(item, KeyMoment):
        return f"{item.what_happened} {item.why_it_matters}"
    if isinstance(item, SessionExperience):
        return getattr(item, "agent_recap", "") or ""
    return ""


def build_rag_context(
    candidates: list[SurfacedMemory],
    budget: int = 2000,
) -> RagContext:
    """
    Select candidates within a token budget, highest-scored first.

    Candidates are assumed to be pre-sorted by descending score.
    Stops as soon as adding the next candidate would exceed the budget.
    """
    result: list[SurfacedMemory] = []
    spent = 0
    for candidate in candidates:
        t = estimate_tokens(_surfaced_text(candidate))
        if spent + t > budget:
            break
        result.append(candidate)
        spent += t
    return RagContext(items=result, tokens_used=spent)


class PassiveMemoryInjector:
    """
    Automatic memory surfacing system.

    Combines embedding-based similarity search with associative
    graph expansion to surface relevant context without explicit queries.
    """

    def __init__(
        self,
        embedding: EmbeddingPort,
        factual_memory: FactualMemory,
        state_store: StateStore,
        top_k_similarity: int = 5,
        associative_expand: bool = True,
        min_similarity_threshold: float = 0.3,
        *,
        linguistic_analyzer: object | None = None,
        memory_reranker: object | None = None,
        ambient_top_k: int = 50,
        reranker_top_n: int = 10,
        bm25: EmbeddingPort | None = None,
        candidate_pool_size: int = 0,
    ) -> None:
        self.embedding = embedding
        self.factual_memory = factual_memory
        self.state_store = state_store
        self.top_k = top_k_similarity
        self.associative_expand = associative_expand
        self.min_threshold = min_similarity_threshold
        self._linguistic_analyzer = linguistic_analyzer
        self._reranker = memory_reranker
        self._ambient_top_k = ambient_top_k
        self._reranker_top_n = reranker_top_n
        self._bm25 = bm25
        self._candidate_pool_size = candidate_pool_size

    @property
    def candidate_pool_size(self) -> int:
        """How many candidates to pull from backend before embedding scoring.

        Larger pool = better recall but slower (each candidate gets embedded).
        Defaults to ``max(top_k * 10, 50)`` so that with default top_k=5
        we sample 50 facts by salience and let embedding/BM25 select the best.
        """
        return self._candidate_pool_size or max(self.top_k * 10, 50)

    @property
    def _ambient_mode(self) -> bool:
        """True when both LA and reranker are configured."""
        return self._linguistic_analyzer is not None and self._reranker is not None

    def surface_key_moments_for_context(
        self,
        context_text: str,
        *,
        limit: int = 10,
    ) -> list[SurfacedMemory]:
        """
        Surface relevant key moments (v2 API — uses state_store.list_key_moments).

        Falls back to dense embedding search on what_happened text.
        In ambient mode, uses entity anchors + reranker.
        """
        from atman.core.ports.memory_reranker import SurfacedMemory as RankedMemory

        query_embedding = self.embedding.embed(context_text)
        all_moments = self.state_store.list_key_moments()
        # Build a quick lookup so we can return the actual KeyMoment objects rather
        # than wrapping the text in a FactRecord (which would conflate types for
        # downstream isinstance checks).
        moment_by_id: dict[UUID, KeyMoment] = {m.id: m for m in all_moments}
        candidates: list[RankedMemory] = []

        for moment in all_moments:
            if not moment.what_happened.strip():
                continue
            if not moment.salience or moment.salience < 0.01:
                continue
            mom_embedding = self.embedding.embed(moment.what_happened)
            score = self.embedding.similarity(query_embedding, mom_embedding)
            if score >= self.min_threshold:
                candidates.append(
                    RankedMemory(
                        key_moment_id=moment.id,
                        text=moment.what_happened,
                        score=float(score),
                        source="dense",
                    )
                )

        if self._ambient_mode and candidates:
            ranked = self._reranker.rerank(context_text, candidates, top_n=limit)  # type: ignore[union-attr]
        else:
            ranked = sorted(candidates, key=lambda c: c.score, reverse=True)[:limit]

        return [
            SurfacedMemory(
                item=moment_by_id[r.key_moment_id],
                source=r.source,
                # Use `is not None` rather than `or` so a legitimate 0.0
                # reranker score is not silently overridden by retrieval score.
                score=r.final_score if r.final_score is not None else r.score,
            )
            for r in ranked
            if r.key_moment_id in moment_by_id
        ]

    def surface_for_context(
        self,
        context_text: str,
        working_memory: SessionWorkingMemory | None = None,
    ) -> list[SurfacedMemory]:
        """
        Surface relevant memories for given context.

        Pipeline:
        1. Pull candidate pool from backend ordered by salience
           (``query=None`` — substring filter is bypassed; semantic ranking
           is the service's responsibility).
        2. Score each candidate by dense embedding similarity.
        3. If BM25 adapter is configured, score by BM25 as well and fuse
           with embedding via Reciprocal Rank Fusion.
        4. If ambient mode is enabled (linguistic analyzer + reranker),
           rerank the top candidates via the cross-encoder.
        5. Expand 1-hop via associative graph; associative items get
           a real embedding similarity score, not a hardcoded constant.
        """
        surfaced: list[SurfacedMemory] = []
        seen_ids: set[UUID] = set()

        query_embedding = self.embedding.embed(context_text)

        candidate_facts = self.factual_memory.search(
            query=None,
            limit=self.candidate_pool_size,
            include_invalidated=False,
        )

        # Embedding scoring + working-memory dedup + empty-content skip.
        # Use embed_batch so remote adapters (Ollama, flag) make one round-trip
        # instead of one per fact.
        eligible: list[FactRecord] = [
            fact
            for fact in candidate_facts
            if fact.content.strip() and not (working_memory and working_memory.has(fact.id))
        ]
        scored_facts: list[tuple[FactRecord, float]] = []
        if eligible:
            batch_embeddings = self.embedding.embed_batch([f.content for f in eligible])
            for fact, fact_embedding in zip(eligible, batch_embeddings, strict=True):
                score = self.embedding.similarity(query_embedding, fact_embedding)
                if score >= self.min_threshold:
                    scored_facts.append((fact, float(score)))

        if not scored_facts:
            return surfaced

        # Optional BM25 RRF fusion — lifts exact lexical matches that the
        # dense encoder might rank low, without dropping semantic matches.
        ordered = self._fuse_with_bm25(context_text, scored_facts)

        # Optional cross-encoder reranking (ambient mode).
        ordered = self._apply_reranker(context_text, ordered)

        for fact, score in ordered[: self.top_k]:
            surfaced.append(SurfacedMemory(item=fact, source="similarity", score=score))
            seen_ids.add(fact.id)
            if working_memory:
                working_memory.add_fact(fact)

        # Associative graph expansion (1-hop) — score by real embedding
        # similarity, capped at 0.5 so associative items never outrank a
        # direct semantic match.
        if self.associative_expand:
            related_facts = self._associative_expand(seen_ids)
            for fact in related_facts:
                if fact.id in seen_ids or not fact.content.strip():
                    continue
                rel_embedding = self.embedding.embed(fact.content)
                rel_score = float(self.embedding.similarity(query_embedding, rel_embedding))
                surfaced.append(
                    SurfacedMemory(item=fact, source="associative", score=min(rel_score, 0.5))
                )
                seen_ids.add(fact.id)
                if working_memory:
                    working_memory.add_fact(fact)

        return surfaced

    def _fuse_with_bm25(
        self,
        context_text: str,
        scored_facts: list[tuple[FactRecord, float]],
    ) -> list[tuple[FactRecord, float]]:
        """Reciprocal Rank Fusion of embedding ranks and BM25 ranks.

        Returns scored_facts sorted by fused score. Embedding scores are
        preserved on the tuples for downstream use; only ordering changes.
        When ``self._bm25`` is None, falls back to plain embedding sort.
        """
        if self._bm25 is None:
            return sorted(scored_facts, key=lambda x: x[1], reverse=True)

        bm25_qvec = self._bm25.embed(context_text)
        facts_only = [f for f, _ in scored_facts]
        bm25_vecs = self._bm25.embed_batch([f.content for f in facts_only])
        bm25_scores: dict[UUID, float] = {
            fact.id: float(self._bm25.similarity(bm25_qvec, vec))
            for fact, vec in zip(facts_only, bm25_vecs, strict=True)
        }

        emb_sorted = sorted(scored_facts, key=lambda x: x[1], reverse=True)
        bm25_sorted = sorted(bm25_scores.items(), key=lambda x: x[1], reverse=True)
        emb_rank = {f.id: i for i, (f, _) in enumerate(emb_sorted)}
        bm25_rank = {fid: i for i, (fid, _) in enumerate(bm25_sorted)}
        missing = len(scored_facts)

        def rrf(fid: UUID) -> float:
            return 1.0 / (RRF_K + emb_rank.get(fid, missing)) + 1.0 / (
                RRF_K + bm25_rank.get(fid, missing)
            )

        return sorted(scored_facts, key=lambda x: rrf(x[0].id), reverse=True)

    def _apply_reranker(
        self,
        context_text: str,
        scored_facts: list[tuple[FactRecord, float]],
    ) -> list[tuple[FactRecord, float]]:
        """Cross-encoder reranking of the top candidates.

        Only runs when ambient mode is enabled. Reranker operates on the
        top ``reranker_top_n`` so cost stays bounded.
        """
        if not (self._ambient_mode and scored_facts):
            return scored_facts

        from atman.core.ports.memory_reranker import SurfacedMemory as RankedMemory

        head = scored_facts[: self._reranker_top_n]
        tail = scored_facts[self._reranker_top_n :]
        ranked_input = [
            RankedMemory(
                key_moment_id=fact.id,
                text=fact.content,
                score=score,
                source="similarity",
            )
            for fact, score in head
        ]
        ranked = self._reranker.rerank(  # type: ignore[union-attr]
            context_text, ranked_input, top_n=len(ranked_input)
        )
        fact_by_id = {f.id: f for f, _ in head}
        reordered: list[tuple[FactRecord, float]] = []
        for r in ranked:
            fact = fact_by_id.get(r.key_moment_id)
            if fact is None:
                continue
            new_score = r.final_score if r.final_score is not None else r.score
            reordered.append((fact, float(new_score)))
        return reordered + tail

    def _associative_expand(self, seed_fact_ids: set[UUID]) -> list[FactRecord]:
        """
        Expand 1-hop from seed facts via relations.

        Args:
            seed_fact_ids: Starting fact IDs

        Returns:
            list[FactRecord]: Related facts via graph edges
        """
        related: list[FactRecord] = []

        for fact_id in seed_fact_ids:
            fact = self.factual_memory.get_fact(fact_id)
            if not fact:
                continue

            for relation in fact.relations:
                related_fact = self.factual_memory.get_fact(relation.target_id)
                if related_fact and related_fact.status == FactStatus.ACTIVE:
                    related.append(related_fact)

        # Deduplicate
        seen: set[UUID] = set()
        unique_related: list[FactRecord] = []
        for fact in related:
            if fact.id not in seen:
                unique_related.append(fact)
                seen.add(fact.id)

        return unique_related

    def surface_experiences(
        self,
        context_text: str,
        limit: int = 3,
        working_memory: SessionWorkingMemory | None = None,
    ) -> list[SurfacedMemory]:
        """
        Surface relevant past experiences.

        Args:
            context_text: Current context text
            limit: Maximum experiences to surface
            working_memory: Optional cache

        Returns:
            list[SurfacedMemory]: Surfaced experiences
        """
        surfaced: list[SurfacedMemory] = []

        # Query experiences via state_store. ExperienceQuery is a marker base
        # class (no constructor args); pull a candidate window via the
        # ``limit`` kwarg of search_experiences and rerank by embedding
        # similarity below.
        experience_records = self.state_store.search_experiences(limit=limit * 2)

        # Score by embedding similarity
        query_embedding = self.embedding.embed(context_text)

        scored: list[tuple[SessionExperience, float]] = []
        for record in experience_records:
            exp = record.experience
            if working_memory and working_memory.has(exp.id):
                continue

            # Create text representation for embedding
            # Fetch key moments and concatenate their content
            moment_texts = []
            for moment_id in exp.key_moment_ids:
                moment = self.state_store.get_key_moment(moment_id)
                if moment:
                    moment_texts.append(moment.what_happened)
            exp_text = " ".join(moment_texts)
            if not exp_text.strip():
                continue

            exp_embedding = self.embedding.embed(exp_text)
            score = self.embedding.similarity(query_embedding, exp_embedding)

            if score >= self.min_threshold:
                scored.append((exp, score))

        # Sort and return top results
        scored.sort(key=lambda x: x[1], reverse=True)
        for exp, score in scored[:limit]:
            surfaced.append(SurfacedMemory(item=exp, source="similarity", score=score))
            if working_memory:
                working_memory.add_experience(exp)

        return surfaced
