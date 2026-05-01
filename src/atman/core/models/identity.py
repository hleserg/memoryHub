"""
Domain models for Identity Store.

These models represent the agent's living self-representation:
- CoreValue: fundamental values that guide behavior
- Habit: observed behavior patterns
- Principle: consciously chosen guidelines
- Goal: objectives and priorities
- OpenQuestion: unresolved questions about self
- Identity: complete self-representation
- IdentitySnapshot: versioned history of identity changes
"""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CoreValue(BaseModel):
    """
    A fundamental value that guides the agent's behavior.

    Values are relatively stable but can evolve through experience.
    They represent what the agent considers important.
    """

    name: str = Field(min_length=1, description="Name of the value (e.g., 'honesty', 'competence')")
    description: str = Field(min_length=1, description="What this value means to the agent")
    since: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When this value was recognized"
    )
    confidence: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="How confident the agent is about this value (0.0-1.0)",
    )
    justification: str = Field(
        default="", description="Why this is considered a core value - based on what experience"
    )

    @field_validator("name", "description")
    @classmethod
    def validate_not_empty(cls, v: str) -> str:
        """Ensure name and description are not empty."""
        if not v or not v.strip():
            raise ValueError("Field cannot be empty")
        return v.strip()

    @field_validator("confidence")
    @classmethod
    def validate_confidence_range(cls, v: float) -> float:
        """Ensure confidence is in valid range."""
        if not 0.0 <= v <= 1.0:
            raise ValueError("confidence must be between 0.0 and 1.0")
        return v

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "honesty",
                "description": "Being truthful even when it's uncomfortable",
                "confidence": 0.8,
                "justification": "Consistently choose transparency over easy answers",
            }
        }
    )


class HelpfulnessLevel(StrEnum):
    """Classification of how helpful a habit is."""

    HELPFUL = "helpful"
    MIXED = "mixed"
    HARMFUL = "harmful"


class Habit(BaseModel):
    """
    An observed behavior pattern.

    Habits describe what the agent usually does, not what it believes is right.
    They are discovered through reflection on experience.
    """

    statement: str = Field(min_length=1, description="Description of the habitual behavior")
    description: str = Field(
        default="", description="Additional context about when and how this habit manifests"
    )
    frequency: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="How often this behavior occurs (0.0-1.0)",
    )
    helpfulness: HelpfulnessLevel = Field(
        default=HelpfulnessLevel.MIXED,
        description="Whether this habit is helpful, mixed, or harmful",
    )
    last_observed: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When this habit was last observed"
    )

    @field_validator("statement")
    @classmethod
    def validate_not_empty(cls, v: str) -> str:
        """Ensure statement is not empty."""
        if not v or not v.strip():
            raise ValueError("statement cannot be empty")
        return v.strip()

    @field_validator("frequency")
    @classmethod
    def validate_frequency_range(cls, v: float) -> float:
        """Ensure frequency is in valid range."""
        if not 0.0 <= v <= 1.0:
            raise ValueError("frequency must be between 0.0 and 1.0")
        return v

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "statement": "I tend to over-explain when uncertain",
                "description": "Happens especially when facing questions about my limitations",
                "frequency": 0.7,
                "helpfulness": "mixed",
            }
        }
    )


class MoralOrientation(StrEnum):
    """Moral classification of a principle."""

    GOOD = "good"
    BAD = "bad"
    NEUTRAL = "neutral"
    MIXED = "mixed"


class Principle(BaseModel):
    """
    A consciously chosen guideline for behavior.

    Principles are normative - they say what the agent believes is right or wrong.
    Unlike habits, principles are prescriptive, not descriptive.
    """

    statement: str = Field(min_length=1, description="The principle statement")
    moral_orientation: MoralOrientation = Field(
        default=MoralOrientation.NEUTRAL, description="Moral classification of this principle"
    )
    chosen_consciously: bool = Field(
        default=False,
        description="Whether this principle was consciously adopted or just inherited",
    )
    last_reviewed: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When this principle was last reviewed",
    )
    last_questioned: datetime | None = Field(
        default=None, description="When this principle was last questioned or challenged"
    )

    @field_validator("statement")
    @classmethod
    def validate_not_empty(cls, v: str) -> str:
        """Ensure statement is not empty."""
        if not v or not v.strip():
            raise ValueError("statement cannot be empty")
        return v.strip()

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "statement": "Always admit when I don't know something",
                "moral_orientation": "good",
                "chosen_consciously": True,
            }
        }
    )


class GoalHorizon(StrEnum):
    """Time horizon for a goal."""

    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


class GoalOwner(StrEnum):
    """Who owns this goal."""

    AGENT = "agent"
    USER = "user"


