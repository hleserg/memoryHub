"""
Tests for MockEmbeddingAdapter.

Issue: E25.2 - Implement MockEmbeddingAdapter (deterministic, no I/O)
"""

import math

import pytest

from atman.adapters.memory.mock_embedding import MockEmbeddingAdapter


class TestMockEmbeddingAdapter:
    """Tests for the MockEmbeddingAdapter deterministic embedding."""

    @pytest.fixture
    def adapter(self) -> MockEmbeddingAdapter:
        """Provide a fresh MockEmbeddingAdapter instance."""
        return MockEmbeddingAdapter()

    # ==========================================================================
    # Basic Functionality Tests
    # ==========================================================================

    def test_adapter_has_required_methods(self, adapter: MockEmbeddingAdapter) -> None:
        """MockEmbeddingAdapter implements all EmbeddingPort methods."""
        assert hasattr(adapter, "embed")
        assert hasattr(adapter, "embed_batch")
        assert hasattr(adapter, "dimension")
        assert hasattr(adapter, "model_name")

    def test_dimension_is_768(self, adapter: MockEmbeddingAdapter) -> None:
        """Adapter reports correct 1024 dimension (bge-m3 compatible)."""
        assert adapter.dimension() == 1024

    def test_model_name_is_mock(self, adapter: MockEmbeddingAdapter) -> None:
        """Adapter reports correct model name."""
        assert adapter.model_name() == "mock-embedding:1024d"

    def test_embed_returns_list_of_floats(self, adapter: MockEmbeddingAdapter) -> None:
        """Single text embedding returns list[float]."""
        result = adapter.embed("hello world")
        assert isinstance(result, list)
        assert len(result) == 1024
        assert all(isinstance(x, float) for x in result)

    def test_embed_dimension_matches_reported(self, adapter: MockEmbeddingAdapter) -> None:
        """Actual embedding length matches dimension() value."""
        embedding = adapter.embed("test")
        assert len(embedding) == adapter.dimension()

    # ==========================================================================
    # Determinism Tests (E25.2 spec: seeded by hash(text) % 2^31)
    # ==========================================================================

    def test_same_text_same_embedding(self, adapter: MockEmbeddingAdapter) -> None:
        """Same text produces identical embeddings (deterministic)."""
        text = "deterministic test string"
        embedding1 = adapter.embed(text)
        embedding2 = adapter.embed(text)
        assert embedding1 == embedding2

    def test_different_texts_different_embeddings(self, adapter: MockEmbeddingAdapter) -> None:
        """Different texts produce different embeddings."""
        emb1 = adapter.embed("first text")
        emb2 = adapter.embed("second text")
        assert emb1 != emb2

    def test_empty_string_embedding(self, adapter: MockEmbeddingAdapter) -> None:
        """Empty string produces valid embedding."""
        embedding = adapter.embed("")
        assert len(embedding) == 1024
        assert all(isinstance(x, float) for x in embedding)

    def test_unicode_text_embedding(self, adapter: MockEmbeddingAdapter) -> None:
        """Unicode text produces valid embedding."""
        text = "Привет мир 🌍 你好世界"
        embedding = adapter.embed(text)
        assert len(embedding) == 1024
        assert all(isinstance(x, float) for x in embedding)

    # ==========================================================================
    # Batch Embedding Tests
    # ==========================================================================

    def test_embed_batch_returns_list_of_lists(self, adapter: MockEmbeddingAdapter) -> None:
        """Batch embedding returns list[list[float]]."""
        texts = ["first", "second", "third"]
        results = adapter.embed_batch(texts)
        assert isinstance(results, list)
        assert len(results) == 3
        for emb in results:
            assert isinstance(emb, list)
            assert len(emb) == 1024
            assert all(isinstance(x, float) for x in emb)

    def test_embed_batch_empty_list(self, adapter: MockEmbeddingAdapter) -> None:
        """Empty batch returns empty list."""
        results = adapter.embed_batch([])
        assert results == []

    def test_embed_batch_single_item(self, adapter: MockEmbeddingAdapter) -> None:
        """Batch with single item works correctly."""
        results = adapter.embed_batch(["single"])
        assert len(results) == 1
        assert len(results[0]) == 1024

    def test_embed_batch_determinism(self, adapter: MockEmbeddingAdapter) -> None:
        """Batch embeddings are deterministic."""
        texts = ["a", "b", "c"]
        results1 = adapter.embed_batch(texts)
        results2 = adapter.embed_batch(texts)
        assert results1 == results2

    def test_embed_batch_matches_individual_embed(self, adapter: MockEmbeddingAdapter) -> None:
        """Batch results match individual embed calls."""
        texts = ["text one", "text two"]
        batch_results = adapter.embed_batch(texts)
        individual_results = [adapter.embed(t) for t in texts]
        assert batch_results == individual_results

    # ==========================================================================
    # Similarity Tests
    # ==========================================================================

    def test_similarity_same_vector_is_one(self, adapter: MockEmbeddingAdapter) -> None:
        """Similarity of identical vectors is 1.0."""
        vec = adapter.embed("test")
        sim = adapter.similarity(vec, vec)
        assert sim == pytest.approx(1.0, abs=1e-6)

    def test_similarity_normalized_vectors(self, adapter: MockEmbeddingAdapter) -> None:
        """Mock embeddings are unit vectors (normalized)."""
        vec = adapter.embed("test")
        norm = math.sqrt(sum(x * x for x in vec))
        assert norm == pytest.approx(1.0, abs=1e-6)

    def test_similarity_different_vectors_less_than_one(
        self, adapter: MockEmbeddingAdapter
    ) -> None:
        """Different vectors have similarity < 1.0."""
        vec1 = adapter.embed("hello")
        vec2 = adapter.embed("world")
        sim = adapter.similarity(vec1, vec2)
        assert sim < 1.0
        assert -1.0 <= sim <= 1.0

    def test_similarity_dimension_mismatch_raises(self, adapter: MockEmbeddingAdapter) -> None:
        """Similarity with mismatched dimensions raises ValueError."""
        vec1 = adapter.embed("test")
        vec2 = vec1[:-1]  # Remove last element
        with pytest.raises(ValueError, match="Vectors must have same dimension"):
            adapter.similarity(vec1, vec2)

    def test_similarity_empty_vectors(self, adapter: MockEmbeddingAdapter) -> None:
        """Similarity of empty vectors is 0.0."""
        sim = adapter.similarity([], [])
        assert sim == 0.0

    # ==========================================================================
    # Edge Cases
    # ==========================================================================

    def test_very_long_text_embedding(self, adapter: MockEmbeddingAdapter) -> None:
        """Very long text produces valid embedding."""
        text = "word " * 10000
        embedding = adapter.embed(text)
        assert len(embedding) == 1024

    def test_special_characters_embedding(self, adapter: MockEmbeddingAdapter) -> None:
        """Special characters produce valid embedding."""
        text = "\n\t\r\\\"'\x00\x01\x02"
        embedding = adapter.embed(text)
        assert len(embedding) == 1024

    def test_large_batch(self, adapter: MockEmbeddingAdapter) -> None:
        """Large batch works correctly."""
        texts = [f"text {i}" for i in range(100)]
        results = adapter.embed_batch(texts)
        assert len(results) == 100
        for emb in results:
            assert len(emb) == 1024
