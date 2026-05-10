"""
Atman configuration management via Pydantic Settings.

Centralizes all environment variable configuration with type validation.
"""

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
    model: str = "qwen3-embedding:1.5b"  # Ollama model name
    dimension: int = 768  # Embedding vector dimension
    ollama_host: str = "http://localhost:11434"  # Ollama API host
    timeout: float = 30.0  # Request timeout in seconds


class Settings(BaseSettings):
    """Global application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    embedding: EmbeddingSettings = EmbeddingSettings()


# Global settings instance
settings = Settings()
