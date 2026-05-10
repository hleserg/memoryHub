"""
PassiveMemoryInjector - automatic memory surfacing.

Surfaces relevant facts and experiences automatically based on:
1. Embedding similarity (top-K semantic search)
2. 1-hop associative graph expansion (related facts via relations)
"""

from dataclasses import dataclass
from uuid import UUID

from atman.core.models import FactRecord, SessionExperience
from atman.core.ports import EmbeddingPort, FactualMemory
from atman.core.ports.state_store import StateStore
from atman.core.services.session_working_memory import SessionWorkingMemory


@dataclass
class SurfacedMemory:
    """A memory item surfaced by the injector."""

    item: FactRecord | SessionExperience
    source: str  # "similarity" or "associative"
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
    ) -> None:
        """
        Initialize passive memory injector.

        Args:
            embedding: Embedding provider for similarity search
            factual_memory: Factual memory storage
            state_store: State store for experiences
            top_k_similarity: Number of top similar items to surface
            associative_expand: Whether to do 1-hop graph expansion
            min_similarity_threshold: Minimum similarity score to include
        """
        self.embedding = embedding
        self.factual_memory = factual_memory
        self.state_store = state_store
        self.top_k = top_k_similarity
        self.associative_expand = associative_expand
        self.min_threshold = min_similarity_threshold

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
                if related_fact and related_fact.status.value == "active":
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

        # Query experiences via state_store
        # Get recent experiences and filter by embedding similarity
        from atman.core.ports.state_store import ExperienceQuery

        query = ExperienceQuery(limit=limit * 2)
        experience_records = self.state_store.search_experiences(query)

        # Score by embedding similarity
        query_embedding = self.embedding.embed(context_text)

        scored: list[tuple[SessionExperience, float]] = []
        for record in experience_records:
            exp = record.experience
            if working_memory and working_memory.has(exp.id):
                continue

            # Create text representation for embedding
            exp_text = " ".join(km.what_happened for km in exp.key_moments)
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
