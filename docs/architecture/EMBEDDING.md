# Embedding Architecture

## Overview

Atman's memory system relies on semantic embeddings for similarity search. The Embedding Port provides an abstraction over embedding providers, enabling pluggable implementations while maintaining a consistent interface for the memory layer.

## Embedding Port Contract

The `EmbeddingPort` abstract base class (`src/atman/core/ports/embedding.py`) defines the contract:

```python
class EmbeddingPort(ABC):
    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Generate embedding vector for a single text."""
        pass

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embedding vectors for multiple texts."""
        pass

    @abstractmethod
    def dimension(self) -> int:
        """Return the dimension of embeddings produced."""
        pass

    @abstractmethod
    def model_name(self) -> str:
        """Return the name of the embedding model used."""
        pass
```

### Key Design Decisions

1. **Dimension Consistency**: All adapters must return vectors of the configured dimension (2560 for qwen3-embedding:4b)
2. **Determinism**: Mock adapter uses `hash(text) % 2^31` seeding for reproducible test results
3. **Model Traceability**: `model_name()` enables tracking which model generated each embedding

## Configuration

Embedding configuration is controlled via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `EMBEDDING_BACKEND` | `mock` | Backend to use: `ollama` or `mock` |
| `EMBEDDING_MODEL` | `qwen3-embedding:4b` | Ollama model name |
| `EMBEDDING_DIMENSION` | `768` | Expected vector dimension |
| `EMBEDDING_OLLAMA_HOST` | `http://localhost:11434` | Ollama API endpoint |
| `EMBEDDING_TIMEOUT` | `30.0` | Request timeout in seconds |

Configuration is loaded via Pydantic Settings (`src/atman/config.py`) with `.env` file support.

## Available Adapters

### OllamaEmbeddingAdapter

Production adapter using Ollama's `/api/embed` endpoint.

**Features:**
- Supports any Ollama embedding model
- Batch embedding for efficiency
- Health check via `health_check()` method
- Automatic dimension probing

**Usage:**
```python
from atman.adapters.memory.ollama_embedding import OllamaEmbeddingAdapter

adapter = OllamaEmbeddingAdapter(
    base_url="http://localhost:11434",
    model="qwen3-embedding:4b",
    timeout=30.0,
)

embedding = adapter.embed("semantic search query")
assert len(embedding) == 2560
assert adapter.model_name() == "qwen3-embedding:4b"
```

**Requirements:**
- Running Ollama instance
- Model pulled: `ollama pull qwen3-embedding:4b`

### MockEmbeddingAdapter

Deterministic test adapter with no external dependencies.

**Features:**
- Same text always produces same embedding
- Different texts produce different embeddings
- 2560-dimensional unit vectors
- LCG-based deterministic generation

**Usage:**
```python
from atman.adapters.memory.mock_embedding import MockEmbeddingAdapter

adapter = MockEmbeddingAdapter()

embedding1 = adapter.embed("hello world")
embedding2 = adapter.embed("hello world")
assert embedding1 == embedding2  # Deterministic
assert adapter.dimension() == 2560
assert adapter.model_name() == "mock-embedding:768d"
```

## Model Choice: qwen3-embedding:4b

The default embedding model is `qwen3-embedding:4b` for the following reasons:

| Criterion | qwen3-embedding:4b |
|-----------|-------------------|
| **Dimension** | 2560 |
| **Quality** | Good performance on MTEB benchmarks |
| **Speed** | ~50ms per query on consumer GPU |
| **Size** | 1.5B parameters, ~600MB |
| **License** | Apache 2.0 (commercial use OK) |
| **Multilingual** | Strong CJK + English support |

## Database Schema

Tables storing embeddings include `embed_model` column for traceability:

```sql
ALTER TABLE public.facts
ADD COLUMN embed_model TEXT;

ALTER TABLE public.key_moments
ADD COLUMN embed_model TEXT;

ALTER TABLE public.identity_snapshots
ADD COLUMN embed_model TEXT;
```

