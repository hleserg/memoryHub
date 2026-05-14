"""
FlagEmbeddingAdapter - embedding via FlagEmbedding native Python SDK.

Uses BGEM3FlagModel directly without Ollama HTTP server.
Supports dense, sparse (lexical), and ColBERT multi-vector retrieval.
Default model: BAAI/bge-m3 (multilingual, 1024 dims)
"""

from __future__ import annotations

import math
from typing import Any

from typing_extensions import override

from atman.core.ports.embedding import EmbeddingPort


class FlagEmbeddingAdapter(EmbeddingPort):
    """
    Embedding adapter using FlagEmbedding native SDK (BGEM3FlagModel).

    No Ollama required. Loads model directly via PyTorch/Hugging Face.
    First call downloads the model to ~/.cache/huggingface/ (~570 MB).

    Args:
        model_name: HuggingFace model path (default: BAAI/bge-m3)
        use_fp16: Use float16 for faster inference (recommended if GPU available)
        batch_size: Texts per batch during encode (default: 32)
        max_length: Max token length (BGE-M3 supports up to 8192)
        device: 'cuda', 'cpu', or None for auto-detect
    """

    _DIMENSION = 1024  # BGE-M3 dense vector dimension

    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        use_fp16: bool = True,
        batch_size: int = 32,
        max_length: int = 512,
        device: str | None = None,
    ) -> None:
        self._model_name = model_name
        self._use_fp16 = use_fp16
        self._batch_size = batch_size
        self._max_length = max_length
        self._device = device
        self._model: Any = None  # lazy load

    def _get_model(self) -> Any:
        """Lazy-load BGEM3FlagModel on first use."""
        if self._model is None:
            try:
                from FlagEmbedding import BGEM3FlagModel
            except ImportError as e:
                raise RuntimeError(
                    "FlagEmbedding not installed. Run: pip install FlagEmbedding"
                ) from e

            kwargs: dict[str, Any] = {"use_fp16": self._use_fp16}
            if self._device is not None:
                kwargs["device"] = self._device

            self._model = BGEM3FlagModel(self._model_name, **kwargs)
        return self._model

    @override
    def embed(self, text: str) -> list[float]:
        """Generate dense embedding for a single text."""
        return self.embed_batch([text])[0]

    @override
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Generate dense embeddings for multiple texts.

        Uses BGEM3FlagModel.encode() with return_dense=True.
        Returns list of 1024-dimensional float vectors.
        """
        model = self._get_model()
        output = model.encode(
            texts,
            batch_size=self._batch_size,
            max_length=self._max_length,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        # output['dense_vecs'] is numpy ndarray of shape (n, 1024)
        return output["dense_vecs"].tolist()

    def embed_batch_full(
        self,
        texts: list[str],
        return_sparse: bool = True,
        return_colbert: bool = False,
    ) -> dict[str, Any]:
        """
        Full hybrid embedding: dense + sparse (lexical weights) + optional ColBERT.

        Returns dict with keys:
          - 'dense_vecs': list[list[float]]       — 1024-dim dense vectors
          - 'lexical_weights': list[dict[str, float]]  — token → weight (BM25-style)
          - 'colbert_vecs': list[list[list[float]]]    — multi-vectors (if requested)

        Used by RAGIndex._hybrid_search() in atman_agent_cli.
        """
        model = self._get_model()
        output = model.encode(
            texts,
            batch_size=self._batch_size,
            max_length=self._max_length,
            return_dense=True,
            return_sparse=return_sparse,
            return_colbert_vecs=return_colbert,
        )
        result: dict[str, Any] = {
            "dense_vecs": output["dense_vecs"].tolist(),
        }
        if return_sparse:
            # Convert token_id keys to strings for JSON-serializability
            result["lexical_weights"] = [
                {str(k): float(v) for k, v in lw.items()} for lw in output["lexical_weights"]
            ]
        if return_colbert:
            result["colbert_vecs"] = [cv.tolist() for cv in output["colbert_vecs"]]
        return result

    @override
    def dimension(self) -> int:
        return self._DIMENSION

    @override
    def model_name(self) -> str:
        return self._model_name

    @override
    def similarity(self, vec1: list[float], vec2: list[float]) -> float:
        """Cosine similarity between two dense vectors."""
        if len(vec1) != len(vec2):
            raise ValueError("Vectors must have same dimension")
        dot = sum(a * b for a, b in zip(vec1, vec2, strict=True))
        n1 = math.sqrt(sum(a * a for a in vec1))
        n2 = math.sqrt(sum(b * b for b in vec2))
        if n1 == 0 or n2 == 0:
            return 0.0
        return dot / (n1 * n2)

    def is_available(self) -> bool:
        """Check if FlagEmbedding package is installed."""
        try:
            import FlagEmbedding  # noqa: F401

            return True
        except ImportError:
            return False
