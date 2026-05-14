"""Tests for FlagEmbeddingAdapter."""

from typing import Any

import pytest


class _FakeArray:
    """Small stand-in for numpy arrays returned by FlagEmbedding."""

    def __init__(self, value: Any) -> None:
        self._value = value

    def tolist(self) -> Any:
        return self._value


class _FakeBGEM3Model:
    """Fake BGEM3 model that records encode calls without loading FlagEmbedding."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def encode(
        self,
        texts: list[str],
        *,
        batch_size: int,
        max_length: int,
        return_dense: bool,
        return_sparse: bool,
        return_colbert_vecs: bool,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "texts": texts,
                "batch_size": batch_size,
                "max_length": max_length,
                "return_dense": return_dense,
                "return_sparse": return_sparse,
                "return_colbert_vecs": return_colbert_vecs,
            }
        )
        output: dict[str, Any] = {
            "dense_vecs": _FakeArray([[1.0, 0.0], [0.0, 1.0]][: len(texts)]),
        }
        if return_sparse:
            output["lexical_weights"] = [{101: 0.75, "known": 0.25} for _ in texts]
        if return_colbert_vecs:
            output["colbert_vecs"] = [_FakeArray([[0.1, 0.2]]) for _ in texts]
        return output

FLAG_EMBEDDING_AVAILABLE = False
try:
    import FlagEmbedding  # noqa: F401  # type: ignore[import-not-found]

    FLAG_EMBEDDING_AVAILABLE = True
except ImportError:
    pass


@pytest.mark.skipif(not FLAG_EMBEDDING_AVAILABLE, reason="FlagEmbedding not installed")
class TestFlagEmbeddingAdapter:
    """Tests for FlagEmbeddingAdapter with real FlagEmbedding SDK."""

    def setup_method(self) -> None:
        """Setup adapter with test configuration."""
        from atman.adapters.memory.flag_embedding import FlagEmbeddingAdapter

        self.adapter = FlagEmbeddingAdapter(
            model_name="BAAI/bge-m3",
            use_fp16=False,  # CPU for CI
            batch_size=2,
            max_length=64,
        )

    def test_embed_returns_correct_dimension(self) -> None:
        """Embed returns 1024-dimensional vector."""
        vec = self.adapter.embed("hello world")
        assert len(vec) == 1024
        assert all(isinstance(x, float) for x in vec)

    def test_embed_batch_correct_count(self) -> None:
        """Batch embedding returns correct number of vectors."""
        texts = ["first sentence", "second sentence", "third sentence"]
        vecs = self.adapter.embed_batch(texts)
        assert len(vecs) == 3
        assert all(len(v) == 1024 for v in vecs)
        assert all(all(isinstance(x, float) for x in v) for v in vecs)

    def test_embed_is_normalized(self) -> None:
        """BGE-M3 returns normalized vectors (unit length)."""
        import math

        vec = self.adapter.embed("test normalization")
        norm = math.sqrt(sum(x * x for x in vec))
        # BGE-M3 returns normalized vectors
        assert abs(norm - 1.0) < 0.01

    def test_similarity_same_text(self) -> None:
        """Similarity of identical vectors is close to 1.0."""
        vec = self.adapter.embed("identical text")
        sim = self.adapter.similarity(vec, vec)
        assert sim > 0.99

    def test_similarity_different_texts(self) -> None:
        """Similarity of different semantic content is lower."""
        v1 = self.adapter.embed("Python programming language")
        v2 = self.adapter.embed("quantum physics equations")
        sim = self.adapter.similarity(v1, v2)
        # Different topics should have lower similarity
        assert sim < 0.9

    def test_dimension(self) -> None:
        """Dimension returns 1024 for BGE-M3."""
        assert self.adapter.dimension() == 1024

    def test_model_name(self) -> None:
        """Model name returns configured model path."""
        assert self.adapter.model_name() == "BAAI/bge-m3"

    def test_embed_batch_full_returns_dense_and_sparse(self) -> None:
        """embed_batch_full returns dense vectors and lexical weights."""
        result = self.adapter.embed_batch_full(["sample text for hybrid"], return_sparse=True)
        assert "dense_vecs" in result
        assert "lexical_weights" in result
        assert len(result["dense_vecs"]) == 1
        assert len(result["lexical_weights"]) == 1
        # dense_vecs should be 1024-dimensional
        assert len(result["dense_vecs"][0]) == 1024
        # lexical_weights should be dict[str, float]
        assert isinstance(result["lexical_weights"][0], dict)
        # Check that keys are strings (token IDs converted)
        for key in result["lexical_weights"][0]:
            assert isinstance(key, str)

    def test_embed_batch_full_without_sparse(self) -> None:
        """embed_batch_full with return_sparse=False omits lexical_weights."""
        result = self.adapter.embed_batch_full(
            ["sample text"], return_sparse=False, return_colbert=False
        )
        assert "dense_vecs" in result
        assert "lexical_weights" not in result
        assert "colbert_vecs" not in result

    def test_similarity_orthogonal_concept(self) -> None:
        """Similarity between orthogonal concepts is moderate."""
        v1 = self.adapter.embed("machine learning algorithms")
        v2 = self.adapter.embed("culinary recipes")
        sim = self.adapter.similarity(v1, v2)
        # Orthogonal concepts should have low to moderate similarity
        assert 0.0 <= sim < 0.7

    def test_similarity_dimension_mismatch_raises(self) -> None:
        """Similarity with mismatched dimensions raises ValueError."""
        vec1 = [1.0] * 1024
        vec2 = [1.0] * 512
        with pytest.raises(ValueError, match="Vectors must have same dimension"):
            self.adapter.similarity(vec1, vec2)

    def test_similarity_zero_vectors(self) -> None:
        """Similarity of zero vectors returns 0.0."""
        vec_zero = [0.0] * 1024
        vec_normal = [1.0] * 1024
        sim = self.adapter.similarity(vec_zero, vec_normal)
        assert sim == 0.0


class TestFlagEmbeddingAdapterAvailability:
    """Tests for FlagEmbeddingAdapter availability check (no model loading)."""

    def test_is_available_returns_bool(self) -> None:
        """is_available returns bool without loading model."""
        from atman.adapters.memory.flag_embedding import FlagEmbeddingAdapter

        adapter = FlagEmbeddingAdapter.__new__(FlagEmbeddingAdapter)
        result = adapter.is_available()
        assert isinstance(result, bool)

    @pytest.mark.skipif(not FLAG_EMBEDDING_AVAILABLE, reason="FlagEmbedding not installed")
    def test_is_available_true_when_installed(self) -> None:
        """is_available returns True when FlagEmbedding is installed."""
        from atman.adapters.memory.flag_embedding import FlagEmbeddingAdapter

        adapter = FlagEmbeddingAdapter()
        assert adapter.is_available() is True

    def test_model_lazy_loading(self) -> None:
        """Model is not loaded until first embed call."""
        from atman.adapters.memory.flag_embedding import FlagEmbeddingAdapter

        adapter = FlagEmbeddingAdapter()
        # Model should be None before first use
        assert adapter._model is None

    def test_embed_batch_uses_configured_encode_options_without_real_sdk(self) -> None:
        """embed_batch passes adapter limits to BGEM3FlagModel.encode."""
        from atman.adapters.memory.flag_embedding import FlagEmbeddingAdapter

        adapter = FlagEmbeddingAdapter(batch_size=7, max_length=123)
        fake_model = _FakeBGEM3Model()
        adapter._model = fake_model

        result = adapter.embed_batch(["first", "second"])

        assert result == [[1.0, 0.0], [0.0, 1.0]]
        assert fake_model.calls == [
            {
                "texts": ["first", "second"],
                "batch_size": 7,
                "max_length": 123,
                "return_dense": True,
                "return_sparse": False,
                "return_colbert_vecs": False,
            }
        ]

    def test_embed_batch_full_normalizes_hybrid_outputs_without_real_sdk(self) -> None:
        """Hybrid output is JSON-friendly without requiring the FlagEmbedding package."""
        from atman.adapters.memory.flag_embedding import FlagEmbeddingAdapter

        adapter = FlagEmbeddingAdapter(batch_size=3, max_length=64)
        fake_model = _FakeBGEM3Model()
        adapter._model = fake_model

        result = adapter.embed_batch_full(["hybrid"], return_sparse=True, return_colbert=True)

        assert result == {
            "dense_vecs": [[1.0, 0.0]],
            "lexical_weights": [{"101": 0.75, "known": 0.25}],
            "colbert_vecs": [[[0.1, 0.2]]],
        }
        assert fake_model.calls == [
            {
                "texts": ["hybrid"],
                "batch_size": 3,
                "max_length": 64,
                "return_dense": True,
                "return_sparse": True,
                "return_colbert_vecs": True,
            }
        ]

    def test_build_embedding_adapter_raises_when_flag_backend_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Selecting FlagEmbedding must fail fast when the SDK is unavailable."""
        from atman import config as atman_config
        from atman.adapters.memory.flag_embedding import FlagEmbeddingAdapter

        monkeypatch.setattr(atman_config.settings.embedding, "backend", "flag")
        monkeypatch.setattr(FlagEmbeddingAdapter, "is_available", lambda self: False)

        with pytest.raises(RuntimeError, match="FlagEmbedding backend selected but not installed"):
            atman_config.build_embedding_adapter()

    def test_build_embedding_adapter_uses_flag_settings_without_model_load(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """FlagEmbedding config wiring is deterministic and does not load the model."""
        from atman import config as atman_config
        from atman.adapters.memory.flag_embedding import FlagEmbeddingAdapter

        monkeypatch.setattr(atman_config.settings.embedding, "backend", "flag")
        monkeypatch.setattr(atman_config.settings.embedding, "flag_model", "fake/bge")
        monkeypatch.setattr(atman_config.settings.embedding, "use_fp16", False)
        monkeypatch.setattr(atman_config.settings.embedding, "batch_size", 5)
        monkeypatch.setattr(atman_config.settings.embedding, "max_length", 256)
        monkeypatch.setattr(FlagEmbeddingAdapter, "is_available", lambda self: True)

        adapter = atman_config.build_embedding_adapter()

        assert isinstance(adapter, FlagEmbeddingAdapter)
        assert adapter.model_name() == "fake/bge"
        assert adapter._use_fp16 is False
        assert adapter._batch_size == 5
        assert adapter._max_length == 256
        assert adapter._model is None

    @pytest.mark.skipif(not FLAG_EMBEDDING_AVAILABLE, reason="FlagEmbedding not installed")
    def test_model_loads_on_first_embed(self) -> None:
        """Model is loaded on first embed call."""
        from atman.adapters.memory.flag_embedding import FlagEmbeddingAdapter

        adapter = FlagEmbeddingAdapter(use_fp16=False, max_length=64)
        assert adapter._model is None
        # First embed call should load model
        _ = adapter.embed("test")
        assert adapter._model is not None

    @pytest.mark.skipif(not FLAG_EMBEDDING_AVAILABLE, reason="FlagEmbedding not installed")
    def test_custom_model_name(self) -> None:
        """Custom model name is stored and returned."""
        from atman.adapters.memory.flag_embedding import FlagEmbeddingAdapter

        adapter = FlagEmbeddingAdapter(model_name="custom/model-path")
        assert adapter.model_name() == "custom/model-path"

    @pytest.mark.skipif(not FLAG_EMBEDDING_AVAILABLE, reason="FlagEmbedding not installed")
    def test_empty_text_handling(self) -> None:
        """Empty text can be embedded without error."""
        from atman.adapters.memory.flag_embedding import FlagEmbeddingAdapter

        adapter = FlagEmbeddingAdapter(use_fp16=False, max_length=64)
        vec = adapter.embed("")
        assert len(vec) == 1024

    @pytest.mark.skipif(not FLAG_EMBEDDING_AVAILABLE, reason="FlagEmbedding not installed")
    def test_long_text_truncation(self) -> None:
        """Long text beyond max_length is handled gracefully."""
        from atman.adapters.memory.flag_embedding import FlagEmbeddingAdapter

        adapter = FlagEmbeddingAdapter(use_fp16=False, max_length=64)
        long_text = " ".join(["word"] * 1000)  # Much longer than max_length
        vec = adapter.embed(long_text)
        assert len(vec) == 1024


class TestFlagEmbeddingAdapterImportError:
    """Tests for error handling when FlagEmbedding is not installed."""

    def test_embed_raises_runtime_error_when_not_installed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """embed raises RuntimeError with helpful message when FlagEmbedding not installed."""
        from atman.adapters.memory.flag_embedding import FlagEmbeddingAdapter

        adapter = FlagEmbeddingAdapter()

        # Mock import to simulate missing FlagEmbedding
        def mock_import(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
            if name == "FlagEmbedding":
                raise ImportError("No module named 'FlagEmbedding'")
            return __import__(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", mock_import)

        with pytest.raises(RuntimeError, match="FlagEmbedding not installed"):
            adapter.embed("test")
