"""
Agent-driven reflection request records.

When the agent decides during a session that something should be reflected on
later, it calls the `request_reflection` tool. That tool enqueues a
:class:`ReflectionRequest` here. The reason is preserved and threaded into the
startup context of the next reflection job at the same level.

Idempotency: a request with the same reason inside the same hour bucket
collapses to one record (see :func:`agent_driven_run_key`).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReflectionRequestLevel(StrEnum):
    """Reflection level the agent is asking for."""

    DAILY = "daily"
    DEEP = "deep"


class ReflectionRequest(BaseModel):
    """A single agent-initiated reflection request."""

    id: UUID = Field(default_factory=uuid4)
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    level: ReflectionRequestLevel = ReflectionRequestLevel.DAILY
    reason: str = Field(min_length=1, description="Why the agent thinks this matters")
    run_key: str = Field(
        min_length=1,
        description="Idempotency key (hash of reason + hour bucket). Same key collapses.",
    )

    consumed_at: datetime | None = None
    consumed_by_reflection_event_id: UUID | None = None

    @property
    def is_consumed(self) -> bool:
        return self.consumed_at is not None

    @field_validator("reason", "run_key")
    @classmethod
    def _strip_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("field cannot be empty")
        return v.strip()

    model_config = ConfigDict(validate_assignment=True)
