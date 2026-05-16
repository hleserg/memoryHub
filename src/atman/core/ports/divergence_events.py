"""Port: DivergenceEventStore — persist/query thinking↔message↔action divergences.

Implementation note (R6): the legacy plan was to extend ``StateStore`` with
``list_divergence_events`` directly, but that broadens an already-large
contract. A dedicated port keeps the surface focused — adapters can live
alongside the other in-memory + postgres pairs without touching every
``StateStore`` implementation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from atman.core.models.validation import DivergenceEvent


class DivergenceEventStore(ABC):
    """Append-only store of detected divergence events."""

    @abstractmethod
    def write_event(self, event: DivergenceEvent) -> DivergenceEvent:
        """Persist a divergence event. Idempotent by ``event.id``."""

    @abstractmethod
    def list_in_range(
        self,
        agent_id: UUID,
        start: datetime,
        end: datetime,
    ) -> list[DivergenceEvent]:
        """Return events for ``agent_id`` with ``created_at`` in ``[start, end]``."""
