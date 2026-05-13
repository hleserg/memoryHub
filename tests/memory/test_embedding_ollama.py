"""
Tests for OllamaEmbeddingAdapter.

Issue: E25.3 - Implement OllamaEmbeddingAdapter against bge-m3
Uses mocked HTTP responses to avoid requiring a running Ollama instance.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from atman.adapters.memory.ollama_embedding import OllamaEmbeddingAdapter


class TestOllamaEmbeddingAdapter:
    """Tests for the OllamaEmbeddingAdapter with mocked HTTP."""

    @pytest.fixture
    def adapter(self) -> OllamaEmbeddingAdapter:
        """Provide a fresh OllamaEmbeddingAdapter instance."""
        return OllamaEmbeddingAdapter(
            base_url="http://localhost:11434",
            model="bge-m3",
            timeout=30.0,
        )

    @pytest.fixture
    def mock_768_embedding(self) -> list[float]:
        """Generate a fake 1024-dim embedding for mocking."""
        # Deterministic fake embedding
        return [float(i % 10) / 10.0 for i in range(1024)]

    # ==========================================================================
    # Basic Functionality Tests
    # ==========================================================================

    def test_adapter_is_instance_of_port(self, adapter: OllamaEmbeddingAdapter) -> None:
        """OllamaEmbeddingAdapter can be used as EmbeddingPort."""
        # Verify the adapter has all required methods
        assert hasattr(adapter, "embed")
        assert hasattr(adapter, "embed_batch")
        assert hasattr(adapter, "dimension")
        assert hasattr(adapter, "model_name")

    def test_model_name_reports_configured_model(self, adapter: OllamaEmbeddingAdapter) -> None:
        """Adapter reports configured model name."""
        assert adapter.model_name() == "bge-m3"

    def test_custom_model_name(self) -> None:
        """Custom model name is reported correctly."""
        custom = OllamaEmbeddingAdapter(model="nomic-embed-text")
        assert custom.model_name() == "nomic-embed-text"

    def test_dimension_probes_on_first_call(
        self, adapter: OllamaEmbeddingAdapter, mock_768_embedding: list[float]
    ) -> None:
        """Dimension is probed via API call on first access."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"embedding": mock_768_embedding}).encode(
            "utf-8"
        )
        # urlopen is used as context manager: with urlopen(...) as response
        mock_context = MagicMock()
        mock_context.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_context):
            dim = adapter.dimension()

        assert dim == 1024

    def test_dimension_caches_result(
        self, adapter: OllamaEmbeddingAdapter, mock_768_embedding: list[float]
    ) -> None:
        """Dimension result is cached (only one API call)."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"embedding": mock_768_embedding}).encode(
            "utf-8"
        )
        # urlopen is used as context manager: with urlopen(...) as response
        mock_context = MagicMock()
        mock_context.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_context) as mock_urlopen:
            _ = adapter.dimension()  # First call
            _ = adapter.dimension()  # Second call (should be cached)
            _ = adapter.dimension()  # Third call (should be cached)

        # Only one API call for probing
        assert mock_urlopen.call_count == 1

    # ==========================================================================
    # Embed Tests
    # ==========================================================================

    def test_embed_returns_list_of_floats(
        self, adapter: OllamaEmbeddingAdapter, mock_768_embedding: list[float]
    ) -> None:
        """Single text embedding returns list[float]."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"embedding": mock_768_embedding}).encode(
            "utf-8"
        )
        # urlopen is used as context manager: with urlopen(...) as response
        mock_context = MagicMock()
        mock_context.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_context):
            result = adapter.embed("hello world")

        assert isinstance(result, list)
        assert len(result) == 1024
        assert all(isinstance(x, float) for x in result)

    def test_embed_makes_correct_api_call(
        self, adapter: OllamaEmbeddingAdapter, mock_768_embedding: list[float]
    ) -> None:
        """Embed makes POST request to /api/embed with correct payload."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"embedding": mock_768_embedding}).encode(
            "utf-8"
        )
        # urlopen is used as context manager: with urlopen(...) as response
        mock_context = MagicMock()
        mock_context.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_context) as mock_urlopen:
            adapter.embed("test text")

        # Verify the request was made
        assert mock_urlopen.call_count == 1
        call_args = mock_urlopen.call_args
        request = call_args[0][0]

        assert request.full_url == "http://localhost:11434/api/embed"
        assert request.method == "POST"

        # Parse request body
        body = json.loads(request.data.decode("utf-8"))
        assert body["model"] == "bge-m3"
        assert body["input"] == "test text"

    def test_embed_handles_embeddings_field_response(
        self, adapter: OllamaEmbeddingAdapter, mock_768_embedding: list[float]
    ) -> None:
        """Embed handles response with 'embeddings' field (batch format)."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"embeddings": [mock_768_embedding]}).encode(
            "utf-8"
        )
        # urlopen is used as context manager: with urlopen(...) as response
        mock_context = MagicMock()
        mock_context.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_context):
            result = adapter.embed("hello")

        assert len(result) == 1024

    # ==========================================================================
    # Embed Batch Tests
    # ==========================================================================

    def test_embed_batch_returns_list_of_lists(
        self, adapter: OllamaEmbeddingAdapter, mock_768_embedding: list[float]
    ) -> None:
        """Batch embedding returns list[list[float]]."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"embeddings": [mock_768_embedding, mock_768_embedding, mock_768_embedding]}
        ).encode("utf-8")
        # urlopen is used as context manager: with urlopen(...) as response
        mock_context = MagicMock()
        mock_context.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_context):
            results = adapter.embed_batch(["a", "b", "c"])

        assert isinstance(results, list)
        assert len(results) == 3
        for emb in results:
            assert isinstance(emb, list)
            assert len(emb) == 1024

    def test_embed_batch_makes_correct_api_call(
        self, adapter: OllamaEmbeddingAdapter, mock_768_embedding: list[float]
    ) -> None:
        """Batch embed makes POST request with array input."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"embeddings": [mock_768_embedding, mock_768_embedding]}
        ).encode("utf-8")
        # urlopen is used as context manager: with urlopen(...) as response
        mock_context = MagicMock()
        mock_context.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_context) as mock_urlopen:
            adapter.embed_batch(["text1", "text2"])

        call_args = mock_urlopen.call_args
        request = call_args[0][0]
        body = json.loads(request.data.decode("utf-8"))

        assert body["input"] == ["text1", "text2"]

    # ==========================================================================
    # Error Handling Tests
    # ==========================================================================

    def test_embed_raises_on_connection_error(self, adapter: OllamaEmbeddingAdapter) -> None:
        """Embed raises RuntimeError on connection failure."""
        from urllib.error import URLError

        with (
            patch(
                "urllib.request.urlopen",
                side_effect=URLError("Connection refused"),
            ),
            pytest.raises(RuntimeError, match="Failed to connect to Ollama"),
        ):
            adapter.embed("test")

    def test_embed_raises_on_invalid_json(self, adapter: OllamaEmbeddingAdapter) -> None:
        """Embed raises RuntimeError on invalid JSON response."""
        mock_response = MagicMock()
        mock_response.read.return_value = b"not valid json"
        # urlopen is used as context manager: with urlopen(...) as response
        mock_context = MagicMock()
        mock_context.__enter__.return_value = mock_response

        with (
            patch("urllib.request.urlopen", return_value=mock_context),
            pytest.raises(RuntimeError, match="Invalid JSON response"),
        ):
            adapter.embed("test")

    def test_embed_raises_on_empty_embedding(self, adapter: OllamaEmbeddingAdapter) -> None:
        """Embed raises RuntimeError when embedding is empty."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"embedding": []}).encode("utf-8")
        # urlopen is used as context manager: with urlopen(...) as response
        mock_context = MagicMock()
        mock_context.__enter__.return_value = mock_response

        with (
            patch("urllib.request.urlopen", return_value=mock_context),
            pytest.raises(RuntimeError, match="Empty embedding"),
        ):
            adapter.embed("test")

    def test_embed_raises_on_empty_embeddings_list(self, adapter: OllamaEmbeddingAdapter) -> None:
        """Empty ``embeddings: []`` from Ollama raises RuntimeError, not IndexError.

        Regression for Devin Review BUG_pr-review-job…0001 on PR #414: a fallback
        of ``data.get("embeddings", [[]])[0]`` would raise ``IndexError`` when the
        key is *present* with an empty list, because dict.get returns the actual
        empty list (not the default).
        """
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"embeddings": []}).encode("utf-8")
        mock_context = MagicMock()
        mock_context.__enter__.return_value = mock_response

        with (
            patch("urllib.request.urlopen", return_value=mock_context),
            pytest.raises(RuntimeError, match="Empty embedding"),
        ):
            adapter.embed("test")

    def test_embed_uses_embeddings_array_when_embedding_key_absent(
        self, adapter: OllamaEmbeddingAdapter, mock_768_embedding: list[float]
    ) -> None:
        """Newer Ollama versions return ``embeddings: [[...]]`` with no
        ``embedding`` key. The adapter must accept that shape."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"embeddings": [mock_768_embedding]}).encode(
            "utf-8"
        )
        mock_context = MagicMock()
        mock_context.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_context):
            result = adapter.embed("test")

        assert result == mock_768_embedding

    # ==========================================================================
    # Similarity Tests
    # ==========================================================================

    def test_similarity_same_vector_is_one(
        self, adapter: OllamaEmbeddingAdapter, mock_768_embedding: list[float]
    ) -> None:
        """Similarity of identical vectors is 1.0."""
        sim = adapter.similarity(mock_768_embedding, mock_768_embedding)
        assert sim == pytest.approx(1.0, abs=1e-6)

    def test_similarity_orthogonal_vectors(self, adapter: OllamaEmbeddingAdapter) -> None:
        """Orthogonal vectors have similarity 0.0."""
        vec1 = [1.0] + [0.0] * 767
        vec2 = [0.0, 1.0] + [0.0] * 766
        sim = adapter.similarity(vec1, vec2)
        assert sim == pytest.approx(0.0, abs=1e-6)

    def test_similarity_dimension_mismatch_raises(self, adapter: OllamaEmbeddingAdapter) -> None:
        """Similarity with mismatched dimensions raises ValueError."""
        vec1 = [1.0] * 1024
        vec2 = [1.0] * 767
        with pytest.raises(ValueError, match="Vectors must have same dimension"):
            adapter.similarity(vec1, vec2)

    # ==========================================================================
    # Health Check Tests
    # ==========================================================================

    def test_health_check_returns_true_when_healthy(self, adapter: OllamaEmbeddingAdapter) -> None:
        """Health check returns True when Ollama is available and model exists."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps(
            {"models": [{"name": "bge-m3"}]}
        ).encode("utf-8")
        # urlopen is used as context manager: with urlopen(...) as response
        mock_context = MagicMock()
        mock_context.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_context):
            assert adapter.health_check() is True

    def test_health_check_returns_false_when_model_missing(
        self, adapter: OllamaEmbeddingAdapter
    ) -> None:
        """Health check returns False when model is not pulled."""
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({"models": [{"name": "other-model"}]}).encode(
            "utf-8"
        )
        # urlopen is used as context manager: with urlopen(...) as response
        mock_context = MagicMock()
        mock_context.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_context):
            assert adapter.health_check() is False

    def test_health_check_returns_false_on_error(self, adapter: OllamaEmbeddingAdapter) -> None:
        """Health check returns False on any exception."""
        with patch("urllib.request.urlopen", side_effect=Exception("Network error")):
            assert adapter.health_check() is False

    # ==========================================================================
    # Configuration Tests
    # ==========================================================================

    def test_default_base_url_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Base URL can be set via EMBEDDING_OLLAMA_HOST env var."""
        monkeypatch.setenv("EMBEDDING_OLLAMA_HOST", "http://ollama.custom:8080")
        adapter = OllamaEmbeddingAdapter()
        assert adapter.base_url == "http://ollama.custom:8080"

    def test_default_model_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Model can be set via EMBEDDING_MODEL env var."""
        monkeypatch.setenv("EMBEDDING_MODEL", "nomic-embed-text")
        adapter = OllamaEmbeddingAdapter()
        assert adapter.model == "nomic-embed-text"
        assert adapter.model_name() == "nomic-embed-text"

    def test_constructor_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Constructor parameters override env vars."""
        monkeypatch.setenv("OLLAMA_EMBED_MODEL", "env-model")
        adapter = OllamaEmbeddingAdapter(model="constructor-model")
        assert adapter.model == "constructor-model"