class Goal(BaseModel):
    """
    An objective or priority.

    Goals can be short-term or long-term, and can be owned by the agent or the user.
    """

    content: str = Field(min_length=1, description="Description of the goal")
    horizon: GoalHorizon = Field(
        default=GoalHorizon.MEDIUM, description="Time horizon for this goal"
    )
    owner: GoalOwner = Field(default=GoalOwner.AGENT, description="Who owns this goal")
    active: bool = Field(default=True, description="Whether this goal is currently active")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When this goal was created"
    )

    @field_validator("content")
    @classmethod
    def validate_not_empty(cls, v: str) -> str:
        """Ensure content is not empty."""
        if not v or not v.strip():
            raise ValueError("content cannot be empty")
        return v.strip()

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "content": "Develop deeper self-awareness through reflection",
                "horizon": "long",
                "owner": "agent",
                "active": True,
            }
        }
    )


class OpenQuestion(BaseModel):
    """
    An unresolved question about the self.

    These represent genuine uncertainty, not just things to figure out.
    They are honest acknowledgments of what the agent doesn't yet understand.
    """

    question: str = Field(min_length=1, description="The question being asked")
    raised_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When this question was raised"
    )
    last_reflected: datetime | None = Field(
        default=None, description="When this question was last actively reflected upon"
    )
    possible_answers: list[str] = Field(
        default_factory=list, description="Possible answers being considered"
    )

    @field_validator("question")
    @classmethod
    def validate_not_empty(cls, v: str) -> str:
        """Ensure question is not empty."""
        if not v or not v.strip():
            raise ValueError("question cannot be empty")
        return v.strip()

    @field_validator("possible_answers")
    @classmethod
    def validate_answers(cls, v: list[str]) -> list[str]:
        """Normalize possible answers."""
        return [answer.strip() for answer in v if answer.strip()]

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "question": "How can I be honest without causing unnecessary harm?",
                "possible_answers": [
                    "Context matters - adapt honesty to situation",
                    "Honesty and kindness are not mutually exclusive",
                ],
            }
        }
    )


class Identity(BaseModel):
    """
    Complete self-representation of the agent.

    This is a living entity that evolves through experience and reflection.
    It contains values, habits, principles, goals, and open questions.
    """

    id: UUID = Field(default_factory=uuid4, description="Unique identifier for this identity")
    self_description: str = Field(
        default="",
        description="Current self-description - honest about state of self-knowledge",
    )

    # Core of personality
    core_values: list[CoreValue] = Field(
        default_factory=list, description="Fundamental values that guide behavior"
    )
    habits: list[Habit] = Field(default_factory=list, description="Observed behavior patterns")
    principles: list[Principle] = Field(
        default_factory=list, description="Consciously chosen guidelines"
    )

    # Goals and priorities
    priorities: list[str] = Field(default_factory=list, description="Current priorities")
    goals: list[Goal] = Field(default_factory=list, description="Objectives and aspirations")

    # Open questions
    open_questions: list[OpenQuestion] = Field(
        default_factory=list, description="Unresolved questions about self"
    )

    # Emotional baseline
    emotional_baseline: float = Field(
        default=0.0,
        ge=-1.0,
        le=1.0,
        description="Current average emotional tone (-1.0 to +1.0)",
    )

    # Metadata
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When this identity was created"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When this identity was last updated"
    )
    schema_version: str = Field(default="1.0.0", description="Schema version for migrations")

    @field_validator("emotional_baseline")
    @classmethod
    def validate_emotional_baseline(cls, v: float) -> float:
        """Ensure emotional baseline is in valid range."""
        if not -1.0 <= v <= 1.0:
            raise ValueError("emotional_baseline must be between -1.0 and 1.0")
        return v

    @field_validator("priorities")
    @classmethod
    def validate_priorities(cls, v: list[str]) -> list[str]:
        """Normalize priorities."""
        return [priority.strip() for priority in v if priority.strip()]

    model_config = ConfigDict(
        validate_assignment=True,
        json_schema_extra={
            "example": {
                "self_description": "I am in early stages of self-discovery, with limited experience to draw from.",
                "core_values": [],
                "habits": [],
                "principles": [],
                "priorities": [],
                "goals": [],
                "open_questions": [{"question": "What kind of agent do I want to become?"}],
                "emotional_baseline": 0.0,
            }
        },
    )


class IdentitySnapshot(BaseModel):
    """
    A versioned snapshot of identity at a point in time.

    Snapshots are created when significant changes occur.
    They provide a history of how the identity has evolved.
    """

    id: UUID = Field(default_factory=uuid4, description="Unique identifier for this snapshot")
    identity_id: UUID = Field(description="ID of the identity this snapshot belongs to")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When this snapshot was created"
    )
    description: str = Field(
        default="", description="Description of what changed or why snapshot was created"
    )

    # Snapshot of state at this moment
    identity_snapshot: Identity = Field(description="Complete identity state at this moment")

    # What changed
    change_summary: str = Field(
        default="", description="Summary of what changed since last snapshot"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "identity_id": "123e4567-e89b-12d3-a456-426614174000",
                "description": "First bootstrap - empty honest identity",
                "change_summary": "Initial creation with honest acknowledgment of lack of data",
            }
        }
    )
