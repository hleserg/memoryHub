"""
Adapters for reflection engine components.
"""

import os

from atman.adapters.reflection.mock_reflection_model import MockReflectionModel
from atman.core.ports.reflection import ReflectionModel

__all__ = [
    "MockReflectionModel",
    "get_reflection_model",
]


def get_reflection_model() -> ReflectionModel:
    """
    Factory for reflection model based on ATMAN_REFLECTION_BACKEND env var.

    Returns:
        ReflectionModel instance (OpenAI-compatible, Anthropic, or Mock)

    Supported backends:
        - "openai" (default): OpenAI-compatible endpoint via OpenAILLMConfig
        - "anthropic": Anthropic Claude via AnthropicLLMConfig
        - "mock": Deterministic mock for testing
    """
    backend = os.getenv("ATMAN_REFLECTION_BACKEND", "openai")

    if backend == "openai":
        from atman.adapters.reflection.openai_reflection_model import OpenAIReflectionModel

        return OpenAIReflectionModel()
    elif backend == "anthropic":
        raise NotImplementedError("Anthropic backend not yet implemented. Use 'openai' or 'mock'.")
    elif backend == "mock":
        return MockReflectionModel()
    else:
        raise ValueError(
            f"Unknown reflection backend: {backend!r}. Valid options: 'openai', 'anthropic', 'mock'"
        )
