"""
Atman configuration management via Pydantic Settings.

Centralizes all environment variable configuration with type validation.
"""

import os
from pathlib import Path

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

    backend: str = "ollama"  # "ollama" or "mock"
    model: str = "bge-m3"  # Ollama model name (bge-m3 for production)
    dimension: int = 1024  # Embedding vector dimension (1024 for bge-m3)
    ollama_host: str = "http://localhost:11434"  # Ollama API host
    timeout: float = 30.0  # Request timeout in seconds


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
