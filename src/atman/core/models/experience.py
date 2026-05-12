"""
Domain models for Experience Store.

These models represent first-hand lived experiences of the agent.
All experiences are immutable after recording - only reframing notes can be added.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    def validate_float_range(cls, v: float, info) -> float:
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

    model_config = ConfigDict(
        # Ensure immutability by making validation strict
        validate_assignment=True,
        json_schema_extra={
            "example": {
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

    id: UUID = Field(default_factory=uuid4)
    session_id: UUID = Field(description="ID of the session this experience is from")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When this experience was recorded"
    )

    # IMMUTABLE ORIGINAL EXPERIENCE
    key_moments: list[KeyMoment] = Field(
        min_length=1, description="The moments that made up this experience - IMMUTABLE"
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

    # SESSION CLOSURE METADATA (E22.7)
    close_reason: str | None = Field(
        default=None,
        description="Reason for session closure: timeout_sleep | restart | forced | interrupted | None",
    )
    restart_reason: str | None = Field(
        default=None,
        description="Human-readable reason when close_reason=restart (agent's own words)",
    )
    agent_recap: str | None = Field(
        default=None,
        description="Agent's recap before timeout_sleep (optional, agent-authored)",
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

    def add_reframing_note(self, note: ReframingNote) -> None:
        """
        Add a new reframing note to this experience.

        This is the ONLY way to modify an experience after creation.
        The original key_moments remain untouched.
        """
        self.reframing_notes.append(note)

    def mark_accessed(self) -> None:
        """
        Mark this experience as accessed.

        Updates last_accessed_at and increments access_count.
        Used for salience calculation.
        """
        self.last_accessed_at = datetime.now(UTC)
        self.access_count += 1

    def calculate_current_salience(
        self, decay_lambda: float = 0.1, current_time: datetime | None = None
    ) -> float:
        """
        Calculate current salience based on time decay.

        Formula: salience_t = salience_0 * exp(-lambda * days_since_access)

        This DOES NOT modify the stored salience value.
        It only calculates what the current effective salience would be.

        Args:
            decay_lambda: Decay rate parameter (default 0.1)
            current_time: Current time for calculation (defaults to now)

        Returns:
            float: Current effective salience (0.0-1.0)
        """
        import math

        if current_time is None:
            current_time = datetime.now(UTC)

        days_since_access = (current_time - self.last_accessed_at).total_seconds() / 86400

        # Adjust decay rate based on emotional intensity and depth
        if self.key_moments:
            avg_intensity = sum(m.how_i_felt.emotional_intensity for m in self.key_moments) / len(
                self.key_moments
            )
            has_profound = any(
                m.how_i_felt.depth == EmotionalDepth.PROFOUND for m in self.key_moments
            )

            # Profound or intense experiences decay more slowly
            if has_profound:
                decay_lambda *= 0.5
            elif avg_intensity > 0.7:
                decay_lambda *= 0.7

        effective_salience = self.salience * math.exp(-decay_lambda * days_since_access)
        return max(0.0, min(1.0, effective_salience))

    model_config = ConfigDict(
        validate_assignment=True,
        json_schema_extra={
            "example": {
                "session_id": "123e4567-e89b-12d3-a456-426614174000",
                "timestamp": "2026-04-30T10:00:00Z",
                "key_moments": [
                    {
                        "what_happened": "User presented a complex problem",
                        "how_i_felt": {
                            "emotional_valence": 0.2,
                            "emotional_intensity": 0.6,
                            "depth": "meaningful",
                        },
                        "why_it_matters": "Tests my ability to handle complexity",
                        "values_touched": ["competence", "service"],
                    }
                ],
                "importance": 0.7,
                "salience": 0.7,
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
