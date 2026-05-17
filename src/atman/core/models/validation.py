"""Domain models for memory validation findings and divergence events."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class FindingSeverity(StrEnum):
    info = "info"
    warning = "warning"
    critical = "critical"


class FindingType(StrEnum):
    orphan_entity = "orphan_entity"
    similar_entities = "similar_entities"
    stale_moment = "stale_moment"
    quality_metric = "quality_metric"
    embedding_missing = "embedding_missing"
    # Async pipeline signals surfaced as findings for Reflection triage (R8).
    pending_structured_markers = "pending_structured_markers"
    analysis_failed = "analysis_failed"
    affect_detector_silent = "affect_detector_silent"
    # HLE-31: Level-C psychological quality metrics. Emitted by
    # MemoryGuardian.scan_quality_metrics over a sliding window.
    divergence_pattern = "divergence_pattern"
    stance_formation_too_fast = "stance_formation_too_fast"
    other = "other"


class ResolutionStatus(StrEnum):
    fixed = "fixed"
    ignored = "ignored"
    escalated = "escalated"
    # R8/§10: Reflection cannot self-heal critical pipeline failures; it
    # records that human/operator attention is needed.
    requires_attention = "requires_attention"


class ValidationFinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    agent_id: UUID
    finding_type: FindingType
    severity: FindingSeverity
    target_table: str
    target_id: UUID
    details: dict[str, Any] = Field(default_factory=dict)
    detected_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    detected_by: str
    resolution: ResolutionStatus | None = None
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    resolution_note: str | None = None

    @property
    def is_resolved(self) -> bool:
        """True if the finding has been given a resolution status."""
        return self.resolution is not None


class DivergenceType(StrEnum):
    thinking_suppression = "thinking_suppression"
    principle_invocation_in_thinking = "principle_invocation_in_thinking"
    message_entity_gap = "message_entity_gap"
    cognitive_load_spike = "cognitive_load_spike"
    other = "other"


class DivergenceSeverity(StrEnum):
    trace = "trace"
    notable = "notable"
    significant = "significant"
    rupture = "rupture"


class DivergenceEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    agent_id: UUID
    session_id: UUID | None = None
    key_moment_id: UUID | None = None
    divergence_type: DivergenceType
    severity: DivergenceSeverity
    thinking_layer: dict[str, Any] | None = None
    message_layer: dict[str, Any] | None = None
    action_layer: dict[str, Any] | None = None
    gliner_signals: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
