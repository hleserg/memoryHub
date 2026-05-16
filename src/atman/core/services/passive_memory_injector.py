"""
PassiveMemoryInjector - automatic memory surfacing.

Surfaces relevant facts and experiences automatically based on:
1. Embedding similarity (top-K semantic search)
2. 1-hop associative graph expansion (related facts via relations)

When LinguisticAnalyzer + MemoryReranker are provided (LINGUISTIC_ENABLED=True),
uses ambient-anchor mode: parallel queries per entity/anchor type, then reranking.
"""

from dataclasses import dataclass
from uuid import UUID

from atman.core.models import FactRecord, KeyMoment, SessionExperience
from atman.core.models.fact import FactStatus
from atman.core.ports import EmbeddingPort, FactualMemory
from atman.core.ports.state_store import StateStore
from atman.core.services.session_working_memory import SessionWorkingMemory


@dataclass
class SurfacedMemory:
    """A memory item surfaced by the injector."""

    item: FactRecord | SessionExperience | KeyMoment
    source: str  # "similarity" or "associative" or "dense" or "ambient_rerank"
    score: float  # relevance score


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
                score=r.final_score or r.score,
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

        Args:
            context_text: The current context/situation text
            working_memory: Optional cache to avoid re-surfacing

        Returns:
            list[SurfacedMemory]: Surfaced relevant memories
        """
        surfaced: list[SurfacedMemory] = []
        seen_ids: set[UUID] = set()

        # 1. Embedding similarity search for facts
        query_embedding = self.embedding.embed(context_text)

        # Get candidate facts
        candidate_facts = self.factual_memory.search(
            query=context_text, limit=self.top_k * 2, include_invalidated=False
        )

        # Score by embedding similarity
        scored_facts: list[tuple[FactRecord, float]] = []
        for fact in candidate_facts:
            if not fact.content.strip():
                continue

            # Check working memory
            if working_memory and working_memory.has(fact.id):
                continue

            fact_embedding = self.embedding.embed(fact.content)
            score = self.embedding.similarity(query_embedding, fact_embedding)

            if score >= self.min_threshold:
                scored_facts.append((fact, score))

        # Sort by score and take top_k
        scored_facts.sort(key=lambda x: x[1], reverse=True)
        for fact, score in scored_facts[: self.top_k]:
            surfaced.append(SurfacedMemory(item=fact, source="similarity", score=score))
            seen_ids.add(fact.id)

            # Add to working memory if provided
            if working_memory:
                working_memory.add_fact(fact)

        # 2. Associative graph expansion (1-hop)
        if self.associative_expand:
            related_facts = self._associative_expand(seen_ids)
            for fact in related_facts:
                if fact.id not in seen_ids:
                    surfaced.append(SurfacedMemory(item=fact, source="associative", score=0.5))
                    seen_ids.add(fact.id)

                    if working_memory:
                        working_memory.add_fact(fact)

        return surfaced

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
