"""
MockEmbeddingAdapter - deterministic embedding for CI/testing.

Produces consistent, reproducible embeddings based on text content hash.
No external dependencies required.
"""

import math
from typing import override

from atman.core.ports.embedding import EmbeddingPort


class MockEmbeddingAdapter(EmbeddingPort):
    """
    Deterministic embedding adapter for testing.

    Generates embeddings based on text hash, ensuring:
    - Same text always produces same embedding
    - Different texts produce different embeddings
    - No external services required

    Uses 768-dimensional vectors to match qwen3-embedding:1.5b dimensions.
    """

    _DIMENSION = 768
    _MODEL_NAME = "mock-embedding:768d"

    @override
    def embed(self, text: str) -> list[float]:
        """Generate deterministic embedding from text hash.

        Uses hash(text) % 2^31 as seed for deterministic pseudo-random generation.
        """
        # Use hash modulo 2^31 as seed (per E25 spec)
        seed = hash(text) % (2**31)

        # Generate embedding values using deterministic pseudo-random sequence
        embedding: list[float] = []
        for _i in range(self._DIMENSION):
            # Linear congruential generator for deterministic sequence
            seed = (seed * 1103515245 + 12345) % (2**31)
            # Convert to float in range [-1, 1]
            value = (seed / (2**30)) - 1.0
            embedding.append(value)

        # Normalize to unit vector
        return self._normalize(embedding)

    @override
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        return [self.embed(text) for text in texts]

    @override
    def dimension(self) -> int:
        """Return embedding dimension."""
        return self._DIMENSION

    @override
    def model_name(self) -> str:
        """Return the mock model name."""
        return self._MODEL_NAME

    @override
    def similarity(self, vec1: list[float], vec2: list[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        if len(vec1) != len(vec2):
            raise ValueError("Vectors must have same dimension")

        dot_product = sum(a * b for a, b in zip(vec1, vec2, strict=True))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    def _normalize(self, vec: list[float]) -> list[float]:
        """Normalize vector to unit length."""
        norm = math.sqrt(sum(x * x for x in vec))
        if norm == 0:
            return vec
        return [x / norm for x in vec]
