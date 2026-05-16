"""In-memory adapter for :class:`ReflectionRequestQueue`."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from atman.core.models.reflection_request import ReflectionRequest, ReflectionRequestLevel
from atman.core.ports.reflection_request_queue import ReflectionRequestQueue


class InMemoryReflectionRequestQueue(ReflectionRequestQueue):
    """Dict-backed queue. Suitable for tests and prototyping."""

    def __init__(self) -> None:
        self._by_id: dict[UUID, ReflectionRequest] = {}
        self._by_run_key: dict[str, UUID] = {}

    def enqueue(self, request: ReflectionRequest) -> ReflectionRequest:
        existing_id = self._by_run_key.get(request.run_key)
        if existing_id is not None:
            return self._by_id[existing_id]
        self._by_id[request.id] = request
        self._by_run_key[request.run_key] = request.id
        return request

    def get_by_run_key(self, run_key: str) -> ReflectionRequest | None:
        rid = self._by_run_key.get(run_key)
        return self._by_id.get(rid) if rid is not None else None

    def take_pending(
        self,
        *,
        level: ReflectionRequestLevel,
        limit: int | None = None,
    ) -> list[ReflectionRequest]:
        rows = [
            r
            for r in self._by_id.values()
            if r.level == level and not r.is_consumed
        ]
        rows.sort(key=lambda r: r.requested_at)
        if limit is not None:
            rows = rows[:limit]
        return rows

    def mark_consumed(
        self,
        request_id: UUID,
        *,
        consumed_at: datetime,
        reflection_event_id: UUID,
    ) -> ReflectionRequest:
        existing = self._by_id.get(request_id)
        if existing is None:
            raise KeyError(f"reflection_request {request_id} not found")
        if existing.is_consumed:
            raise ValueError(f"reflection_request {request_id} already consumed")
        updated = existing.model_copy(
            update={
                "consumed_at": consumed_at,
                "consumed_by_reflection_event_id": reflection_event_id,
            }
        )
        self._by_id[request_id] = updated
        return updated
