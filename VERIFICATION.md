# BGE-M3 + Gemma3 Verification Instructions

This document provides step-by-step instructions to verify that BGE-M3 and Gemma3 are properly integrated into Atman.

## Prerequisites

Before verification, ensure you have:

1. **Ollama installed and running** (`http://localhost:11434`)
2. **Required models pulled**:
   ```bash
   ollama pull bge-m3
   ollama pull gemma3:27b-it-qat
   ```

## Verification Steps

### 1. Verify Ollama Models

Check that both models are available:

```bash
ollama list
```

Expected output should include:
- `bge-m3:latest`
- `gemma3:27b-it-qat`

### 2. Test Embedding Generation

Test BGE-M3 embeddings directly via Ollama API:

```bash
curl http://localhost:11434/api/embeddings -d '{
  "model": "bge-m3",
  "prompt": "Test embedding"
}'
```

Expected:
- HTTP 200 response
- JSON with `embedding` field containing 1024 floats

### 3. Test LLM Chat

Test Gemma3 chat completion:

```bash
curl http://localhost:11434/api/chat -d '{
  "model": "gemma3:27b-it-qat",
  "messages": [{"role": "user", "content": "Say hello"}],
  "stream": false
}'
```

Expected:
- HTTP 200 response
- JSON with `message.content` containing a greeting

### 4. Test Atman Configuration

Check that Atman picks up the new defaults:

```python
from atman.config import settings

print(f"Embedding model: {settings.embedding.model}")
print(f"Embedding dimension: {settings.embedding.dimension}")
print(f"LLM model: {settings.llm.model}")

# Expected output:
# Embedding model: bge-m3
# Embedding dimension: 1024
# LLM model: gemma3:27b-it-qat
```

### 5. Test Embedding Adapter

Test the OllamaEmbeddingAdapter with BGE-M3:

```python
from atman.adapters.memory.ollama_embedding import OllamaEmbeddingAdapter

adapter = OllamaEmbeddingAdapter()
print(f"Model: {adapter.model_name()}")
print(f"Dimension: {adapter.dimension()}")

embedding = adapter.embed("Test sentence")
print(f"Embedding length: {len(embedding)}")
print(f"Sample values: {embedding[:5]}")

# Expected output:
# Model: bge-m3
# Dimension: 1024
# Embedding length: 1024
# Sample values: [0.123, -0.456, 0.789, ...]
```

### 6. Test LLM Provider

Test the OllamaReflectionModel with Gemma3:

```python
from atman.adapters.reflection.ollama_reflection_model import OllamaReflectionModel

with OllamaReflectionModel() as model:
    print(f"Model: {model.model}")
    print(f"Base URL: {model.base_url}")

# Expected output:
# Model: gemma3:27b-it-qat
# Base URL: http://localhost:11434
```

### 7. Test Dimension Validation

Test the startup dimension validation check:

```python
from atman.config import validate_embedding_dimension

try:
    validate_embedding_dimension()
    print("✓ Dimension validation passed!")
except RuntimeError as e:
    print(f"✗ Dimension mismatch: {e}")
```

Expected: "✓ Dimension validation passed!"

### 8. Test Agent Dialogue (Full Integration)

Run a simple 3-turn agent dialogue to verify end-to-end integration:

```bash
# Set up environment
export EMBEDDING_MODEL=bge-m3
export EMBEDDING_DIMENSION=1024
export LLM_MODEL=gemma3:27b-it-qat

# Run a demo or CLI session
python3 -m atman.cli
```

In the CLI:
```
> add "User prefers concise answers" session_1 preference communication
> search "preference" --limit 2
> exit
```

Expected:
- Facts are stored successfully
- Semantic search returns relevant results
- No errors related to embeddings or LLM calls

### 9. PostgreSQL Vector Store Migration (if applicable)

If you have existing data in PostgreSQL with old embeddings:

```bash
# Dry run to see what would happen
python scripts/migrate_embeddings.py --dry-run

# Run actual migration
python scripts/migrate_embeddings.py
```

Expected output:
```
Migration Configuration:
  Database: localhost:5432/atman
  Embedding Model: bge-m3
  Ollama Host: http://localhost:11434
  Mode: LIVE

Target embedding dimension: 1024
Current embedding dimension: 2560

Found N facts with embeddings to migrate

Re-embedding facts with new model...
  Progress: N/N (100.0%)

Verification:
  New dimension: 1024
  Expected dimension: 1024
  ✓ Migration successful!
  Facts with embeddings before: N
  Facts with embeddings after: N
  ✓ Count matches!
```

## Troubleshooting

### Ollama not responding

```bash
# Check if Ollama is running
curl http://localhost:11434/api/tags

# Restart Ollama if needed
ollama serve
```

### Model not found

```bash
# Pull the missing model
ollama pull bge-m3
ollama pull gemma3:27b-it-qat
```

### Dimension mismatch error

If you see:
```
RuntimeError: Embedding dimension mismatch!
  Config EMBEDDING_DIMENSION: 1024
  Actual model dimension: 2560
```

This means you have the wrong model loaded. Check:
```bash
ollama list | grep bge
# Should show: bge-m3
```

### Legacy environment variables

The code supports legacy environment variable names for backward compatibility:
- `OLLAMA_HOST` → now `EMBEDDING_OLLAMA_HOST`
- `OLLAMA_EMBED_MODEL` → now `EMBEDDING_MODEL`
- `ATMAN_OLLAMA_BASE_URL` → now `LLM_OLLAMA_HOST`
- `ATMAN_OLLAMA_MODEL` → now `LLM_MODEL`

New names take precedence if both are set.

## Success Criteria

All verification steps should pass with:
- ✓ BGE-M3 model available and responding
- ✓ Gemma3:27b-it-qat model available and responding
- ✓ Embeddings are 1024-dimensional
- ✓ LLM chat completions work
- ✓ Atman configuration picks up new defaults
- ✓ Dimension validation passes
- ✓ Agent dialogue runs without errors
- ✓ (If applicable) Vector store migration completes successfully
