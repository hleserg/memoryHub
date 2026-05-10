"""
EmbeddingPort - interface for text embedding generation.

Defines the contract for embedding providers that convert text to vectors.
Used for semantic similarity search in passive memory surfacing.
"""

from abc import abstractmethod
from typing import Protocol


class EmbeddingPort(Protocol):
    """Interface for embedding generation services."""

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """
        Generate embedding vector for a single text.

        Args:
            text: The text to embed

        Returns:
            list[float]: The embedding vector
        """
        pass

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embedding vectors for multiple texts.

        Args:
            texts: List of texts to embed

        Returns:
            list[list[float]]: List of embedding vectors
        """
        pass

    @abstractmethod
    def dimension(self) -> int:
        """
        Return the dimension of embeddings produced.

        Returns:
            int: The vector dimension
        """
        pass

    @abstractmethod
    def model_name(self) -> str:
        """
        Return the name of the embedding model used.

        Returns:
            str: The model identifier (e.g., "qwen3-embedding:1.5b")
        """
        pass

    @abstractmethod
    def similarity(self, vec1: list[float], vec2: list[float]) -> float:
        """
        Calculate similarity between two embedding vectors.

        Default is cosine similarity, but implementations may vary.

        Args:
            vec1: First embedding vector
            vec2: Second embedding vector

        Returns:
            float: Similarity score (typically -1.0 to 1.0)
        """
        pass
