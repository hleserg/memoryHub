"""Port: MemoryReranker — rerank retrieved memory candidates by relevance to query."""

from abc import ABC, abstractmethod
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SurfacedMemory(BaseModel):
    """A single memory candidate surfaced by retrieval, ready for reranking."""

    model_config = ConfigDict(frozen=True)

    key_moment_id: UUID
    text: str = Field(description="what_happened content used for relevance scoring")
    score: float = Field(
        ge=0.0,
        le=1.0,
        description="Retrieval score assigned before reranking",
    )
    final_score: float | None = Field(
        default=None,
        description="Score assigned by the reranker; None until rerank() is called",
    )
    source: str = Field(
        description="dense | entity_join | time_ref | alias_match | fallback"
    )


class MemoryReranker(ABC):
    """Hexagonal port for cross-encoder or LLM-based reranking of memory candidates."""

    @abstractmethod
    def rerank(
        self,
        query: str,
        candidates: list[SurfacedMemory],
        *,
        top_n: int = 10,
    ) -> list[SurfacedMemory]:
        """Return top_n candidates sorted by final_score DESC.

        Implementations MUST set final_score on every candidate they return.
        Candidates beyond top_n are discarded.  If len(candidates) <= top_n, all
        candidates are returned (still sorted and scored).

        The input list is not mutated; new SurfacedMemory instances with
        final_score populated are returned.
        """
