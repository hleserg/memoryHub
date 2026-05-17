"""Pydantic models for Affect Detector."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from atman.core.models.experience import EmotionalDepth


class TriggerReason(StrEnum):
    """Why a key_moment row was emitted by the detector."""

    ANOMALY = "anomaly"
    RANDOM_SAMPLE = "random_sample"
    SELF_REPORT = "self_report"
    DIVERGENCE = "divergence"
    EMPHASIS = "emphasis"
    STRUCTURAL_MARKER = "structural_marker"
    LINGUISTIC = "linguistic"


class AffectMetrics(BaseModel):
    """Eight behavioural floats plus sincerity (int) computed from text."""

    nrc_valence: float = Field(description="NRC positive minus negative density signal")
    hedge_density: float = Field(description="Hedge markers per token")
    length_z: float = Field(description="Character-count z-score vs rolling baseline")
    question_tail_density: float = Field(description="Question marks in last 20% of text")
    self_reference_density: float = Field(description="Self-reference markers per token")
    disclaimer_density: float = Field(description="Contrastive / hedge conjunctions per token")
    negation_adjusted_valence: float = Field(
        description="Valence after negation-window inversion heuristic"
    )
    emotion_lexical_energy: float = Field(
        description="L2 energy of primary emotion channels (excl. positive/negative aggregates)"
    )
    sincerity_score: int = Field(
        ge=-5,
        le=5,
        description="Heuristic sincerity score (≤0 sceptical, 1–2 mixed, ≥3 sincere)",
    )


class AffectRecord(BaseModel):
    """In-memory result of a detector pass (also embedded in KeyMoment metadata)."""

    trigger_reason: TriggerReason
    tags: list[str] = Field(default_factory=list)
    says_writes: dict[str, Any] = Field(default_factory=dict)
    demonstrates_thinks: dict[str, Any] | None = None
    divergence_score: float | None = None


class AgentMemoryReport(BaseModel):
    """Structured self-report from the agent for divergence + enrichment."""

    content: str | None = Field(
        default=None,
        description="Optional utterance text; objective layer skipped when None",
    )
    self_reported_emotions: list[str] = Field(default_factory=list)
    emotional_valence: float = Field(ge=-1.0, le=1.0)
    emotional_intensity: float = Field(ge=0.0, le=1.0)
    emotional_depth: EmotionalDepth | None = Field(
        default=None,
        description="Depth for KeyMoment.how_i_felt; defaults to MEANINGFUL in the detector when omitted",
    )
    tags: list[str] = Field(default_factory=list)
    why_it_matters: str | None = None
