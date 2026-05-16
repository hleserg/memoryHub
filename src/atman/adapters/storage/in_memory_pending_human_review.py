"""In-memory adapter for `PendingHumanReviewInbox`."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from atman.core.models.pending_human_review import (
    PendingReview,
    PendingReviewDraft,
    PendingReviewKind,
    PendingReviewPriority,
    PendingReviewResolution,
)
from atman.core.ports.pending_human_review import PendingHumanReviewInbox


class InMemoryPendingHumanReviewInbox(PendingHumanReviewInbox):
    """Dict-backed inbox. Suitable for tests and prototyping."""

    def __init__(self) -> None:
        self._items: dict[UUID, PendingReview] = {}

    def enqueue(self, draft: PendingReviewDraft) -> PendingReview:
        review = PendingReview(
            created_by=draft.created_by,
            reflection_event_id=draft.reflection_event_id,
            kind=draft.kind,
            question=draft.question,
            context=dict(draft.context),
            priority=draft.priority,
        )
        self._items[review.id] = review
        return review

    def get(self, review_id: UUID) -> PendingReview | None:
        return self._items.get(review_id)

    def list_unresolved(
        self,
        *,
        kind: PendingReviewKind | None = None,
        limit: int | None = None,
    ) -> list[PendingReview]:
        rows = [r for r in self._items.values() if not r.is_resolved]
        if kind is not None:
            rows = [r for r in rows if r.kind == kind]

        def priority_rank(item: PendingReview) -> int:
            return 0 if item.priority == PendingReviewPriority.HIGH else 1

        rows.sort(key=lambda r: (priority_rank(r), r.created_at))
        if limit is not None:
            rows = rows[:limit]
        return rows

    def resolve(
        self,
        review_id: UUID,
        *,
        resolution: PendingReviewResolution,
        note: str,
        resolved_at: datetime,
        applied_change_id: UUID | None = None,
    ) -> PendingReview:
        existing = self._items.get(review_id)
        if existing is None:
            raise KeyError(f"pending_human_review {review_id} not found")
        if existing.is_resolved:
            raise ValueError(f"pending_human_review {review_id} already resolved")
        updated = existing.model_copy(
            update={
                "resolved_at": resolved_at,
                "resolution": resolution,
                "resolution_note": note,
                "applied_change_id": applied_change_id,
            }
        )
        self._items[review_id] = updated
        return updated
