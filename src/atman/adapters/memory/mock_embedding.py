"""
MockEmbeddingAdapter - deterministic hash-based embedding for testing.

Generates reproducible embeddings without external dependencies.
Uses 2560-dimensional vectors to match qwen3-embedding:4b dimensions.
"""

import hashlib
import math
from typing import override

from atman.core.ports.embedding import EmbeddingPort


class MockEmbeddingAdapter(EmbeddingPort):
    """
    Mock embedding adapter for testing.

    Generates deterministic embeddings based on text hashing.
    Uses 2560-dimensional vectors to match qwen3-embedding:4b dimensions.
    """

    _DIMENSION = 2560

    @override
    def embed(self, text: str) -> list[float]:
        """Generate deterministic embedding from text hash.

        Uses hash(text) % 2^31 as seed for deterministic pseudo-random generation.
        """
        # Use hash modulo 2^31 as seed (per E25 spec)
        seed = hash(text) % (2**31)

        # Generate embedding values using deterministic pseudo-random sequence
        embedding: list[float] = []
        for i in range(self._DIMENSION):
            # Use hashlib for additional mixing to ensure good distribution
            h = hashlib.sha256(f"{seed}:{i}".encode()).digest()
            value = int.from_bytes(h[:4], byteorder="big") / (2**32)
            embedding.append(value * 2.0 - 1.0)  # Scale to [-1, 1]

        # Normalize to unit vector
        norm = math.sqrt(sum(x * x for x in embedding))
        if norm > 0:
            embedding = [x / norm for x in embedding]

        return embedding

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
        """Return model identifier."""
        return "mock-embedding:768d"

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
