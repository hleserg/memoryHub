"""
Adapters for reflection engine components.
"""

from atman.adapters.reflection.mock_reflection_model import MockReflectionModel
from atman.adapters.reflection.ollama_reflection_model import OllamaReflectionModel

__all__ = ["MockReflectionModel", "OllamaReflectionModel"]
