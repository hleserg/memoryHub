"""
MemoryUsageLog port - tracking what memory was actually used.

Provides visibility into what memory was actually used vs merely surfaced,
giving the reflection engine data on memory effectiveness.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class UsageType(StrEnum):
    """Type of memory usage."""

    SURFACED = "surfaced"  # Memory was surfaced but not necessarily used
    ACCESSED = "accessed"  # Memory was explicitly accessed/read
    CITED = "cited"  # Memory was cited/quoted in output
    INFLUENCED = "influenced"  # Memory influenced decision/action


@dataclass
class MemoryUsageRecord:
    """Record of a single memory usage event."""

    timestamp: datetime
    session_id: UUID
    memory_type: str  # "fact" or "experience"
    memory_id: UUID
    usage_type: UsageType
    context: str  # Brief description of usage context
    metadata: dict[str, str] | None = None


class MemoryUsageLog(ABC):
    """
    Port for tracking memory usage.

    Allows the reflection engine to see what memory was actually
    used vs merely surfaced, enabling better memory management.
    """

    @abstractmethod
    def log_usage(self, record: MemoryUsageRecord) -> None:
        """
        Log a memory usage event.

        Args:
            record: The usage record to log
        """
        pass

    @abstractmethod
    def get_usage_for_session(
        self,
        session_id: UUID,
        memory_type: str | None = None,
    ) -> list[MemoryUsageRecord]:
        """
        Get all usage records for a session.

        Args:
            session_id: The session to query
            memory_type: Optional filter by memory type

        Returns:
            list[MemoryUsageRecord]: Usage records
        """
        pass

    @abstractmethod
    def get_usage_for_memory(
        self,
        memory_id: UUID,
        limit: int = 50,
    ) -> list[MemoryUsageRecord]:
        """
        Get usage history for a specific memory item.

        Args:
            memory_id: The memory item ID
            limit: Maximum records to return

        Returns:
            list[MemoryUsageRecord]: Usage history
        """
        pass

    @abstractmethod
    def get_usage_summary(
        self,
        session_id: UUID,
    ) -> dict[str, int]:
        """
        Get summary statistics for a session.

        Args:
            session_id: The session to summarize

        Returns:
            dict[str, int]: Counts by usage_type
        """
        pass
