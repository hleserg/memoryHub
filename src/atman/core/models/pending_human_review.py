"""
Pending human review queue.

When reflection decides on its own that an identity/narrative change should be
made but is not confident enough to apply it, it enqueues a `PendingReview`
here. The agent runner, on the next interactive session, surfaces top items as
the first system message so the human can decide.

This is the bridge between reflection's "I'm not sure" and the next live
conversation. It is intentionally a queue, not a request-response RPC:
reflection writes and continues; the human picks up when convenient.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PendingReviewKind(StrEnum):
    """What kind of decision reflection needs help with."""

    IDENTITY_CHANGE_DOUBT = "identity_change_doubt"
    NARRATIVE_CHANGE_DOUBT = "narrative_change_doubt"
    HIGH_SALIENCE_JUDGEMENT = "high_salience_judgement"


class PendingReviewPriority(StrEnum):
    """Priority hint for the runner pick-up logic."""

    NORMAL = "normal"
    HIGH = "high"


class PendingReviewResolution(StrEnum):
    """How a pending review was resolved."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    MODIFIED = "modified"
    DISMISSED = "dismissed"


class PendingReviewDraft(BaseModel):
    """Input used by callers (e.g. reflection) to enqueue a new review item."""

    created_by: str = Field(
        min_length=1,
        description="Source actor, e.g. 'reflection_daily' / 'reflection_deep'",
    )
    reflection_event_id: UUID | None = None
    kind: PendingReviewKind
    question: str = Field(min_length=1, description="The decision the human is asked to make")
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="Proposed change, supporting moments, alternatives — anything the human needs",
    )
    priority: PendingReviewPriority = PendingReviewPriority.NORMAL

    @field_validator("created_by", "question")
    @classmethod
    def _strip_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("field cannot be empty")
        return v.strip()

    model_config = ConfigDict(frozen=True)


class PendingReview(BaseModel):
    """A pending review item: a question reflection asks the human."""

    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    created_by: str
    reflection_event_id: UUID | None = None
    kind: PendingReviewKind
    question: str
    context: dict[str, Any] = Field(default_factory=dict)
    priority: PendingReviewPriority = PendingReviewPriority.NORMAL

    resolved_at: datetime | None = None
    resolution: PendingReviewResolution | None = None
    resolution_note: str | None = None
    applied_change_id: UUID | None = Field(
        default=None,
        description="If resolution produced a SelfAppliedChange, link it here",
    )

    @property
    def is_resolved(self) -> bool:
        return self.resolved_at is not None

    model_config = ConfigDict(validate_assignment=True)
