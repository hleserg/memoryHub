"""
InMemoryUsageLog - in-memory implementation of MemoryUsageLog.

Simple in-memory storage for usage records.
Not persistent - suitable for testing and short-lived sessions.
"""

from typing import override
from uuid import UUID

from atman.core.ports.memory_usage_log import MemoryUsageLog, MemoryUsageRecord, UsageType


class InMemoryUsageLog(MemoryUsageLog):
    """
    In-memory implementation of MemoryUsageLog.

    Stores usage records in memory. Data is lost when process ends.
    Suitable for testing and prototyping.
    """

    def __init__(self) -> None:
        """Initialize empty usage log."""
        self._records: list[MemoryUsageRecord] = []

    @override
    def log_usage(self, record: MemoryUsageRecord) -> None:
        """Log a memory usage event."""
        self._records.append(record)

    @override
    def get_usage_for_session(
        self,
        session_id: UUID,
        memory_type: str | None = None,
    ) -> list[MemoryUsageRecord]:
        """Get all usage records for a session."""
        results = [
            r for r in self._records
            if r.session_id == session_id
        ]
        if memory_type:
            results = [r for r in results if r.memory_type == memory_type]
        return results

    @override
    def get_usage_for_memory(
        self,
        memory_id: UUID,
        limit: int = 50,
    ) -> list[MemoryUsageRecord]:
        """Get usage history for a specific memory item."""
        results = [
            r for r in self._records
            if r.memory_id == memory_id
        ]
        # Return most recent first
        return results[-limit:][::-1]

    @override
    def get_usage_summary(
        self,
        session_id: UUID,
    ) -> dict[str, int]:
        """Get summary statistics for a session."""
        summary: dict[str, int] = {}
        for record in self._records:
            if record.session_id == session_id:
                key = record.usage_type.value
                summary[key] = summary.get(key, 0) + 1
        return summary

    def clear(self) -> None:
        """Clear all records. Useful for testing."""
        self._records.clear()

    def count(self) -> int:
        """Return total number of records."""
        return len(self._records)
