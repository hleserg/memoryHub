# TASK — Перейти с Ollama HTTP API на нативный FlagEmbedding SDK

## Контекст

Сейчас Atman использует `OllamaEmbeddingAdapter` для получения эмбеддингов BGE-M3 через HTTP-запросы к локальному Ollama-серверу (`POST /api/embed`). Это создаёт лишнюю зависимость от запущенного процесса Ollama и добавляет сетевые накладные расходы (~10–100 мс на запрос).

`FlagEmbedding` — официальный Python SDK от BAAI (авторов BGE-M3) с прямым вызовом модели через PyTorch. Даёт доступ ко всем трём режимам: dense + sparse (lexical) + ColBERT.

**Репозиторий:** https://github.com/FlagOpen/FlagEmbedding

---

## Что уже есть (не трогать)

- `EmbeddingPort` — порт-интерфейс (`src/atman/core/ports/embedding.py`), методы: `embed()`, `embed_batch()`, `dimension()`, `model_name()`, `similarity()`
- `OllamaEmbeddingAdapter` — текущая реализация (`src/atman/adapters/memory/ollama_embedding.py`), **оставить как fallback**
- `MockEmbeddingAdapter` — для тестов, 1024-мерные векторы, **не трогать**
- `postgres_backend.py` — принимает `EmbeddingPort`, **не трогать**
- `passive_memory_injector.py` — принимает `EmbeddingPort`, **не трогать**

---

## Что нужно сделать

### 1. Установить зависимость

В `pyproject.toml` добавить в `[project.optional-dependencies]` или в основные зависимости:

```toml
"FlagEmbedding>=1.3",
```

Также понадобится `torch` (уже должен быть, если используется локальный GPU), `numpy`.

### 2. Создать новый адаптер `FlagEmbeddingAdapter`

**Файл:** `src/atman/adapters/memory/flag_embedding.py`

```python
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
                {str(k): float(v) for k, v in lw.items()}
                for lw in output["lexical_weights"]
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
```

### 3. Экспортировать из `__init__.py`

В `src/atman/adapters/memory/__init__.py` добавить:

```python
from atman.adapters.memory.flag_embedding import FlagEmbeddingAdapter

__all__ = [
    ...,
    "FlagEmbeddingAdapter",
]
```

### 4. Обновить конфиг

В `src/atman/config.py` — `EmbeddingConfig` (или аналогичный датакласс):

```python
# Было:
model: str = "bge-m3"  # Ollama model name

# Стать:
model: str = "BAAI/bge-m3"         # HuggingFace model path для FlagEmbeddingAdapter
backend: str = "flag"               # "flag" | "ollama" — выбор адаптера
use_fp16: bool = True
batch_size: int = 32
max_length: int = 512
```

Переменные окружения:
```bash
EMBEDDING_BACKEND=flag        # или "ollama" для обратной совместимости
EMBEDDING_MODEL=BAAI/bge-m3
EMBEDDING_USE_FP16=true
EMBEDDING_BATCH_SIZE=32
EMBEDDING_MAX_LENGTH=512
```

### 5. Фабрика адаптера

В `src/run_agent.py` или в месте инициализации `PostgresFactualMemory` — добавить выбор адаптера:

```python
from atman.config import EmbeddingConfig
from atman.adapters.memory import FlagEmbeddingAdapter, OllamaEmbeddingAdapter

def build_embedding_adapter(cfg: EmbeddingConfig):
    """
    Factory: выбирает FlagEmbeddingAdapter или OllamaEmbeddingAdapter
    на основе конфига/env.
    """
    backend = cfg.backend  # "flag" | "ollama"

    if backend == "flag":
        adapter = FlagEmbeddingAdapter(
            model_name=cfg.model,       # "BAAI/bge-m3"
            use_fp16=cfg.use_fp16,
            batch_size=cfg.batch_size,
            max_length=cfg.max_length,
        )
        if not adapter.is_available():
            # Мягкий fallback с предупреждением
            import warnings
            warnings.warn(
                "FlagEmbedding not installed, falling back to OllamaEmbeddingAdapter. "
                "Run: pip install FlagEmbedding",
                stacklevel=2,
            )
            return OllamaEmbeddingAdapter()
        return adapter

    # backend == "ollama" — обратная совместимость
    return OllamaEmbeddingAdapter()
```

### 6. Написать тесты

**Файл:** `tests/memory/test_flag_embedding.py`

