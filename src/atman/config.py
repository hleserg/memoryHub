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

    backend: str = "mock"  # "ollama" or "mock"
    model: str = "qwen3-embedding:4b"  # Ollama model name
    dimension: int = 2560  # Embedding vector dimension
    ollama_host: str = "http://localhost:11434"  # Ollama API host
    timeout: float = 30.0  # Request timeout in seconds


class MemorySettings(BaseModel):
    """Factual memory backend selection.

    Default is ``file`` for CLI and local use. Production can set
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
    memory: MemorySettings = MemorySettings()


# Global settings instance
settings = Settings()


def build_memory_backend():
    """Instantiate the factual memory backend selected in config.memory.backend."""
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
