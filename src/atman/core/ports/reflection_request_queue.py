"""
Port for the agent-driven reflection request queue.

The agent enqueues via :meth:`enqueue` (idempotent by `run_key`). Reflection
services consume via :meth:`take_pending` when assembling startup context for
the next run, then call :meth:`mark_consumed` once the reflection job has
durably saved.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from atman.core.models.reflection_request import ReflectionRequest, ReflectionRequestLevel


class ReflectionRequestQueue(ABC):
    """Persistent queue of agent-driven reflection requests."""

    @abstractmethod
    def enqueue(self, request: ReflectionRequest) -> ReflectionRequest:
        """
        Enqueue a new request. Idempotent by `run_key`: if a request with the
        same key already exists, return the existing one without modifying it.
        """
        ...

    @abstractmethod
    def get_by_run_key(self, run_key: str) -> ReflectionRequest | None:
        """Fetch a request by its idempotency key."""
        ...

    @abstractmethod
    def take_pending(
        self,
        *,
        level: ReflectionRequestLevel,
        limit: int | None = None,
    ) -> list[ReflectionRequest]:
        """
        Return unconsumed requests for `level`, oldest first.

        This does **not** mark them consumed. Callers must call
        :meth:`mark_consumed` after the reflection job has been persisted.
        """
        ...

    @abstractmethod
    def mark_consumed(
        self,
        request_id: UUID,
        *,
        consumed_at: datetime,
        reflection_event_id: UUID,
    ) -> ReflectionRequest:
        """
        Mark a request consumed by a specific reflection event.

        Raises:
            KeyError: if `request_id` is unknown.
            ValueError: if the request was already consumed.
        """
        ...
