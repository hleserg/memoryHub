"""Tests for MockEmbeddingAdapter (E24.6)."""

from __future__ import annotations

import pytest

from atman.adapters.memory.mock_embedding import MockEmbeddingAdapter


def test_embed_is_deterministic():
    adapter = MockEmbeddingAdapter()
    vec1 = adapter.embed("Hello world")
    vec2 = adapter.embed("Hello world")
    assert vec1 == vec2


def test_embed_different_texts_produce_different_vectors():
    adapter = MockEmbeddingAdapter()
    vec_a = adapter.embed("Hello world")
    vec_b = adapter.embed("Completely different text")
    assert vec_a != vec_b


def test_embed_returns_unit_vector():
    adapter = MockEmbeddingAdapter()
    vec = adapter.embed("Hello world")
    norm_sq = sum(x * x for x in vec)
    assert norm_sq == pytest.approx(1.0, abs=1e-6)


def test_dimension_matches_embedding_length():
    adapter = MockEmbeddingAdapter()
    assert adapter.dimension() == len(adapter.embed("anything"))


def test_embed_batch_returns_one_vector_per_text():
    adapter = MockEmbeddingAdapter()
    vectors = adapter.embed_batch(["one", "two", "three"])
    assert len(vectors) == 3
    assert vectors[0] == adapter.embed("one")


def test_similarity_self_is_one():
    adapter = MockEmbeddingAdapter()
    vec = adapter.embed("foo bar")
    assert adapter.similarity(vec, vec) == pytest.approx(1.0)


def test_similarity_zero_vector_returns_zero():
    adapter = MockEmbeddingAdapter()
    zero = [0.0] * adapter.dimension()
    other = adapter.embed("text")
    assert adapter.similarity(zero, other) == 0.0
    assert adapter.similarity(other, zero) == 0.0


def test_similarity_dimension_mismatch_raises():
    adapter = MockEmbeddingAdapter()
    with pytest.raises(ValueError):
        adapter.similarity([0.1, 0.2], [0.1, 0.2, 0.3])
