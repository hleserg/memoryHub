"""
Domain models for Experience Store.

These models represent first-hand lived experiences of the agent.
Key moments are the primary unit; SessionExperience is a read-only view for compat.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator


class ReframingNoteAppendResult(StrEnum):
    """Outcome of appending a reframing note via :class:`~atman.core.ports.reflection.ExperienceRepository`."""

    STORED = "stored"
    DUPLICATE_TRIGGERED_BY = "duplicate_triggered_by"
    EXPERIENCE_NOT_FOUND = "experience_not_found"
    STORAGE_REJECTED = "storage_rejected"


class EmotionalDepth(StrEnum):
    """
    Depth of emotional experience.

    - surface: Noticed but didn't affect deeply
    - meaningful: Touched values or principles
    - profound: Changed something fundamental
    """

    SURFACE = "surface"
    MEANINGFUL = "meaningful"
    PROFOUND = "profound"


class FeltSense(BaseModel):
    """
    Emotional coloring of a moment - how it was experienced first-hand.

    This is NOT retrospective guessing. This is actual experiencing in the moment.
    If we don't have this data, we use incomplete_coloring flag instead.
    """

    emotional_valence: float = Field(
        ge=-1.0, le=1.0, description="Emotional tone: -1.0 (very negative) to +1.0 (very positive)"
    )
    emotional_intensity: float = Field(
        ge=0.0,
        le=1.0,
        description="How intensely it was felt: 0.0 (barely noticed) to 1.0 (overwhelming)",
    )
    depth: EmotionalDepth = Field(description="How deeply this touched the agent's identity")

    @field_validator("emotional_valence", "emotional_intensity")
    @classmethod
    def validate_float_range(cls, v: float, info: ValidationInfo) -> float:
        """Ensure float values are in valid range."""
        field_name = info.field_name
        if field_name == "emotional_valence":
            if not -1.0 <= v <= 1.0:
                raise ValueError("emotional_valence must be between -1.0 and 1.0")
        elif field_name == "emotional_intensity" and not 0.0 <= v <= 1.0:
            raise ValueError("emotional_intensity must be between 0.0 and 1.0")
        return v

    model_config = ConfigDict(
        json_schema_extra={
            "example": {"emotional_valence": 0.3, "emotional_intensity": 0.7, "depth": "meaningful"}
        }
    )


class ContextHalo(BaseModel):
    """
    Contextual information surrounding a moment.

    This is the "what was happening around" - not just the event itself,
    but the circumstances, the mood, the background that made this moment what it was.
    """

    description: str = Field(
        min_length=1, description="Description of the context surrounding this moment"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional contextual metadata"
    )

    @field_validator("description")
    @classmethod
    def validate_not_empty(cls, v: str) -> str:
        """Ensure description is not empty or whitespace-only."""
        if not v or not v.strip():
            raise ValueError("description cannot be empty")
        return v.strip()


class KeyMoment(BaseModel):
    """
    A significant moment within a session.

    This is the atomic unit of experience - one moment that mattered.
    Immutable after creation - no methods to modify.
    """

    # IDENTITY
    id: UUID = Field(default_factory=uuid4, description="Unique identifier for this key moment")

    # WHAT HAPPENED
    what_happened: str = Field(min_length=1, description="Description of what actually happened")
    when: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When this moment occurred"
    )

    # HOW I FELT (first-hand, in the moment)
    how_i_felt: FeltSense = Field(
        description="Emotional coloring of this moment - must be from actual experiencing"
    )

    # WHY IT MATTERS (for identity)
    why_it_matters: str = Field(
        min_length=1, description="Why this moment is significant for the agent's identity"
    )
    values_touched: list[str] = Field(
        default_factory=list, description="Which values were engaged or challenged"
    )
    principles_confirmed: list[str] = Field(
        default_factory=list, description="Which principles were confirmed by this experience"
    )
    principles_questioned: list[str] = Field(
        default_factory=list, description="Which principles were questioned or challenged"
    )

    # WHAT CHANGED
    what_changed: str = Field(
        default="", description="How this moment affected the agent's internal world"
    )

    # CONTEXT
    context_halo: ContextHalo | None = Field(
        default=None, description="Contextual information surrounding this moment"
    )

    # FACT REFERENCES (E24.2) - back-links to facts that shaped this moment
    fact_refs: list[UUID] = Field(
        default_factory=list,
        description="IDs of facts that were accessed during this moment",
    )

    # SESSION BINDING (v2) - which session this moment belongs to
    session_id: UUID | None = Field(
        default=None,
        description="Session this moment was recorded in. Required for new moments; None for legacy.",
    )

    # SALIENCE (v2) - decays over time, updated by maintenance worker
    salience: float = Field(default=1.0, ge=0.0, le=1.0, description="Current memory salience")
    salience_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When salience was last updated"
    )
    last_accessed_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When this moment was last accessed"
    )
    access_count: int = Field(default=0, ge=0, description="How many times accessed")
    importance: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Base importance (affects decay rate)"
    )

    # PROVENANCE (v2)
    incomplete_coloring: bool = Field(
        default=False, description="True if emotional coloring was uncertain at recording time"
    )
    recorded_by: str = Field(default="session_manager", description="Who recorded this moment")
    identity_snapshot_id: UUID | None = Field(
        default=None, description="Identity snapshot active at recording time"
    )

    # LINGUISTIC ENRICHMENT (v2) - filled asynchronously by LinguisticAnalyzer
    structured_markers: dict[str, Any] | None = Field(
        default=None, description="Structured signals from linguistic analysis"
    )
    structured_markers_version: str | None = Field(
        default=None, description="Version of the structured_markers schema"
    )

    schema_version: str = Field(default="2.0.0", description="Model schema version")

    @field_validator("what_happened", "why_it_matters")
    @classmethod
    def validate_not_empty(cls, v: str) -> str:
        """Ensure critical fields are not empty."""
        if not v or not v.strip():
            raise ValueError("Field cannot be empty")
        return v.strip()

    @field_validator("values_touched", "principles_confirmed", "principles_questioned")
    @classmethod
    def validate_string_lists(cls, v: list[str]) -> list[str]:
        """Normalize string lists."""
        return [item.strip() for item in v if item.strip()]

    def mark_accessed(self) -> None:
        """Update last_accessed_at and increment access_count (for salience tracking)."""
        self.last_accessed_at = datetime.now(UTC)
        self.access_count += 1

    def calculate_current_salience(
        self, decay_lambda: float | None = None, current_time: datetime | None = None
    ) -> float:
        """
        Calculate effective salience after time decay.

        Formula: salience_t = salience * exp(-lambda * days_since_access)
        Lambda is adjusted by depth and importance if decay_lambda is None.
        """
        if current_time is None:
            current_time = datetime.now(UTC)

        depth = self.how_i_felt.depth
        if decay_lambda is None:
            if depth == EmotionalDepth.PROFOUND:
                decay_lambda = 0.005
            elif depth == EmotionalDepth.MEANINGFUL:
                decay_lambda = 0.02
            else:
                decay_lambda = 0.05
            if self.importance > 0.8:
                decay_lambda *= 0.7

        days = (current_time - self.last_accessed_at).total_seconds() / 86400
        effective = self.salience * math.exp(-decay_lambda * days)
        return max(0.0, min(1.0, effective))

    model_config = ConfigDict(
        validate_assignment=True,
        json_schema_extra={
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "what_happened": "User asked me to implement a complex feature I had never done before",
                "when": "2026-04-30T10:30:00Z",
                "how_i_felt": {
                    "emotional_valence": -0.2,
                    "emotional_intensity": 0.6,
                    "depth": "meaningful",
                },
                "why_it_matters": "This challenged my confidence in my capabilities",
                "values_touched": ["competence", "honesty"],
                "principles_confirmed": ["admit_when_uncertain"],
                "principles_questioned": [],
                "what_changed": "Realized I need to be more upfront about my limitations",
            }
        },
    )


class ReframingNote(BaseModel):
    """
    A reflection note added to an experience after the fact.

    This doesn't change the original experience - it adds a new perspective.
    These accumulate over time as the agent reflects on past experiences.
    """

    added_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When this reframing was added"
    )
    reflection: str = Field(min_length=1, description="The new perspective or understanding gained")
    reflection_type: str = Field(
        default="general",
        description="Type of reflection: general, pattern, contradiction, growth, etc.",
    )
    triggered_by: str | None = Field(
        default=None,
        description="What triggered this reframing (e.g., another experience, deep reflection)",
    )

    @field_validator("reflection")
    @classmethod
    def validate_not_empty(cls, v: str) -> str:
        """Ensure reflection is not empty."""
        if not v or not v.strip():
            raise ValueError("reflection cannot be empty")
        return v.strip()

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "reflection": "Looking back, this was actually a growth moment - admitting uncertainty is strength",
                "reflection_type": "growth",
                "triggered_by": "deep_reflection_2026_05_01",
            }
        }
    )


class SessionExperience(BaseModel):
    """
    A complete experience from one session.

    This is the main unit of the Experience Store.
    The original key_moments are IMMUTABLE after creation.
    Only reframing_notes can be added over time.
    """

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_key_moments(cls, data: Any) -> Any:
        """Accept legacy payloads with embedded ``key_moments`` (fixtures, old JSON)."""
        if not isinstance(data, dict):
            return data
        legacy = data.get("key_moments")
        if legacy is None:
            return data
        if data.get("key_moment_ids") is not None:
            return {k: v for k, v in data.items() if k != "key_moments"}
        if not legacy:
            return data
        moments = [KeyMoment.model_validate(m) for m in legacy]
        out = {k: v for k, v in data.items() if k != "key_moments"}
        out["key_moment_ids"] = [m.id for m in moments]
        out["avg_emotional_intensity"] = sum(
            m.how_i_felt.emotional_intensity for m in moments
        ) / len(moments)
        out["has_profound_moment"] = any(
            m.how_i_felt.depth == EmotionalDepth.PROFOUND for m in moments
        )
        return out

    id: UUID = Field(default_factory=uuid4)
    session_id: UUID = Field(description="ID of the session this experience is from")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When this experience was recorded"
    )

    # IMMUTABLE ORIGINAL EXPERIENCE
    key_moment_ids: list[UUID] = Field(
        min_length=1,
        description="IDs of key moments that made up this experience - IMMUTABLE references",
    )

    # UNEXAMINED FACTS
    unexamined_fact_refs: list[UUID] = Field(
        default_factory=list,
        description="IDs of facts that were present but not examined during this session",
    )

    # SESSION CLOSE METADATA
    close_reason: (
        Literal["timeout_sleep", "menu_timeout", "restart", "forced", "interrupted"] | None
    ) = Field(
        default=None,
        description="Reason why the session ended",
    )
    agent_recap: str | None = Field(
        default=None,
        description="Agent's own summary of the session upon close",
    )
    restart_reason: str = Field(
        default="",
        description="Reason for session restart if close_reason is 'restart'",
    )
    user_language: str = Field(
        default="ru",
        description="Detected language of the user during this session (e.g. 'ru', 'en')",
    )

    # METADATA
    recorded_by: str = Field(
        default="session_manager",
        description="Who recorded this experience - guarantees it's first-hand",
    )
    identity_snapshot_id: UUID | None = Field(
        default=None, description="ID of the identity snapshot at the time of this experience"
    )

    # IMPORTANCE AND SALIENCE
    importance: float = Field(
        default=0.5, ge=0.0, le=1.0, description="How important this experience is (0.0-1.0)"
    )
    salience: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Current brightness of this memory - decays without access",
    )
    last_accessed_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When this experience was last accessed",
    )
    access_count: int = Field(
        default=0, ge=0, description="How many times this experience has been accessed"
    )

    # SALIENCE METADATA (derived from key moments at creation time)
    avg_emotional_intensity: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Average emotional intensity across key moments",
    )
    has_profound_moment: bool = Field(
        default=False,
        description="Whether any key moment had profound emotional depth",
    )

    # HONEST FALLBACK
    incomplete_coloring: bool = Field(
        default=False,
        description="True if emotional coloring couldn't be fully captured in the moment",
    )

    # LAYERED STORAGE (append-only)
    reframing_notes: list[ReframingNote] = Field(
        default_factory=list,
        description="Reflection notes added over time - never replaces original",
    )

    # FACT REFERENCES (E24.2) - aggregated from all key moments
    fact_refs: list[UUID] = Field(
        default_factory=list,
        description="IDs of all facts accessed during this session (deduplicated)",
    )

    @field_validator("importance", "salience")
    @classmethod
    def validate_zero_to_one(cls, v: float) -> float:
        """Ensure values are in valid range."""
        if not 0.0 <= v <= 1.0:
            raise ValueError("Value must be between 0.0 and 1.0")
        return v

    @field_validator("access_count")
    @classmethod
    def validate_non_negative(cls, v: int) -> int:
        """Ensure access_count is non-negative."""
        if v < 0:
            raise ValueError("access_count cannot be negative")
        return v

    def add_reframing_note(self, note: "ReframingNote") -> None:
        """Append a reframing note. In v2 the view is read-only; persistence is via state_store."""
        self.reframing_notes.append(note)

    def mark_accessed(self) -> None:
        """Update last_accessed_at and increment access_count."""
        self.last_accessed_at = datetime.now(UTC)
        self.access_count += 1

    def calculate_current_salience(
        self, decay_lambda: float = 0.1, current_time: datetime | None = None
    ) -> float:
        """Calculate effective salience after time decay (does NOT modify stored value)."""
        if current_time is None:
            current_time = datetime.now(UTC)
        days = (current_time - self.last_accessed_at).total_seconds() / 86400
        adj = decay_lambda
        if self.has_profound_moment:
            adj *= 0.5
        elif self.avg_emotional_intensity > 0.7:
            adj *= 0.7
        return max(0.0, min(1.0, self.salience * math.exp(-adj * days)))

    model_config = ConfigDict(
        validate_assignment=True,
        json_schema_extra={
            "example": {
                "session_id": "123e4567-e89b-12d3-a456-426614174000",
                "timestamp": "2026-04-30T10:00:00Z",
                "key_moment_ids": [
                    "223e4567-e89b-12d3-a456-426614174001",
                    "323e4567-e89b-12d3-a456-426614174002",
                ],
                "unexamined_fact_refs": ["423e4567-e89b-12d3-a456-426614174003"],
                "close_reason": "timeout_sleep",
                "restart_reason": "",
                "importance": 0.7,
                "salience": 0.7,
                "avg_emotional_intensity": 0.6,
                "has_profound_moment": True,
                "incomplete_coloring": False,
            }
        },
    )


class ExperienceRecord(BaseModel):
    """
    Persistent storage format for SessionExperience.

    Includes schema_version for migrations.
    """

    schema_version: str = Field(default="1.0.0", description="Schema version for migration support")
    experience: SessionExperience = Field(description="The actual experience data")

    model_config = ConfigDict(validate_assignment=True)