This enables:
- **Model migration tracking**: Know which model generated each vector
- **Re-embedding decisions**: Identify records needing re-processing when models change
- **Audit trail**: Maintain data lineage for compliance

## Health Check

Verify embedder status:

```python
from atman.adapters.memory.ollama_embedding import OllamaEmbeddingAdapter

adapter = OllamaEmbeddingAdapter()
if adapter.health_check():
    print(f"Ollama ready with {adapter.model_name()}")
    sample = adapter.embed("__warmup__")
    assert len(sample) == adapter.dimension()
```

## How to Add a New Adapter

To add support for a new embedding provider (e.g., OpenAI, Hugging Face):

### Step 1: Create Adapter File

Create `src/atman/adapters/memory/openai_embedding.py`:

```python
"""OpenAIEmbeddingAdapter - embedding via OpenAI API."""

import math
from typing import override

from atman.core.ports.embedding import EmbeddingPort


class OpenAIEmbeddingAdapter(EmbeddingPort):
    """Embedding adapter using OpenAI API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "text-embedding-3-small",
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.model = model
        self.timeout = timeout
        self._dimension = 1536  # text-embedding-3-small dimension

    @override
    def embed(self, text: str) -> list[float]:
        """Generate embedding via OpenAI API."""
        # Implementation: call OpenAI /embeddings endpoint
        # Return list[float] of correct dimension
        pass

    @override
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts."""
        return [self.embed(text) for text in texts]

    @override
    def dimension(self) -> int:
        """Return embedding dimension."""
        return self._dimension

    @override
    def model_name(self) -> str:
        """Return the configured OpenAI model name."""
        return self.model

    def health_check(self) -> bool:
        """Verify API key and connectivity."""
        try:
            self.embed("test")
            return True
        except Exception:
            return False
```

### Step 2: Update Configuration

Add to `src/atman/config.py`:

```python
class EmbeddingSettings(BaseSettings):
    backend: str = "mock"  # Add "openai" option
    openai_api_key: str | None = None
    openai_model: str = "text-embedding-3-small"
```

### Step 3: Register in `__init__.py`

Update `src/atman/adapters/memory/__init__.py` to export the new adapter.

### Step 4: Add Tests

Create `tests/memory/test_embedding_openai.py` with ≥15 tests covering:
- Successful embedding generation
- Dimension verification
- Model name reporting
- Health check behavior
- Error handling (invalid API key, network failure)
- Batch embedding consistency

### Step 5: Update Documentation

Add to this file:
- New adapter description
- Configuration options
- Model comparison table

## Testing

Run embedding tests:

```bash
# All embedding tests
pytest tests/memory/test_embedding_*.py -v

# Mock adapter only (no external services)
pytest tests/memory/test_embedding_mock.py -v

# Ollama adapter (requires running Ollama)
pytest tests/memory/test_embedding_ollama.py -v --requires-ollama
```

## Troubleshooting

### Ollama Connection Failed

```
RuntimeError: Failed to connect to Ollama: <urlopen error [Errno 111] Connection refused>
```

**Solution:** Start Ollama:
```bash
docker-compose up -d ollama
# or
ollama serve
```

### Model Not Found

```
RuntimeError: Empty embedding received from Ollama
```

**Solution:** Pull the model:
```bash
ollama pull qwen3-embedding:4b
```

### Dimension Mismatch

```
ValueError: Vectors must have same dimension
```

**Solution:** Check `EMBEDDING_DIMENSION` matches actual model output.

## References

- Issue: [#391](https://github.com/hleserg/atman/issues/391) - Epic E25
- Model: [qwen3-embedding:4b](https://ollama.com/library/qwen3-embedding)
- Ollama API: [embed endpoint](https://github.com/ollama/ollama/blob/main/docs/api.md#generate-embeddings)
