"""NoOp MemoryReranker — passes candidates through sorted by original score."""

from typing_extensions import override

from atman.core.ports.memory_reranker import MemoryReranker, SurfacedMemory


class NoOpReranker(MemoryReranker):
    """MemoryReranker that assigns final_score = score and returns top_n by score DESC.

    No cross-encoder or LLM call is made.  Useful when reranking infrastructure
    is not available or is disabled, while still satisfying the port contract
    (all returned candidates carry a populated final_score).
    """

    @override
    def rerank(
        self,
        query: str,
        candidates: list[SurfacedMemory],
        *,
        top_n: int = 10,
    ) -> list[SurfacedMemory]:
        """Return top_n candidates with final_score set to their original score.

        Candidates are sorted by score DESC.  Because SurfacedMemory is frozen,
        new instances are created with final_score populated.
        """
        scored = [
            SurfacedMemory(
                key_moment_id=c.key_moment_id,
                text=c.text,
                score=c.score,
                final_score=c.score,
                source=c.source,
            )
            for c in candidates
        ]
        scored.sort(key=lambda m: m.final_score or 0.0, reverse=True)
        return scored[:top_n]
