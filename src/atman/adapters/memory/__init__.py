"""
Memory adapters для Atman.
"""

from atman.adapters.memory.in_memory_backend import InMemoryBackend
from atman.adapters.memory.file_backend import FileBackend

__all__ = ["InMemoryBackend", "FileBackend"]
