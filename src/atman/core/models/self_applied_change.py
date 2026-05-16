"""
Self-applied change audit records.

When reflection (Daily or Deep) decides on its own that an identity or narrative
revision should be made, it goes through `apply_self_change` / `apply_self_layer_update`
APIs on IdentityService and NarrativeRevisionService. Each such application is
recorded as a `SelfAppliedChange` so it can be reviewed and reverted later.

This is a separate path from `GovernanceDecision` (which represents human-approved
review): self-applied changes are reflection's prerogative but must always carry
rationale, supporting moment ids, and a before-snapshot so they remain reversible.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SelfChangeActor(StrEnum):
    """Who initiated a self-applied change."""

    REFLECTION_DAILY = "reflection_daily"
    REFLECTION_DEEP = "reflection_deep"
    HUMAN_VIA_REFLECTION_REVIEW = "human_via_reflection_review"


class SelfChangeTargetKind(StrEnum):
    """What aspect of identity or narrative was changed."""

    IDENTITY_CORE_VALUE = "identity_core_value"
    IDENTITY_PRINCIPLE = "identity_principle"
    IDENTITY_HABIT = "identity_habit"
    IDENTITY_GOAL = "identity_goal"
    IDENTITY_OPEN_QUESTION = "identity_open_question"
    IDENTITY_SELF_DESCRIPTION = "identity_self_description"
    NARRATIVE_CORE_LAYER = "narrative_core_layer"
    NARRATIVE_RECENT_LAYER = "narrative_recent_layer"


class SelfChangeSource(BaseModel):
    """
    Provenance of a self-applied change.

    All four fields are required: a self-applied change without rationale,
    confidence statement, or supporting moments is not auditable and the
    service-layer API will refuse it.
    """

    actor: SelfChangeActor = Field(description="Which reflection level produced this change")
    reflection_event_id: UUID = Field(description="ReflectionEvent that produced this change")
    rationale: str = Field(min_length=1, description="Why this change is being applied")
    confidence_self_assessment: str = Field(
        min_length=1,
        description="Reflection's own assessment of confidence (text, not a number)",
    )
    based_on_moment_ids: list[UUID] = Field(
        default_factory=list,
        description="KeyMoment ids that support this change",
    )

    @field_validator("rationale", "confidence_self_assessment")
    @classmethod
    def _strip_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("field cannot be empty")
        return v.strip()

    model_config = ConfigDict(frozen=True)


class SelfAppliedChange(BaseModel):
    """
    Audit record of an identity or narrative change that reflection applied itself.

    Before-snapshot is mandatory and is the basis for revert: reverting a change
    is itself a new write that restores `before_snapshot` to the target.
    """

    id: UUID = Field(default_factory=uuid4)
    applied_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    actor: SelfChangeActor
    reflection_event_id: UUID
    target_kind: SelfChangeTargetKind

    target_ref: str = Field(
        description=(
            "Stable reference within the target. For list-shaped fields this is the "
            "added item's identifier or natural key (e.g. principle id, value name). "
            "For scalar fields it is the field name."
        )
    )

    before_snapshot: dict[str, Any] = Field(
        description="Target's prior state (subset relevant for revert)"
    )
    after_snapshot: dict[str, Any] = Field(
        description="Target's new state (subset relevant for revert)"
    )

    rationale: str = Field(min_length=1)
    confidence_self_assessment: str = Field(min_length=1)
    based_on_moment_ids: list[UUID] = Field(default_factory=list)

    reverted_at: datetime | None = None
    reverted_reason: str | None = None
    reverted_by_change_id: UUID | None = Field(
        default=None,
        description="If a revert produced a new SelfAppliedChange, link back here",
    )

    @property
    def is_active(self) -> bool:
        """A change is active if it has not been reverted."""
        return self.reverted_at is None

    model_config = ConfigDict(validate_assignment=True)
