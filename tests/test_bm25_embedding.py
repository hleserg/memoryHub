"""Tests for BM25EmbeddingAdapter (E24.6)."""

from __future__ import annotations

import pytest

from atman.adapters.memory.bm25_embedding import BM25EmbeddingAdapter


def test_tokenize_drops_short_tokens_and_lowercases():
    adapter = BM25EmbeddingAdapter()
    assert adapter._tokenize("Hello, World! a") == ["hello", "world"]


def test_tokenize_supports_cyrillic_and_other_unicode():
    adapter = BM25EmbeddingAdapter()
    # Cyrillic words are tokenised correctly (the underscore in
    # ``test_case`` must NOT be treated as part of a word).
    tokens = adapter._tokenize("Привет, мир тест! test_case")
    assert "привет" in tokens
    assert "мир" in tokens
    assert "тест" in tokens
    # ``test`` and ``case`` survive the underscore split, both > 2 chars.
    assert "test" in tokens
    assert "case" in tokens
    # Greek script also tokenises.
    greek = adapter._tokenize("αβγδ ωωωω")
    assert "αβγδ" in greek
    assert "ωωωω" in greek


def test_embed_returns_fixed_dimension_for_any_input():
    adapter = BM25EmbeddingAdapter(dimension=64)
    vec1 = adapter.embed("alpha beta beta gamma")
    vec2 = adapter.embed("entirely different words here")
    assert adapter.dimension() == 64
    assert len(vec1) == 64
    assert len(vec2) == 64


def test_embed_results_are_pairwise_comparable():
    """The original bug: independent embed() calls now share dimensions."""
    adapter = BM25EmbeddingAdapter(dimension=128)
    a = adapter.embed("the deploy succeeded")
    b = adapter.embed("the deploy failed")
    # similarity must not raise — vectors share the fixed dimension.
    sim = adapter.similarity(a, b)
    assert 0.0 <= sim <= 1.0


def test_embed_batch_returns_fixed_dimension_vectors():
    adapter = BM25EmbeddingAdapter(dimension=128)
    docs = [
        "alpha beta gamma delta",
        "alpha epsilon zeta eta",
        "alpha beta theta iota",
    ]
    vectors = adapter.embed_batch(docs)
    assert len(vectors) == 3
    dim = adapter.dimension()
    assert dim == 128
    assert all(len(vec) == dim for vec in vectors)
    # No longer check internal _vocab, as embed_batch uses hashing trick
    # Instead verify that vectors differ when content differs
    assert vectors[0] != vectors[1]
    assert vectors[0] != vectors[2]
    assert vectors[1] != vectors[2]


def test_embed_with_corpus_uses_idf():
    adapter = BM25EmbeddingAdapter(dimension=128)
    corpus = [
        "rare word here",
        "common term here",
        "common term again",
    ]
    vec = adapter.embed_with_corpus("rare word", corpus)
    rare_idx = adapter._vocab["rare"]
    common_idx = adapter._vocab["common"]
    # "rare" is in the query and has positive weight; "common" is not in
    # the query so its slot is zero.
    assert vec[rare_idx] > 0.0
    assert vec[common_idx] == 0.0


def test_embed_with_corpus_skips_oov_terms():
    adapter = BM25EmbeddingAdapter(dimension=128)
    corpus = ["alpha beta gamma"]
    vec = adapter.embed_with_corpus("alpha unknownterm", corpus)
    # embed_with_corpus uses vocab-derived dimension, not fixed dimension
    assert len(vec) == len(adapter._vocab)
    # "alpha" is in the corpus; its slot has a non-negative weight.
    assert vec[adapter._vocab["alpha"]] >= 0.0


def test_similarity_self_is_one_for_nonzero_vector():
    adapter = BM25EmbeddingAdapter()
    vec = adapter.embed("hello world world world")
    assert adapter.similarity(vec, vec) == pytest.approx(1.0)


def test_similarity_zero_vector_returns_zero():
    adapter = BM25EmbeddingAdapter()
    other = adapter.embed("alpha beta")
    zero = [0.0] * adapter.dimension()
    assert adapter.similarity(zero, other) == 0.0


def test_similarity_dimension_mismatch_raises():
    adapter = BM25EmbeddingAdapter()
    with pytest.raises(ValueError):
        adapter.similarity([0.1], [0.1, 0.2])


def test_similarity_rejects_embed_vs_embed_with_corpus_mix():
    """embed() and embed_with_corpus() produce vectors of different dimensions
    (fixed hashing-trick vs vocabulary-derived). similarity() must refuse to
    score them against each other instead of returning a garbage number."""
    adapter = BM25EmbeddingAdapter()
    fixed_vec = adapter.embed("the quick brown fox jumps over the lazy dog")
    corpus_vec = adapter.embed_with_corpus(
        "the quick brown fox",
        ["the quick brown fox", "lazy dog jumps", "another corpus document"],
    )
    assert len(fixed_vec) != len(corpus_vec)
    with pytest.raises(ValueError, match="dimension mismatch"):
        adapter.similarity(fixed_vec, corpus_vec)


def test_idf_returns_zero_for_unknown_term():
    adapter = BM25EmbeddingAdapter()
    adapter._build_corpus_stats([["alpha"], ["beta"]])
    # A term whose hashed slot is not in the doc-frequency table reads
    # back as zero IDF; pick a string whose hash is unlikely to collide
    # with the small corpus.
    assert adapter._idf("zzz_unique_unknown_term_qwerty") == 0.0


def test_tf_weight_handles_zero_avg_doc_len():
    adapter = BM25EmbeddingAdapter()
    # avg_doc_len == 0 short-circuits to plain term frequency
    assert adapter._tf_weight(term_freq=3, doc_len=0, avg_doc_len=0) == 3


def test_build_corpus_stats_with_empty_corpus():
    adapter = BM25EmbeddingAdapter()
    adapter._build_corpus_stats([])
    assert adapter._num_docs == 0
    assert adapter._avg_doc_len == 0.0


def test_init_rejects_non_positive_dimension():
    with pytest.raises(ValueError):
        BM25EmbeddingAdapter(dimension=0)
    with pytest.raises(ValueError):
        BM25EmbeddingAdapter(dimension=-1)
