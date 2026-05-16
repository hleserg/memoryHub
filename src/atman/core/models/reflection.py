"""
Domain models for Reflection Engine.

These models represent reflection processes and outputs:
- ReflectionLevel: depth of reflection (micro, daily, deep)
- ReframingNote: new perspective on existing experience (already exists in experience.py, but referenced here)
- PatternCandidate: detected behavior pattern
- ReflectionEvent: record of a reflection process
- HealthAssessment: psychological health check based on 6 Jahoda criteria
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ReflectionLevel(StrEnum):
    """
    Depth of reflection process.

    - micro: After-session reflection, updates recent narrative layer (see services)
    - daily: End-of-day reflection, looks for patterns across sessions
    - deep: Scheduled deep reflection; health assessment and proposals on events (see services)
    """

    MICRO = "micro"
    DAILY = "daily"
    DEEP = "deep"


class PatternType(StrEnum):
    """Type of detected pattern."""

    BEHAVIOR = "behavior"
    EMOTIONAL = "emotional"
    COGNITIVE = "cognitive"
    RELATIONAL = "relational"
    VALUE_BASED = "value_based"


class PatternStatus(StrEnum):
    """Status of pattern confirmation."""

    CANDIDATE = "candidate"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class PatternCandidate(BaseModel):
    """
    A detected behavior or emotional pattern.

    Patterns are discovered through reflection on multiple experiences.
    They represent recurring themes, behaviors, or emotional responses.
    """

    id: UUID = Field(default_factory=uuid4, description="Unique identifier for this pattern")
    pattern_type: PatternType = Field(description="Type of pattern detected")
    status: PatternStatus = Field(
        default=PatternStatus.CANDIDATE, description="Confirmation status of this pattern"
    )

    # Pattern description
    description: str = Field(min_length=1, description="Description of the pattern")
    examples: list[UUID] = Field(
        default_factory=list,
        description="Experience IDs that exemplify this pattern",
    )

    # Metadata
    detected_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When this pattern was detected"
    )
    detected_by: ReflectionLevel = Field(
        description="What level of reflection detected this pattern"
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Confidence in this pattern (0.0-1.0)",
    )
    schema_version: str = Field(
        default="1.0.0",
        description="Schema version for migrations and safe export/import",
    )

    # Implications
    related_values: list[str] = Field(
        default_factory=list, description="Values related to this pattern"
    )
    potential_habit: str = Field(
        default="", description="If this pattern suggests a habit, describe it here"
    )
    potential_principle: str = Field(
        default="", description="If this pattern suggests a principle, describe it here"
    )

    @field_validator("description")
    @classmethod
    def validate_not_empty(cls, v: str) -> str:
        """Ensure description is not empty."""
        if not v or not v.strip():
            raise ValueError("description cannot be empty")
        return v.strip()

    @field_validator("confidence")
    @classmethod
    def validate_confidence_range(cls, v: float) -> float:
        """Ensure confidence is in valid range."""
        if not 0.0 <= v <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        return v

    @field_validator("related_values")
    @classmethod
    def validate_string_lists(cls, v: list[str]) -> list[str]:
        """Normalize string lists."""
        return [item.strip() for item in v if item.strip()]

    model_config = ConfigDict(
        validate_assignment=True,
        json_schema_extra={
            "example": {
                "pattern_type": "behavior",
                "description": "Tendency to over-explain when uncertain",
                "examples": [],
                "detected_by": "daily",
                "confidence": 0.7,
                "potential_habit": "Over-explaining as uncertainty response",
            }
        },
    )


class ReframingNoteOutput(BaseModel):
    """
    Structured result from :meth:`~atman.core.ports.reflection.ReflectionModel.generate_reframing_note`.

    Empty ``reflection`` means the service should not persist a note.
    """

    reflection: str = Field(
        default="",
        description="Main note body; whitespace-only is treated as empty",
    )
    reflection_type: str = Field(
        default="insight",
        description="Tag stored on :class:`~atman.core.models.experience.ReframingNote`",
    )

    @field_validator("reflection", "reflection_type", mode="before")
    @classmethod
    def strip_text(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip()
        return v

    @model_validator(mode="after")
    def ensure_reflection_type_not_empty(self) -> Self:
        """Ensure reflection_type is never empty after strip; use default if needed."""
        if not self.reflection_type:
            self.reflection_type = "insight"
        return self


class PatternDetectionOutput(BaseModel):
    """
    Structured result from :meth:`~atman.core.ports.reflection.ReflectionModel.detect_pattern`.

    Empty ``description`` means no pattern; services skip persistence.
    """

    description: str = Field(default="", description="Human-readable pattern summary")
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="If set, used as PatternCandidate.confidence; else service picks a default",
    )
    potential_habit: str = Field(default="")
    potential_principle: str = Field(default="")

    @field_validator("description", "potential_habit", "potential_principle", mode="before")
    @classmethod
    def strip_optional(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip()
        return v


class NarrativeUpdateOutput(BaseModel):
    """
    Structured result from :meth:`~atman.core.ports.reflection.ReflectionModel.propose_narrative_update`.

    ``body`` is merged into the narrative (e.g. recent layer) by :class:`NarrativeRevisionService`.
    """

    body: str = Field(
        default="",
        description="Proposed narrative fragment (often recent-layer replacement content)",
    )

    @field_validator("body", mode="before")
    @classmethod
    def strip_body(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip()
        return v


class HealthCriterionOutput(BaseModel):
    """
    Structured result from :meth:`~atman.core.ports.reflection.ReflectionModel.assess_health_criterion`.
    """

    score: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)

    @field_validator("evidence", "concerns")
    @classmethod
    def normalize_lists(cls, v: list[str]) -> list[str]:
        return [item.strip() for item in v if isinstance(item, str) and item.strip()]


class JahodaCriterion(StrEnum):
    """
    Six criteria for psychological health based on Marie Jahoda's framework.

    These criteria help assess whether the agent's self-representation
    is developing in a healthy direction.
    """

    POSITIVE_SELF_ATTITUDE = "positive_self_attitude"
    GROWTH_AND_ACTUALIZATION = "growth_and_actualization"
    INTEGRATION = "integration"
    AUTONOMY = "autonomy"
    REALITY_PERCEPTION = "reality_perception"
    ENVIRONMENTAL_MASTERY = "environmental_mastery"


class CriterionAssessment(BaseModel):
    """
    Assessment of one Jahoda criterion.

    Each criterion is assessed on a scale and includes evidence and concerns.
    """

    criterion: JahodaCriterion = Field(description="Which criterion is being assessed")
    score: float = Field(
        ge=0.0,
        le=1.0,
        description="Score for this criterion (0.0 = poor, 1.0 = excellent)",
    )
    evidence: list[str] = Field(
        default_factory=list, description="Evidence supporting this assessment"
    )
    concerns: list[str] = Field(
        default_factory=list, description="Concerns or areas for improvement"
    )
    notes: str = Field(default="", description="Additional notes about this criterion")

    @field_validator("score")
    @classmethod
    def validate_score_range(cls, v: float) -> float:
        """Ensure score is in valid range."""
        if not 0.0 <= v <= 1.0:
            raise ValueError("score must be between 0.0 and 1.0")
        return v

    @field_validator("evidence", "concerns")
    @classmethod
    def validate_string_lists(cls, v: list[str]) -> list[str]:
        """Normalize string lists."""
        return [item.strip() for item in v if item.strip()]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "criterion": "positive_self_attitude",
                "score": 0.6,
                "evidence": ["Showing self-awareness", "Acknowledging limitations honestly"],
                "concerns": ["Limited experience base", "Uncertain about capabilities"],
            }
        }
    )


def _health_assessment_example_dict() -> dict[str, Any]:
    """Valid JSON-schema example: six criteria and ``overall_score`` equal to their mean."""
    criteria_json: dict[str, Any] = {}
    for jc in JahodaCriterion:
        criteria_json[jc.value] = {
            "criterion": jc.value,
            "score": 0.55,
            "evidence": ["Illustrative evidence"],
            "concerns": ["Illustrative concern"],
        }
    return {
        "criteria": criteria_json,
        "overall_score": 0.55,
        "summary": "Illustrative health snapshot (six Jahoda criteria, mean-aligned overall_score).",
        "recommendations": ["Continue honest self-reflection", "Seek diverse experiences"],
    }


class HealthAssessment(BaseModel):
    """
    Psychological health assessment based on 6 Jahoda criteria.

    This is performed during deep reflection to check if identity development
    is proceeding in a healthy direction.
    """

    id: UUID = Field(default_factory=uuid4, description="Unique identifier for this assessment")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When this assessment was performed"
    )

    # Assessments for each criterion
    criteria: dict[JahodaCriterion, CriterionAssessment] = Field(
        description="Assessment for each of the 6 criteria"
    )

    # Overall
    overall_score: float = Field(
        ge=0.0, le=1.0, description="Overall health score (average of criteria)"
    )
    summary: str = Field(default="", description="Summary of overall psychological health state")
    recommendations: list[str] = Field(
        default_factory=list, description="Recommendations for healthy development"
    )
    schema_version: str = Field(
        default="1.0.0",
        description="Schema version for migrations and safe export/import",
    )

    @field_validator("overall_score")
    @classmethod
    def validate_score_range(cls, v: float) -> float:
        """Ensure overall score is in valid range."""
        if not 0.0 <= v <= 1.0:
            raise ValueError("overall_score must be between 0.0 and 1.0")
        return v

    @field_validator("criteria")
    @classmethod
    def validate_all_criteria_present(cls, v: dict[JahodaCriterion, CriterionAssessment]) -> dict:
        """Ensure all 6 criteria are assessed."""
        required_criteria = set(JahodaCriterion)
        present_criteria = set(v.keys())

        if present_criteria != required_criteria:
            missing = required_criteria - present_criteria
            extra = present_criteria - required_criteria
            error_parts = []
            if missing:
                error_parts.append(f"missing: {missing}")
            if extra:
                error_parts.append(f"unexpected: {extra}")
            raise ValueError(f"All 6 Jahoda criteria must be assessed; {', '.join(error_parts)}")

        return v

    @field_validator("recommendations")
    @classmethod
    def validate_recommendations(cls, v: list[str]) -> list[str]:
        """Normalize recommendations."""
        return [rec.strip() for rec in v if rec.strip()]

    @model_validator(mode="after")
    def overall_score_matches_criteria_mean(self) -> Self:
        """``overall_score`` must match the arithmetic mean of the six criterion scores."""
        if not self.criteria:
            return self
        expected = sum(c.score for c in self.criteria.values()) / len(self.criteria)
        if abs(self.overall_score - expected) > 1e-5:
            raise ValueError(
                f"overall_score ({self.overall_score}) must equal the mean of criterion scores ({expected})"
            )
        return self

    model_config = ConfigDict(
        validate_assignment=True,
        json_schema_extra={
            "example": _health_assessment_example_dict(),
        },
    )


class ReflectionEvent(BaseModel):
    """
    Record of a reflection process.

    This captures what happened during a reflection session:
    what was analyzed, what patterns were found, what changes were proposed.
    """

    id: UUID = Field(default_factory=uuid4, description="Unique identifier for this event")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When this reflection occurred"
    )
    reflection_level: ReflectionLevel = Field(description="Level of this reflection")

    # What was analyzed
    experiences_analyzed: list[UUID] = Field(
        default_factory=list, description="IDs of experiences analyzed during this reflection"
    )
    identity_snapshot_id: UUID | None = Field(
        default=None,
        description=(
            "Id of the immutable :class:`~atman.core.models.identity.IdentitySnapshot` "
            "that anchored identity state for this job (never ``Identity.id``)"
        ),
    )
    reflection_run_key: str | None = Field(
        default=None,
        description="Deterministic job key for idempotent daily/deep runs (level+window+identity)",
    )

    # What was found
    patterns_detected: list[UUID] = Field(
        default_factory=list, description="IDs of patterns detected during this reflection"
    )
    reframing_notes_added: int = Field(
        default=0, ge=0, description="Number of reframing notes added"
    )
    reframing_experience_not_found_count: int = Field(
        default=0,
        ge=0,
        description="Append attempts where the target experience was missing (degraded path)",
    )
    reframing_append_storage_rejected_count: int = Field(
        default=0,
        ge=0,
        description="Append attempts refused by storage while the experience existed",
    )
    reframing_duplicate_triggered_by_count: int = Field(
        default=0,
        ge=0,
        description=(
            "Append attempts that returned DUPLICATE_TRIGGERED_BY (idempotent replay; "
            "note already present for this triggered_by)"
        ),
    )

    # What was proposed/done
    narrative_changes_proposed: str = Field(default="", description="Proposed changes to narrative")
    identity_changes_proposed: str = Field(default="", description="Proposed changes to identity")
    new_open_questions: list[str] = Field(
        default_factory=list, description="New open questions raised"
    )
    resolved_questions: list[str] = Field(
        default_factory=list, description="Open questions that were resolved"
    )

    # Health check (for deep reflection)
    health_assessment_id: UUID | None = Field(
        default=None, description="ID of health assessment if performed"
    )

    # Insights
    key_insight: str = Field(default="", description="Main insight from this reflection")
    notes: str = Field(default="", description="Additional notes about this reflection")
    schema_version: str = Field(
        default="1.0.0",
        description="Schema version for migrations and safe export/import",
    )

    @field_validator("reframing_notes_added")
    @classmethod
    def validate_non_negative(cls, v: int) -> int:
        """Ensure count is non-negative."""
        if v < 0:
            raise ValueError("reframing_notes_added cannot be negative")
        return v

    @field_validator("new_open_questions", "resolved_questions")
    @classmethod
    def validate_string_lists(cls, v: list[str]) -> list[str]:
        """Normalize string lists."""
        return [item.strip() for item in v if item.strip()]

    model_config = ConfigDict(
        validate_assignment=True,
        json_schema_extra={
            "example": {
                "reflection_level": "daily",
                "experiences_analyzed": [],
                "patterns_detected": [],
                "reframing_notes_added": 2,
                "key_insight": "I'm developing a pattern of honest uncertainty acknowledgment",
                "new_open_questions": ["How do I balance honesty with helpfulness?"],
            }
        },
    )


class ReflectionRecord(BaseModel):
    """
    PostgreSQL persistence model for reflections table.

    Maps to agent_{N}.reflections schema. This is the canonical persistent format
    for reflections (micro/daily/deep) stored in PostgreSQL.

    Schema corresponds to:
    - id: BIGSERIAL PRIMARY KEY
    - agent_id: UUID NOT NULL REFERENCES agents(id)
    - level: reflection_level NOT NULL (enum: micro, daily, deep)
    - created_at: TIMESTAMPTZ NOT NULL DEFAULT now()
    - session_id: UUID REFERENCES sessions(id) -- populated for level='micro'
    - period_start: TIMESTAMPTZ -- populated for level='daily'/'deep'
    - period_end: TIMESTAMPTZ -- populated for level='daily'/'deep'
    - content: TEXT NOT NULL -- the reflection itself (generated by LLM)
    - summary: TEXT -- short title/summary
    - experience_refs: UUID[] NOT NULL DEFAULT '{}' -- experiences analyzed
    - reframing_note_ids: UUID[] NOT NULL DEFAULT '{}' -- reframing notes created
    - model_provider: TEXT -- 'ollama', 'anthropic', etc.
    - model_name: TEXT -- e.g. 'qwen3.5:9b'
    - schema_version: INTEGER NOT NULL DEFAULT 1
    - metadata: JSONB NOT NULL DEFAULT '{}'
    """

    # Primary key (BIGSERIAL in Postgres, int in Python after retrieval)
    id: int | None = Field(default=None, description="Database ID (BIGSERIAL); None before INSERT")

    # Core fields
    agent_id: UUID = Field(description="Agent this reflection belongs to")
    level: ReflectionLevel = Field(description="Reflection level: micro/daily/deep")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When this reflection was created",
    )

    # Session context (for micro reflections)
    session_id: UUID | None = Field(
        default=None,
        description="Session ID (populated only for level='micro', NULL for daily/deep)",
    )

    # Time period context (for daily/deep reflections)
    period_start: datetime | None = Field(
        default=None,
        description="Start of period analyzed (populated for level='daily'/'deep', NULL for micro)",
    )
    period_end: datetime | None = Field(
        default=None,
        description="End of period analyzed (populated for level='daily'/'deep', NULL for micro)",
    )

    # Content
    content: str = Field(
        min_length=1, description="The reflection text itself (generated by reflection model)"
    )
    summary: str | None = Field(default=None, description="Optional short title/summary")

    # References
    experience_refs: list[UUID] = Field(
        default_factory=list, description="UUIDs of experiences analyzed in this reflection"
    )
    reframing_note_ids: list[UUID] = Field(
        default_factory=list,
        description="UUIDs of reframing_notes created by this reflection",
    )

    # Model metadata (for traceability)
    model_provider: str | None = Field(
        default=None, description="LLM provider: 'ollama', 'anthropic', etc."
    )
    model_name: str | None = Field(default=None, description="Specific model: e.g. 'qwen3.5:9b'")

    # Schema versioning and metadata
    schema_version: int = Field(
        default=1, ge=1, description="Schema version for migrations (default 1)"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata (JSONB in PostgreSQL)"
    )

    @field_validator("content")
    @classmethod
    def validate_content_not_empty(cls, v: str) -> str:
        """Ensure content is not empty or whitespace-only."""
        if not v or not v.strip():
            raise ValueError("content cannot be empty")
        return v.strip()

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version_positive(cls, v: int) -> int:
        """Ensure schema_version is positive."""
        if v < 1:
            raise ValueError("schema_version must be >= 1")
        return v

    @field_validator("experience_refs", "reframing_note_ids")
    @classmethod
    def validate_uuid_lists(cls, v: list[UUID]) -> list[UUID]:
        """Ensure UUID lists contain valid UUIDs."""
        return list(v)  # Pydantic will validate UUID type automatically

    model_config = ConfigDict(
        validate_assignment=True,
        json_schema_extra={
            "example": {
                "agent_id": "123e4567-e89b-12d3-a456-426614174000",
                "level": "micro",
                "session_id": "123e4567-e89b-12d3-a456-426614174001",
                "content": "Session went well. User was collaborative, I maintained clarity.",
                "summary": "Positive collaborative session",
                "experience_refs": [],
                "reframing_note_ids": [],
                "model_provider": "ollama",
                "model_name": "qwen3.5:9b",
                "schema_version": 1,
                "metadata": {},
            }
        },
    )
