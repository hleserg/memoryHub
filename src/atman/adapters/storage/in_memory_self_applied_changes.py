"""In-memory adapter for `SelfAppliedChangeStore`."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from atman.core.models import SelfAppliedChange, SelfChangeActor, SelfChangeTargetKind
from atman.core.ports.self_applied_changes import SelfAppliedChangeStore


class InMemorySelfAppliedChangeStore(SelfAppliedChangeStore):
    """Dict-backed store. Suitable for tests and prototyping."""

    def __init__(self) -> None:
        self._records: dict[UUID, SelfAppliedChange] = {}

    def save(self, change: SelfAppliedChange) -> None:
        if change.id in self._records:
            raise ValueError(f"self_applied_change {change.id} already saved")
        self._records[change.id] = change

    def get(self, change_id: UUID) -> SelfAppliedChange | None:
        return self._records.get(change_id)

    def list(
        self,
        *,
        actor: SelfChangeActor | None = None,
        target_kind: SelfChangeTargetKind | None = None,
        since: datetime | None = None,
        only_active: bool = False,
        limit: int | None = None,
    ) -> list[SelfAppliedChange]:
        rows = list(self._records.values())
        if actor is not None:
            rows = [r for r in rows if r.actor == actor]
        if target_kind is not None:
            rows = [r for r in rows if r.target_kind == target_kind]
        if since is not None:
            rows = [r for r in rows if r.applied_at >= since]
        if only_active:
            rows = [r for r in rows if r.is_active]
        rows.sort(key=lambda r: r.applied_at, reverse=True)
        if limit is not None:
            rows = rows[:limit]
        return rows

    def mark_reverted(
        self,
        change_id: UUID,
        *,
        reverted_at: datetime,
        reason: str,
        reverted_by_change_id: UUID | None = None,
    ) -> SelfAppliedChange:
        existing = self._records.get(change_id)
        if existing is None:
            raise KeyError(f"self_applied_change {change_id} not found")
        if existing.reverted_at is not None:
            raise ValueError(f"self_applied_change {change_id} already reverted")
        updated = existing.model_copy(
            update={
                "reverted_at": reverted_at,
                "reverted_reason": reason,
                "reverted_by_change_id": reverted_by_change_id,
            }
        )
        self._records[change_id] = updated
        return updated
