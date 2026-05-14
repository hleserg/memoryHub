"""
Atman configuration management via Pydantic Settings.

Centralizes all environment variable configuration with type validation.
"""

import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class EmbeddingSettings(BaseSettings):
    """Embedding service configuration."""

    model_config = SettingsConfigDict(
        env_prefix="EMBEDDING_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    backend: str = "flag"  # "flag" (native FlagEmbedding), "ollama" (HTTP), or "mock"
    model: str = "BAAI/bge-m3"  # Model path (HuggingFace for flag, Ollama model for ollama)
    dimension: int = 1024  # Embedding vector dimension (1024 for bge-m3)
    ollama_host: str = "http://localhost:11434"  # Ollama API host (used if backend="ollama")
    timeout: float = 30.0  # Request timeout in seconds (used if backend="ollama")
    # FlagEmbedding-specific settings (used if backend="flag")
    use_fp16: bool = True  # Use float16 for faster inference (recommended with GPU)
    batch_size: int = 32  # Batch size for FlagEmbedding encode
    max_length: int = 512  # Max token length for FlagEmbedding (BGE-M3 supports up to 8192)


class LLMSettings(BaseSettings):
    """LLM service configuration for agent and reflection."""

    model_config = SettingsConfigDict(
        env_prefix="LLM_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    model: str = "gemma3:27b-it-qat"  # Ollama model name for agent/reflection
    ollama_host: str = "http://localhost:11434"  # Ollama API host
    timeout: float = 120.0  # Request timeout in seconds (higher for larger models)


class MemorySettings(BaseModel):
    """Factual memory backend selection.

    Default is ``file`` for CLI, tests, and local development. Production can set
    ``ATMAN_MEMORY_BACKEND=postgres`` (see :func:`build_memory_backend`).

    backend options:
      "postgres"  — PostgresFactualMemory (DATABASE_URL from env)
      "file"      — FileBackend (JSONL, path configurable below)
      "inmemory"  — InMemoryBackend (lost on restart, useful for quick tests)
    """

    backend: str = "file"
    file_path: str = "~/.atman/facts.jsonl"


class Settings(BaseSettings):
    """Global application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "postgresql://atman@localhost:5432/atman"

    embedding: EmbeddingSettings = EmbeddingSettings()
    llm: LLMSettings = LLMSettings()
    memory: MemorySettings = MemorySettings()


# Global settings instance
settings = Settings()


def build_memory_backend():
    """Instantiate the factual memory backend selected in config.memory.backend.

    Can be overridden via ATMAN_MEMORY_BACKEND environment variable.
    """
    from atman.core.ports import FactualMemory  # noqa: F401 (type hint target)

    # Subprocess-friendly override for tests and local tooling (see tests/test_cli_factual_memory.py).
    backend = os.environ.get("ATMAN_MEMORY_BACKEND", settings.memory.backend)

    if backend == "postgres":
        from atman.adapters.memory.postgres_backend import PostgresFactualMemory

        mem = PostgresFactualMemory(db_url=settings.database_url)
        mem.connect()
        return mem

    if backend == "file":
        from atman.adapters.memory import FileBackend

        return FileBackend(Path(settings.memory.file_path).expanduser())

    if backend == "inmemory":
        from atman.adapters.memory import InMemoryBackend

        return InMemoryBackend()

    raise ValueError(
        f"Unknown memory backend {backend!r}. "
        "Set config.memory.backend to 'postgres', 'file', or 'inmemory'."
    )


def build_embedding_adapter() -> Any:
    """
    Build the embedding adapter based on settings.embedding.backend.

    Returns the configured embedding adapter (FlagEmbeddingAdapter, OllamaEmbeddingAdapter,
    or MockEmbeddingAdapter).

    Raises:
        ValueError: If backend is unknown
    """
    backend = settings.embedding.backend

    if backend == "flag":
        from atman.adapters.memory.flag_embedding import FlagEmbeddingAdapter

        adapter = FlagEmbeddingAdapter(
            model_name=settings.embedding.model,
            use_fp16=settings.embedding.use_fp16,
            batch_size=settings.embedding.batch_size,
            max_length=settings.embedding.max_length,
        )
        if not adapter.is_available():
            # Soft fallback to Ollama with warning
            import warnings

            warnings.warn(
                "FlagEmbedding not installed, falling back to OllamaEmbeddingAdapter. "
                "Run: pip install FlagEmbedding",
                RuntimeWarning,
                stacklevel=2,
            )
            from atman.adapters.memory.ollama_embedding import OllamaEmbeddingAdapter

            return OllamaEmbeddingAdapter(
                base_url=settings.embedding.ollama_host,
                model=settings.embedding.model,
                timeout=settings.embedding.timeout,
            )
        return adapter

    if backend == "ollama":
        from atman.adapters.memory.ollama_embedding import OllamaEmbeddingAdapter

        return OllamaEmbeddingAdapter(
            base_url=settings.embedding.ollama_host,
            model=settings.embedding.model,
            timeout=settings.embedding.timeout,
        )

    if backend == "mock":
        from atman.adapters.memory.mock_embedding import MockEmbeddingAdapter

        return MockEmbeddingAdapter()

    raise ValueError(
        f"Unknown embedding backend {backend!r}. "
        "Set config.embedding.backend to 'flag', 'ollama', or 'mock'."
    )


def validate_embedding_dimension() -> None:
    """
    Validate that the configured embedding dimension matches the actual model dimension.

    This check should be called at startup when using Ollama embeddings to ensure
    the vector store dimension matches the embedding model being used.

    Raises:
        RuntimeError: If the embedding adapter dimension doesn't match config
    """
    if settings.embedding.backend == "ollama":
        from atman.adapters.memory.ollama_embedding import OllamaEmbeddingAdapter

        try:
            adapter = OllamaEmbeddingAdapter(
                base_url=settings.embedding.ollama_host,
                model=settings.embedding.model,
                timeout=settings.embedding.timeout,
            )
            actual_dim = adapter.dimension()

            if actual_dim != settings.embedding.dimension:
                raise RuntimeError(
                    f"Embedding dimension mismatch!\n"
                    f"  Config EMBEDDING_DIMENSION: {settings.embedding.dimension}\n"
                    f"  Actual model dimension: {actual_dim}\n"
                    f"  Model: {settings.embedding.model}\n\n"
                    f"If you changed the embedding model, you must:\n"
                    f"  1. Update EMBEDDING_DIMENSION={actual_dim} in your config/.env\n"
                    f"  2. Run scripts/migrate_embeddings.py to re-embed existing data"
                )
        except RuntimeError:
            raise
        except Exception as e:
            # Don't fail startup if Ollama is unavailable, just warn
            import warnings

            warnings.warn(
                f"Could not validate embedding dimension (Ollama may not be running): {e}",
                RuntimeWarning,
                stacklevel=2,
            )
