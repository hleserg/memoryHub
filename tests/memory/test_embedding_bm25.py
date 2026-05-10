"""
Tests for BM25EmbeddingAdapter.

Covers Devin Review fixes for PR #414:
- ``model_name`` is implemented (Protocol contract).
- ``_tokenize`` accepts non-ASCII input (Cyrillic, CJK).
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
        assert adapter.model_name() == "bm25-sparse"

    def test_embed_ascii_returns_nonempty_vector(self, adapter: BM25EmbeddingAdapter) -> None:
        """English text produces a non-empty BM25 vector (regression baseline)."""
        vec = adapter.embed("the quick brown fox jumps over the lazy dog")
        assert len(vec) > 0
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
        ``\\w+`` tokenizer fixes this.
        """
        tokens = adapter._tokenize(text)
        assert tokens, f"tokenizer dropped all tokens for {text!r}"

        vec = adapter.embed(text)
        assert len(vec) > 0
        assert any(v != 0.0 for v in vec)

    def test_similarity_dimension_mismatch_raises(self, adapter: BM25EmbeddingAdapter) -> None:
        """``similarity`` rejects vectors with mismatched dimensions."""
        with pytest.raises(ValueError):
            adapter.similarity([1.0, 0.0, 0.0], [1.0, 0.0])

    def test_similarity_zero_vectors_returns_zero(self, adapter: BM25EmbeddingAdapter) -> None:
        """Zero-norm vectors get a defined similarity of 0.0."""
        assert adapter.similarity([0.0, 0.0], [0.0, 0.0]) == 0.0
