"""
Port for the pending human review inbox.

Reflection enqueues a review item when it is not confident enough to apply a
change on its own. The runner picks the top unresolved items at session start
and surfaces them to the human. A `resolve_pending_review` tool, callable by
the agent during a session, records the decision and links any resulting
self-applied change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from uuid import UUID

from atman.core.models.pending_human_review import (
    PendingReview,
    PendingReviewDraft,
    PendingReviewKind,
    PendingReviewResolution,
)


class PendingHumanReviewInbox(ABC):
    """Storage and lifecycle for `PendingReview` items."""

    @abstractmethod
    def enqueue(self, draft: PendingReviewDraft) -> PendingReview:
        """Create a new pending review item from a draft."""
        ...

    @abstractmethod
    def get(self, review_id: UUID) -> PendingReview | None:
        """Fetch a single record by id."""
        ...

    @abstractmethod
    def list_unresolved(
        self,
        *,
        kind: PendingReviewKind | None = None,
        limit: int | None = None,
    ) -> list[PendingReview]:
        """List unresolved items, ordered by priority (high first), then oldest first."""
        ...

    @abstractmethod
    def resolve(
        self,
        review_id: UUID,
        *,
        resolution: PendingReviewResolution,
        note: str,
        resolved_at: datetime,
        applied_change_id: UUID | None = None,
    ) -> PendingReview:
        """
        Mark a review item resolved.

        Raises:
            KeyError: if `review_id` is unknown.
            ValueError: if already resolved.
        """
        ...
