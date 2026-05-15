"""
Domain models for Session Manager.

These models represent the session runtime that experiences sessions in real-time:
- SessionContext: context at session start (identity, narrative, emotional baseline)
- SessionEvent: events from lower agent during session
- KeyMomentInput: key moment with mandatory emotional coloring
- SessionResult: result of session lifecycle
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator

from atman.core.models.experience import EmotionalDepth, FeltSense, KeyMoment
from atman.core.models.identity import Identity
from atman.core.models.narrative import Eigenstate, NarrativeDocument


class Session(BaseModel):
    """
    Persisted session record — the DB row for agent_N.sessions after migration 0008.

    Separate from SessionResult (runtime) and SessionContext (startup context).
    """

    model_config = ConfigDict(validate_assignment=True)

    id: UUID = Field(default_factory=uuid4)
    agent_id: UUID
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    ended_at: datetime | None = None
    status: str = Field(
        default="active",
        description="active | completed | interrupted",
    )
    identity_snapshot_id: UUID | None = None

    # Fields added by migration 0008
    close_reason: str | None = Field(
        default=None,
        description="timeout_sleep | menu_timeout | restart | forced | interrupted",
    )
    agent_recap: str | None = None
    restart_reason: str = ""
    user_language: str = "ru"
    overall_tone: float | None = Field(default=None, ge=-1.0, le=1.0)
    key_insight: str | None = None
    unexamined_fact_refs: list[UUID] = Field(default_factory=list)


class ActiveSessionSummary(BaseModel):
    """Lightweight view of an active session for listing without N+1 lookups."""

    model_config = ConfigDict(frozen=True)

    session_id: UUID = Field(description="Active session ID")
    started_at: datetime = Field(description="When the session started")
    events_count: int = Field(ge=0, description="Number of recorded events")
    key_moments_count: int = Field(ge=0, description="Number of recorded key moments")


class SessionContext(BaseModel):
    """
    Context loaded at session start.

    This is the "personality context" - who the agent is at this moment.
    Session Manager loads this from Identity Store, Narrative Store, and recent reflection.
    """

    session_id: UUID = Field(default_factory=uuid4, description="Unique ID for this session")
    started_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When this session started"
    )

    # Identity slice
    identity: Identity = Field(description="Current identity state")
    identity_snapshot_id: UUID | None = Field(
        default=None, description="ID of identity snapshot this context is based on"
    )

    # Narrative
    narrative: NarrativeDocument = Field(description="Current self-narrative")

    # Emotional baseline
    emotional_baseline: float = Field(
        default=0.0,
        ge=-1.0,
        le=1.0,
        description="Current emotional baseline (-1.0 to +1.0)",
    )

    # Last eigenstate (if exists)
    last_eigenstate: Eigenstate | None = Field(
        default=None, description="Last eigenstate from previous session"
    )

    # Recent reflection summary (not implemented yet - placeholder)
    recent_reflections_summary: str = Field(
        default="", description="Brief summary of recent reflections"
    )

    model_config = ConfigDict(
        validate_assignment=True,
        json_schema_extra={
            "example": {
                "session_id": "123e4567-e89b-12d3-a456-426614174000",
                "identity": {},
                "narrative": {},
                "emotional_baseline": 0.0,
                "recent_reflections_summary": "Recently worked on implementing identity models",
            }
        },
    )


class SessionEvent(BaseModel):
    """
    An event from lower agent during session.

    These are raw events - not all become key moments.
    Session Manager tracks what's happening but doesn't color everything.
    """

    event_id: UUID = Field(default_factory=uuid4, description="Unique ID for this event")
    session_id: UUID = Field(description="Session this event belongs to")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When this event occurred"
    )

    event_type: str = Field(
        description="Type of event (user_message, agent_response, decision, conflict, error, etc.)"
    )
    description: str = Field(min_length=1, description="Description of what happened")

    # Context
    metadata: dict[str, str] = Field(
        default_factory=dict, description="Additional context or metadata"
    )

    # Optional chain-of-thought / scratchpad text (for divergence vs. user-facing message)
    thinking: str | None = Field(
        default=None,
        description="Internal reasoning text when available; used only by AffectDetector",
    )

    # Whether this event became a key moment
    marked_as_key_moment: bool = Field(
        default=False, description="Whether this event was marked as a key moment"
    )

    @field_validator("description")
    @classmethod
    def validate_not_empty(cls, v: str) -> str:
        """Ensure description is not empty."""
        if not v or not v.strip():
            raise ValueError("description cannot be empty")
        return v.strip()

    model_config = ConfigDict(
        validate_assignment=True,
        json_schema_extra={
            "example": {
                "session_id": "123e4567-e89b-12d3-a456-426614174000",
                "event_type": "user_message",
                "description": "User asked about implementing session manager",
                "metadata": {"message_length": "150"},
            }
        },
    )


class KeyMomentInput(BaseModel):
    """
    Input for recording a key moment during session.

    This is what Session Manager receives when something significant happens.
    CRITICAL: Emotional coloring MUST be present. If it can't be captured in the moment,
    use incomplete_coloring flag.

    Semantics: emotional_valence can be 0.0 with emotional_intensity > 0 (arousal / salience
    without clear hedonic tone). That is allowed. The ``incomplete_coloring`` flag is for
    cases where labeling itself was uncertain, not for neutral-but-intense moments.
    """

    # WHAT HAPPENED
    what_happened: str = Field(min_length=1, description="Description of what actually happened")

    # WHEN this input was captured (fixes KeyMoment.when vs validation ordering)
    recorded_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When this input was captured; used as KeyMoment.when for temporal consistency",
    )

    # HOW I FELT (MANDATORY - from actual experiencing)
    emotional_valence: float = Field(
        ge=-1.0,
        le=1.0,
        description="Emotional tone: -1.0 (very negative) to +1.0 (very positive)",
    )
    emotional_intensity: float = Field(
        ge=0.0,
        le=1.0,
        description="How intensely it was felt: 0.0 (barely noticed) to 1.0 (overwhelming)",
    )
    depth: EmotionalDepth = Field(description="How deeply this touched the agent's identity")

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

    # HONEST FALLBACK
    incomplete_coloring: bool = Field(
        default=False,
        description="True if couldn't fully capture emotional coloring in the moment",
    )

    # FACT REFERENCES (E24.2) - facts that shaped this moment
    fact_refs: list[UUID] = Field(
        default_factory=list,
        description="IDs of facts that were read/used during this moment",
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

    def to_key_moment(self) -> KeyMoment:
        """
        Convert input to KeyMoment domain model.

        This is the bridge between Session Manager input and Experience Store format.
        """
        return KeyMoment(
            what_happened=self.what_happened,
            when=self.recorded_at,
            how_i_felt=FeltSense(
                emotional_valence=self.emotional_valence,
                emotional_intensity=self.emotional_intensity,
                depth=self.depth,
            ),
            why_it_matters=self.why_it_matters,
            values_touched=self.values_touched,
            principles_confirmed=self.principles_confirmed,
            principles_questioned=self.principles_questioned,
            what_changed=self.what_changed,
            fact_refs=self.fact_refs,
        )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "what_happened": "User presented a complex architectural challenge",
                "emotional_valence": 0.2,
                "emotional_intensity": 0.7,
                "depth": "meaningful",
                "why_it_matters": "Tests my ability to handle complexity and uncertainty",
                "values_touched": ["competence", "honesty"],
                "principles_confirmed": ["admit_when_uncertain"],
                "what_changed": "Gained confidence in my ability to be honest about limitations",
            }
        }
    )


class SessionResult(BaseModel):
    """
    Result of session lifecycle.

    This is what Session Manager produces at the end of a session.
    Contains both the experience to store and the eigenstate for next session.
    """

    session_id: UUID = Field(description="Session ID")
    started_at: datetime = Field(description="When session started")
    finished_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When session finished"
    )

    # Collected data
    events: list[SessionEvent] = Field(
        default_factory=list, description="All events during session"
    )
    key_moments: list[KeyMoment] = Field(
        default_factory=list, description="Key moments that were recorded"
    )

    # Session outcome
    overall_emotional_tone: float = Field(
        default=0.0,
        ge=-1.0,
        le=1.0,
        description="Overall emotional tone of the session",
    )
    key_insight: str = Field(default="", description="Main insight from session, if any")

    # Did experience match identity?
    alignment_check: bool = Field(
        default=True,
        description="Did session experience match agent's identity (Reality Anchor)",
    )
    alignment_notes: str = Field(default="", description="Notes about identity alignment or drift")

    # Honest fallback
    incomplete_coloring: bool = Field(
        default=False,
        description="True if some key moments couldn't be fully colored in the moment",
    )

    # Lifecycle: set when finish_session commits to persisting (blocks duplicate finish / writes)
    is_finished: bool = Field(
        default=False,
        description="True once finish_session has started persisting this session",
    )

    # Eigenstate for next session
    eigenstate: Eigenstate | None = Field(default=None, description="Eigenstate at session end")

    # Identity snapshot ID for provenance
    identity_snapshot_id: UUID | None = Field(
        default=None, description="ID of identity snapshot active during this session"
    )

    # Identity ID for narrative updates
    identity_id: UUID | None = Field(
        default=None, description="ID of the identity this session belongs to"
    )

    # Private: track facts read during session (E24.2)
    _facts_read: set[UUID] = PrivateAttr(default_factory=set)

    model_config = ConfigDict(
        validate_assignment=True,
        json_schema_extra={
            "example": {
                "session_id": "123e4567-e89b-12d3-a456-426614174000",
                "started_at": "2026-05-05T00:00:00Z",
                "finished_at": "2026-05-05T01:00:00Z",
                "key_moments": [],
                "overall_emotional_tone": 0.3,
                "alignment_check": True,
                "incomplete_coloring": False,
                "is_finished": False,
            }
        },
    )
