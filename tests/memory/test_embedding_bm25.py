"""
Tests for BM25EmbeddingAdapter.

Covers Devin Review fixes for PR #414:
- ``model_name`` is implemented (Protocol contract).
- ``_tokenize`` accepts non-ASCII input (Cyrillic, CJK).
- ``embed`` returns vectors of a fixed ``dimension`` so independent
  ``embed()`` calls are directly comparable via ``similarity()`` (the
  previous implementation rebuilt the vocabulary on every call, which
  silently broke that contract).
"""

from __future__ import annotations

import pytest

from atman.adapters.memory.bm25_embedding import BM25EmbeddingAdapter


class TestBM25EmbeddingAdapter:
    """Unit tests for the BM25 sparse embedding adapter."""

    @pytest.fixture
    def adapter(self) -> BM25EmbeddingAdapter:
        return BM25EmbeddingAdapter()

    def test_implements_embedding_port_methods(self, adapter: BM25EmbeddingAdapter) -> None:
        """BM25 adapter satisfies the EmbeddingPort method contract."""
        for name in ("embed", "embed_batch", "dimension", "model_name", "similarity"):
            assert callable(getattr(adapter, name)), f"missing method: {name}"

    def test_model_name_is_set(self, adapter: BM25EmbeddingAdapter) -> None:
        """``model_name`` returns a stable identifier for telemetry/logs."""
        assert adapter.model_name() == "bm25-1024d"

    def test_embed_ascii_returns_nonempty_vector(self, adapter: BM25EmbeddingAdapter) -> None:
        """English text produces a non-empty BM25 vector (regression baseline)."""
        vec = adapter.embed("the quick brown fox jumps over the lazy dog")
        assert len(vec) == adapter.dimension()
        assert any(v != 0.0 for v in vec)

    @pytest.mark.parametrize(
        "text",
        [
            "Пользователь попросил реализовать факты",  # Cyrillic
            "我喜欢猫和狗",  # Chinese
            "café résumé naïve",  # Latin with diacritics
        ],
    )
    def test_embed_non_ascii_text_produces_tokens(
        self, adapter: BM25EmbeddingAdapter, text: str
    ) -> None:
        """Non-ASCII tokens must not be silently dropped by the tokenizer.

        With the previous ``[a-z0-9]+`` pattern, Cyrillic/CJK input produced
        zero tokens and an empty embedding vector. The Unicode-aware
        ``[^\\W_]+`` tokenizer fixes this.
        """
        tokens = adapter._tokenize(text)
        assert tokens, f"tokenizer dropped all tokens for {text!r}"

        vec = adapter.embed(text)
        assert len(vec) == adapter.dimension()
        assert any(v != 0.0 for v in vec)

    def test_tokenizer_drops_underscores_and_short_tokens(
        self, adapter: BM25EmbeddingAdapter
    ) -> None:
        """Underscores and ``<= 2`` char tokens are stripped as noise."""
        tokens = adapter._tokenize("a b cd hello_world __dunder__ longer")
        # ``a``, ``b``, ``cd`` are too short; underscores split ``hello_world``.
        assert "a" not in tokens
        assert "b" not in tokens
        assert "cd" not in tokens
        assert "hello" in tokens
        assert "world" in tokens
        assert "longer" in tokens

    def test_similarity_dimension_mismatch_raises(self, adapter: BM25EmbeddingAdapter) -> None:
        """``similarity`` rejects vectors with mismatched dimensions."""
        with pytest.raises(ValueError):
            adapter.similarity([1.0, 0.0, 0.0], [1.0, 0.0])

    def test_similarity_zero_vectors_returns_zero(self, adapter: BM25EmbeddingAdapter) -> None:
        """Zero-norm vectors get a defined similarity of 0.0."""
        assert adapter.similarity([0.0, 0.0], [0.0, 0.0]) == 0.0

    def test_similarity_identical_vectors(self, adapter: BM25EmbeddingAdapter) -> None:
        """Cosine similarity of a non-zero vector with itself is ``1.0``."""
        vec = adapter.embed("the quick brown fox jumps over the lazy dog")
        assert adapter.similarity(vec, vec) == pytest.approx(1.0)

    def test_embed_calls_share_dimension_for_similarity(
        self, adapter: BM25EmbeddingAdapter
    ) -> None:
        """
        Independent ``embed()`` calls must yield vectors of identical length
        so that ``similarity()`` can compare them — prior to the E25 fix the
        adapter rebuilt the vocabulary on every call, which silently broke
        that contract.
        """
        v1 = adapter.embed("alpha beta gamma")
        v2 = adapter.embed("delta epsilon zeta")
        assert len(v1) == len(v2) == adapter.dimension()
        # similarity must run without raising and stay within [-1, 1].
        score = adapter.similarity(v1, v2)
        assert -1.0 <= score <= 1.0

    def test_invalid_dimension_raises(self) -> None:
        """``dimension`` of zero or negative is rejected eagerly."""
        with pytest.raises(ValueError, match="dimension must be positive"):
            BM25EmbeddingAdapter(dimension=0)
        with pytest.raises(ValueError, match="dimension must be positive"):
            BM25EmbeddingAdapter(dimension=-1)

    def test_embed_empty_string_returns_zero_vector(self, adapter: BM25EmbeddingAdapter) -> None:
        """``embed('')`` (or whitespace-only) returns a zero vector of the
        configured dimension."""
        vec = adapter.embed("")
        assert vec == [0.0] * adapter.dimension()
        vec = adapter.embed("   __  ")
        assert vec == [0.0] * adapter.dimension()

    def test_embed_batch_empty_input_returns_empty_list(
        self, adapter: BM25EmbeddingAdapter
    ) -> None:
        assert adapter.embed_batch([]) == []

    def test_embed_batch_returns_per_text_vectors_with_corpus_stats(
        self, adapter: BM25EmbeddingAdapter
    ) -> None:
        """``embed_batch`` returns one vector per input, all sized to the
        configured dimension. Tokens that appear only in one document carry
        a higher IDF weight than tokens common to every document."""
        texts = [
            "alpha beta gamma",
            "alpha delta epsilon",
            "alpha zeta eta",
        ]
        vecs = adapter.embed_batch(texts)
        assert len(vecs) == len(texts)
        for vec in vecs:
            assert len(vec) == adapter.dimension()

        # ``gamma`` only appears in one document, so its bucket must be > 0.
        gamma_idx = adapter._hash_bucket("gamma")
        assert vecs[0][gamma_idx] > 0.0

        # Common tokens get a smaller IDF than rare ones (BM25 with smoothing
        # never produces a hard zero, but the rare-token weight must dominate).
        assert adapter._idf("gamma") > adapter._idf("alpha")

    def test_embed_with_corpus_returns_vocab_dimension(self, adapter: BM25EmbeddingAdapter) -> None:
        """``embed_with_corpus`` builds a vocabulary-derived vector indexed by
        the corpus vocab; tokens absent from the vocabulary contribute zero."""
        corpus = ["alpha beta gamma", "alpha delta epsilon"]
        vec = adapter.embed_with_corpus("unknown_token", corpus)
        # Length is determined by the size of the corpus vocabulary.
        assert len(vec) == len(adapter._vocab) > 0
        # The query token isn't in the vocabulary -> the vector is all zero.
        assert all(v == 0.0 for v in vec)

    def test_embed_with_corpus_unique_token_has_weight(self, adapter: BM25EmbeddingAdapter) -> None:
        corpus = ["alpha beta gamma", "alpha delta epsilon"]
        vec = adapter.embed_with_corpus("beta only", corpus)
        # ``beta`` is in only one of two corpus docs => non-zero IDF.
        assert any(v > 0.0 for v in vec)

    def test_idf_returns_zero_for_unknown_term(self, adapter: BM25EmbeddingAdapter) -> None:
        """Unknown terms have IDF == 0.0 (no doc-frequency)."""
        assert adapter._idf("never-seen") == 0.0

    def test_tf_weight_handles_zero_avg_doc_len(self, adapter: BM25EmbeddingAdapter) -> None:
        """When the corpus is empty, ``avg_doc_len`` is 0 and we return raw
        term frequency so the function stays defined."""
        assert adapter._tf_weight(3, doc_len=10, avg_doc_len=0.0) == 3

    def test_hash_bucket_is_deterministic_across_instances(self) -> None:
        """Two independent adapters with the same ``dimension`` produce the
        same bucket for the same token (no per-process randomisation)."""
        a = BM25EmbeddingAdapter(dimension=128)
        b = BM25EmbeddingAdapter(dimension=128)
        assert a._hash_bucket("alpha") == b._hash_bucket("alpha")
        assert a._hash_bucket("hello") == b._hash_bucket("hello")
