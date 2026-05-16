"""
Port for persisting self-applied identity and narrative changes.

Each `SelfAppliedChange` records a change reflection made on its own. The store
exposes save/list/get and a `mark_reverted` operation so reverts are recorded
as state on the original entry rather than as deletions.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from atman.core.models import SelfAppliedChange, SelfChangeActor, SelfChangeTargetKind


class SelfAppliedChangeStore(ABC):
    """Storage for `SelfAppliedChange` audit records."""

    @abstractmethod
    def save(self, change: SelfAppliedChange) -> None:
        """Persist a new self-applied change. Implementations must reject duplicates by id."""
        ...

    @abstractmethod
    def get(self, change_id: UUID) -> SelfAppliedChange | None:
        """Fetch a single record by id."""
        ...

    @abstractmethod
    def list(
        self,
        *,
        actor: SelfChangeActor | None = None,
        target_kind: SelfChangeTargetKind | None = None,
        since: datetime | None = None,
        only_active: bool = False,
        limit: int | None = None,
    ) -> list[SelfAppliedChange]:
        """List records, newest first, optionally filtered."""
        ...

    @abstractmethod
    def mark_reverted(
        self,
        change_id: UUID,
        *,
        reverted_at: datetime,
        reason: str,
        reverted_by_change_id: UUID | None = None,
    ) -> SelfAppliedChange:
        """
        Mark a previously-applied change as reverted.

        Raises:
            KeyError: if `change_id` is unknown
            ValueError: if the change has already been reverted
        """
        ...