```python
"""Tests for FlagEmbeddingAdapter."""
import pytest

FLAG_EMBEDDING_AVAILABLE = False
try:
    import FlagEmbedding  # noqa: F401
    FLAG_EMBEDDING_AVAILABLE = True
except ImportError:
    pass


@pytest.mark.skipif(not FLAG_EMBEDDING_AVAILABLE, reason="FlagEmbedding not installed")
class TestFlagEmbeddingAdapter:
    def setup_method(self):
        from atman.adapters.memory.flag_embedding import FlagEmbeddingAdapter
        self.adapter = FlagEmbeddingAdapter(
            model_name="BAAI/bge-m3",
            use_fp16=False,  # CPU для CI
            batch_size=2,
            max_length=64,
        )

    def test_embed_returns_correct_dimension(self):
        vec = self.adapter.embed("hello world")
        assert len(vec) == 1024

    def test_embed_batch_correct_count(self):
        texts = ["first sentence", "second sentence", "third sentence"]
        vecs = self.adapter.embed_batch(texts)
        assert len(vecs) == 3
        assert all(len(v) == 1024 for v in vecs)

    def test_embed_is_normalized(self):
        import math
        vec = self.adapter.embed("test normalization")
        norm = math.sqrt(sum(x * x for x in vec))
        assert abs(norm - 1.0) < 0.01  # BGE-M3 возвращает нормированные векторы

    def test_similarity_same_text(self):
        vec = self.adapter.embed("identical text")
        sim = self.adapter.similarity(vec, vec)
        assert sim > 0.99

    def test_similarity_different_texts(self):
        v1 = self.adapter.embed("Python programming language")
        v2 = self.adapter.embed("quantum physics equations")
        sim = self.adapter.similarity(v1, v2)
        assert sim < 0.9  # разные темы — низкое сходство

    def test_dimension(self):
        assert self.adapter.dimension() == 1024

    def test_model_name(self):
        assert self.adapter.model_name() == "BAAI/bge-m3"

    def test_embed_batch_full_returns_dense_and_sparse(self):
        result = self.adapter.embed_batch_full(
            ["sample text for hybrid"], return_sparse=True
        )
        assert "dense_vecs" in result
        assert "lexical_weights" in result
        assert len(result["dense_vecs"]) == 1
        assert len(result["lexical_weights"]) == 1
        # lexical_weights — dict токен → вес
        assert isinstance(result["lexical_weights"][0], dict)


class TestFlagEmbeddingAdapterAvailability:
    """Тесты без загрузки модели — только проверка is_available()."""

    def test_is_available_returns_bool(self):
        from atman.adapters.memory.flag_embedding import FlagEmbeddingAdapter
        adapter = FlagEmbeddingAdapter.__new__(FlagEmbeddingAdapter)
        assert isinstance(adapter.is_available(), bool)
```

---

## Что НЕ нужно менять

- `EmbeddingPort` — интерфейс остаётся без изменений
- `OllamaEmbeddingAdapter` — остаётся как fallback (`backend="ollama"`)
- `MockEmbeddingAdapter` — для тестов, не трогать
- `postgres_backend.py` — принимает `EmbeddingPort`, прозрачно работает с любым адаптером
- Размерность вектора остаётся **1024** — в БД ничего не меняется

---

## Ключевые отличия от текущей реализации

| | `OllamaEmbeddingAdapter` | `FlagEmbeddingAdapter` |
|---|---|---|
| Зависимость | Ollama-процесс запущен | `pip install FlagEmbedding` |
| Латентность | HTTP-запрос ~10–100 мс | Прямой PyTorch вызов ~1–5 мс |
| Батчинг | Один запрос на батч | Встроенный batch_size |
| Sparse/ColBERT | Нет | `embed_batch_full()` |
| Первый запуск | Модель уже в Ollama | Скачает ~570 MB в `~/.cache/huggingface/` |
| CPU/GPU | На стороне Ollama | Управляется через `use_fp16`, `device` |
| Конфиг | `OLLAMA_HOST`, `OLLAMA_EMBED_MODEL` | `EMBEDDING_BACKEND=flag`, `EMBEDDING_MODEL` |

---

## API FlagEmbedding SDK (справка)

```python
from FlagEmbedding import BGEM3FlagModel

model = BGEM3FlagModel('BAAI/bge-m3', use_fp16=True)

output = model.encode(
    sentences,               # list[str]
    batch_size=12,           # тексты за раз
    max_length=8192,         # max токены (BGE-M3 поддерживает до 8192)
    return_dense=True,       # вернуть dense_vecs: ndarray (n, 1024)
    return_sparse=True,      # вернуть lexical_weights: list[dict[token_id, float]]
    return_colbert_vecs=True # вернуть colbert_vecs: ndarray per-token
)

# output keys:
output['dense_vecs']       # ndarray (n, 1024)
output['lexical_weights']  # list[dict] — BM25-style sparse weights
output['colbert_vecs']     # list[ndarray] — multi-vector (per token)
```

---

## Порядок выполнения

1. `pip install FlagEmbedding` — проверить что устанавливается
2. Создать `flag_embedding.py` с кодом выше
3. Добавить в `__init__.py`
4. Обновить `EmbeddingConfig` в `config.py` (добавить поле `backend`)
5. Добавить фабрику `build_embedding_adapter()` в `run_agent.py`
6. Написать тесты в `tests/memory/test_flag_embedding.py`
7. Проверить что `MockEmbeddingAdapter` в тестах не сломался
8. Запустить `uv run pytest tests/memory/ -v`
