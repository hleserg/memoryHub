"""
Memory adapters для Atman.
"""

from atman.adapters.memory.file_backend import FileBackend
from atman.adapters.memory.in_memory_backend import InMemoryBackend

__all__ = ["FileBackend", "InMemoryBackend"]
