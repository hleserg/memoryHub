"""In-memory implementation of :class:`DivergenceEventStore`."""

from __future__ import annotations

import threading
from datetime import datetime
from uuid import UUID

from typing_extensions import override

from atman.core.models.validation import DivergenceEvent
from atman.core.ports.divergence_events import DivergenceEventStore


class InMemoryDivergenceEventStore(DivergenceEventStore):
    """Thread-safe in-memory store; suitable for tests and local runs."""

    def __init__(self) -> None:
        self._events: dict[UUID, DivergenceEvent] = {}
        self._lock = threading.Lock()

    @override
    def write_event(self, event: DivergenceEvent) -> DivergenceEvent:
        with self._lock:
            self._events[event.id] = event
            return event

    @override
    def list_in_range(
        self,
        agent_id: UUID,
        start: datetime,
        end: datetime,
    ) -> list[DivergenceEvent]:
        with self._lock:
            out = [
                e
                for e in self._events.values()
                if e.agent_id == agent_id and start <= e.created_at <= end
            ]
        out.sort(key=lambda e: (e.created_at, str(e.id)))
        return out
