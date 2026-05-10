"""Tests for OllamaEmbeddingAdapter (E24.6)."""

from __future__ import annotations

import io
import json
import urllib.error
from typing import Any
from unittest.mock import patch

import pytest

from atman.adapters.memory.ollama_embedding import OllamaEmbeddingAdapter


class _FakeResponse:
    """Context-manager stand-in for urllib.request.urlopen()."""

    def __init__(self, payload: dict[str, Any]):
        self._buffer = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_exc: object) -> None:
        self._buffer.close()

    def read(self) -> bytes:
        return self._buffer.read()


def test_init_rejects_unsupported_scheme():
    with pytest.raises(ValueError):
        OllamaEmbeddingAdapter(base_url="file:///tmp/ollama")


def test_init_accepts_https_scheme():
    adapter = OllamaEmbeddingAdapter(base_url="https://ollama.example/")
    assert adapter.base_url == "https://ollama.example/"


def test_embed_returns_vector_from_ollama():
    adapter = OllamaEmbeddingAdapter(base_url="http://localhost:11434")
    response = _FakeResponse({"embedding": [0.1, 0.2, 0.3]})
    with patch("urllib.request.urlopen", return_value=response):
        vec = adapter.embed("hello")
    assert vec == [0.1, 0.2, 0.3]


def test_embed_falls_back_to_embeddings_field():
    adapter = OllamaEmbeddingAdapter(base_url="http://localhost:11434")
    response = _FakeResponse({"embeddings": [[0.4, 0.5]]})
    with patch("urllib.request.urlopen", return_value=response):
        assert adapter.embed("hello") == [0.4, 0.5]


def test_embed_raises_when_ollama_returns_empty_payload():
    adapter = OllamaEmbeddingAdapter(base_url="http://localhost:11434")
    response = _FakeResponse({})
    with (
        patch("urllib.request.urlopen", return_value=response),
        pytest.raises(RuntimeError, match="Empty embedding"),
    ):
        adapter.embed("hello")


def test_embed_raises_runtime_error_on_empty_embeddings_list():
    """``{"embeddings": []}`` must raise RuntimeError, not IndexError."""
    adapter = OllamaEmbeddingAdapter(base_url="http://localhost:11434")
    response = _FakeResponse({"embeddings": []})
    with (
        patch("urllib.request.urlopen", return_value=response),
        pytest.raises(RuntimeError, match="Empty embedding"),
    ):
        adapter.embed("hello")


def test_embed_raises_runtime_error_when_embeddings_list_is_empty():
    """`{"embeddings": []}` returns a clean RuntimeError, not IndexError."""
    adapter = OllamaEmbeddingAdapter(base_url="http://localhost:11434")
    response = _FakeResponse({"embeddings": []})
    with (
        patch("urllib.request.urlopen", return_value=response),
        pytest.raises(RuntimeError, match="Empty embedding"),
    ):
        adapter.embed("hello")


def test_embed_wraps_url_errors():
    adapter = OllamaEmbeddingAdapter(base_url="http://localhost:11434")
    with (
        patch("urllib.request.urlopen", side_effect=urllib.error.URLError("nope")),
        pytest.raises(RuntimeError, match="Failed to connect"),
    ):
        adapter.embed("hello")


def test_embed_wraps_invalid_json():
    adapter = OllamaEmbeddingAdapter(base_url="http://localhost:11434")

    class BadResponse(_FakeResponse):
        def read(self) -> bytes:
            return b"not-json"

    with (
        patch("urllib.request.urlopen", return_value=BadResponse({})),
        pytest.raises(RuntimeError, match="Invalid JSON"),
    ):
        adapter.embed("hello")


def test_embed_batch_returns_list_of_vectors():
    adapter = OllamaEmbeddingAdapter(base_url="http://localhost:11434")
    response = _FakeResponse({"embeddings": [[0.1], [0.2]]})
    with patch("urllib.request.urlopen", return_value=response):
        vectors = adapter.embed_batch(["a", "b"])
    assert vectors == [[0.1], [0.2]]


def test_embed_batch_raises_on_empty_response():
    adapter = OllamaEmbeddingAdapter(base_url="http://localhost:11434")
    response = _FakeResponse({"embeddings": []})
    with (
        patch("urllib.request.urlopen", return_value=response),
        pytest.raises(RuntimeError, match="Empty embeddings"),
    ):
        adapter.embed_batch(["a"])


def test_dimension_caches_after_first_probe():
    adapter = OllamaEmbeddingAdapter(base_url="http://localhost:11434")
    response = _FakeResponse({"embedding": [0.1, 0.2, 0.3, 0.4]})
    with patch("urllib.request.urlopen", return_value=response) as mocked:
        assert adapter.dimension() == 4
        # Cached - should not hit the API again
        assert adapter.dimension() == 4
    assert mocked.call_count == 1


def test_similarity_zero_vector_returns_zero():
    adapter = OllamaEmbeddingAdapter(base_url="http://localhost:11434")
    assert adapter.similarity([0.0, 0.0], [0.1, 0.2]) == 0.0


def test_similarity_dimension_mismatch_raises():
    adapter = OllamaEmbeddingAdapter(base_url="http://localhost:11434")
    with pytest.raises(ValueError):
        adapter.similarity([0.1, 0.2], [0.1])


def test_health_check_returns_true_when_model_present():
    adapter = OllamaEmbeddingAdapter(
        base_url="http://localhost:11434",
        model="qwen3-embedding:1.5b",
    )
    response = _FakeResponse({"models": [{"name": "qwen3-embedding:1.5b"}]})
    with patch("urllib.request.urlopen", return_value=response):
        assert adapter.health_check() is True


def test_health_check_returns_false_when_unreachable():
    adapter = OllamaEmbeddingAdapter(base_url="http://localhost:11434")
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")):
        assert adapter.health_check() is False
