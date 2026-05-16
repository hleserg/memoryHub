"""BGE Cross-Encoder Reranker via FlagEmbedding's FlagReranker.

This adapter is gated behind the `linguistic` optional extra. If FlagEmbedding
is not installed, the constructor raises ImportError so callers can detect
the missing dependency and fall back to NoOpReranker.
"""

from __future__ import annotations

import logging
from typing import Any

from typing_extensions import override

from atman.core.ports.memory_reranker import MemoryReranker, SurfacedMemory

logger = logging.getLogger(__name__)

try:
    from FlagEmbedding import FlagReranker as _FlagReranker  # type: ignore[import-untyped]

    _FLAG_AVAILABLE = True
except ImportError:
    _FlagReranker = None  # type: ignore[assignment]
    _FLAG_AVAILABLE = False


class BgeReranker(MemoryReranker):
    """Cross-encoder reranker backed by `BAAI/bge-reranker-v2-m3`.

    Loads the model lazily on first `rerank()` call.  The model is large
    (~568MB) and slow on CPU; deploy with a GPU when possible.
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        use_fp16: bool = True,
        device: str | None = None,
    ) -> None:
        if not _FLAG_AVAILABLE:
            raise ImportError(
                "FlagEmbedding is not installed. Install with: "
                "pip install 'atman[linguistic]' or 'pip install FlagEmbedding'"
            )
        self._model_name = model_name
        self._use_fp16 = use_fp16
        self._device = device
        self._model: Any = None

    def _get_model(self) -> Any:
        """Lazy-load the FlagReranker on first use."""
        if self._model is not None:
            return self._model
        logger.info("Loading BGE reranker %s …", self._model_name)
        try:
            kwargs: dict[str, Any] = {"use_fp16": self._use_fp16}
            if self._device is not None:
                kwargs["devices"] = [self._device]
            self._model = _FlagReranker(self._model_name, **kwargs)  # type: ignore[misc]
        except Exception:
            logger.exception("Failed to load reranker model %s", self._model_name)
            return None
        return self._model

    @override
    def rerank(
        self,
        query: str,
        candidates: list[SurfacedMemory],
        *,
        top_n: int = 10,
    ) -> list[SurfacedMemory]:
        """Rerank candidates by cross-encoder relevance to `query`.

        Falls back to the original score ordering if the model cannot be
        loaded (e.g. transient HF download failure) so callers always get
        a sorted, score-populated result.
        """
        if not candidates:
            return []
        model = self._get_model()
        if model is None:
            scored = [c.model_copy(update={"final_score": c.score}) for c in candidates]
            scored.sort(key=lambda m: m.final_score or 0.0, reverse=True)
            return scored[:top_n]

        pairs = [[query, c.text] for c in candidates]
        try:
            raw_scores = model.compute_score(pairs, normalize=True)
        except Exception:
            logger.exception("BGE reranker inference failed for %d candidates", len(pairs))
            scored = [c.model_copy(update={"final_score": c.score}) for c in candidates]
            scored.sort(key=lambda m: m.final_score or 0.0, reverse=True)
            return scored[:top_n]

        # FlagReranker.compute_score may return a single float for one pair;
        # normalise to list[float].
        if isinstance(raw_scores, (int, float)):
            raw_scores = [float(raw_scores)]
        scored = [
            c.model_copy(update={"final_score": float(s)})
            for c, s in zip(candidates, raw_scores, strict=False)
        ]
        scored.sort(key=lambda m: m.final_score or 0.0, reverse=True)
        return scored[:top_n]
