"""
OllamaEmbeddingAdapter - embedding via Ollama API.

Requires running Ollama instance with an embedding model.
Default model: bge-m3 (multilingual, 1024 dims)
"""

import json
import math
import os
import urllib.error
import urllib.request

from typing_extensions import override

from atman.core.ports.embedding import EmbeddingPort


class OllamaEmbeddingAdapter(EmbeddingPort):
    """
    Embedding adapter using Ollama API.

    Requires Ollama to be running locally or at configured host.
    Default model is bge-m3 (multilingual, 1024 dims).

    Environment variables:
        OLLAMA_HOST: Ollama server URL (default: http://localhost:11434)
        OLLAMA_EMBED_MODEL: Model name (default: bge-m3)
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        """
        Initialize Ollama embedding adapter.

        Args:
            base_url: Ollama server URL (defaults to EMBEDDING_OLLAMA_HOST env var or localhost)
            model: Model name (defaults to EMBEDDING_MODEL env var or bge-m3)
            timeout: Request timeout in seconds
        """
        resolved_url = base_url or os.environ.get(
            "EMBEDDING_OLLAMA_HOST", os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        )
        if not resolved_url.startswith(("http://", "https://")):
            raise ValueError(
                f"OllamaEmbeddingAdapter base_url must be http(s)://, got {resolved_url!r}"
            )
        self.base_url = resolved_url
        self.model = model or os.environ.get(
            "EMBEDDING_MODEL", os.environ.get("OLLAMA_EMBED_MODEL", "bge-m3")
        )
        self.timeout = timeout
        self._dimension: int | None = None

    @override
    def embed(self, text: str) -> list[float]:
        """Generate embedding via Ollama API."""
        url = f"{self.base_url}/api/embed"

        payload = json.dumps(
            {
                "model": self.model,
                "input": text,
            }
        ).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
        }

        req = urllib.request.Request(
            url,
            data=payload,
            headers=headers,
            method="POST",
        )

        try:
            # ``url`` is built from ``self.base_url`` (configured Ollama endpoint,
            # validated as ``http(s)://...`` at construction) — the file:// /
            # custom-scheme attack surface B310 warns about does not apply.
            with urllib.request.urlopen(req, timeout=self.timeout) as response:  # nosec B310
                data = json.loads(response.read().decode("utf-8"))
                # Ollama returns the vector under "embedding" for single inputs;
                # newer servers may return ``"embeddings": [[...]]`` or even an
                # explicit empty list. Normalize both shapes without indexing
                # into a possibly empty list.
                embedding = data.get("embedding")
                if not embedding:
                    embeddings = data.get("embeddings") or []
                    embedding = embeddings[0] if embeddings else []
                if not embedding:
                    raise RuntimeError("Empty embedding received from Ollama")
                return embedding
        except urllib.error.URLError as e:
            raise RuntimeError(f"Failed to connect to Ollama: {e}") from e
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON response from Ollama: {e}") from e

    @override
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        url = f"{self.base_url}/api/embed"

        payload = json.dumps(
            {
                "model": self.model,
                "input": texts,
            }
        ).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
        }

        req = urllib.request.Request(
            url,
            data=payload,
            headers=headers,
            method="POST",
        )

        try:
            # See `embed`: ``url`` derives from ``self.base_url``, which the
            # constructor restricts to http(s) endpoints.
            with urllib.request.urlopen(req, timeout=self.timeout) as response:  # nosec B310
                data = json.loads(response.read().decode("utf-8"))
                embeddings = data.get("embeddings", [])
                if not embeddings:
                    raise RuntimeError("Empty embeddings received from Ollama")
                if len(embeddings) != len(texts):
                    raise RuntimeError(
                        f"Ollama batch embedding length mismatch: "
                        f"sent {len(texts)} texts, received {len(embeddings)} vectors"
                    )
                return embeddings
        except urllib.error.URLError as e:
            raise RuntimeError(f"Failed to connect to Ollama: {e}") from e
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Invalid JSON response from Ollama: {e}") from e

    @override
    def dimension(self) -> int:
        """Return embedding dimension."""
        if self._dimension is None:
            # Probe with a sample embedding
            sample = self.embed("test")
            self._dimension = len(sample)
        return self._dimension

    @override
    def model_name(self) -> str:
        """Return model identifier."""
        return self.model

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

    def health_check(self) -> bool:
        """Check if Ollama is available and the model is loaded."""
        try:
            url = f"{self.base_url}/api/tags"
            req = urllib.request.Request(url, method="GET")
            # See `embed`: ``url`` is built from ``self.base_url``.
            with urllib.request.urlopen(req, timeout=5.0) as response:  # nosec B310
                data = json.loads(response.read().decode("utf-8"))
                models = data.get("models", [])
                return any(m.get("name") == self.model for m in models)
        except Exception:
            return False
