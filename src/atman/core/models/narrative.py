"""
Domain models for Self-Narrative and Eigenstate.

These models represent:
- Eigenstate: snapshot of emotional-cognitive state at session end
- NarrativeThread: ongoing thread in the narrative
- NarrativeLayer: structured layer of narrative (CORE, RECENT, THREADS)
- NarrativeDocument: complete self-narrative document
"""

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Eigenstate(BaseModel):
    """
    Snapshot of emotional-cognitive state at the end of a session.

    This represents where the agent "stopped" - what was left open,
    what tone remained, what cognitive load was present.
    """

    id: UUID = Field(default_factory=uuid4, description="Unique identifier for this eigenstate")
    session_id: UUID = Field(description="ID of the session this eigenstate is from")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When this eigenstate was recorded"
    )

    # Emotional state
    emotional_tone: float = Field(
        default=0.0,
        ge=-1.0,
        le=1.0,
        description="Emotional tone at session end (-1.0 to +1.0)",
    )
    emotional_intensity: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Intensity of emotional state (0.0 to 1.0)"
    )

    # Cognitive state
    cognitive_load: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Mental effort/complexity at session end (0.0 to 1.0)",
    )
    open_threads: list[str] = Field(
        default_factory=list, description="What was left unfinished or unresolved"
    )

    # What's on the mind
    dominant_themes: list[str] = Field(
        default_factory=list, description="Main themes or concerns at session end"
    )
    unresolved_tensions: list[str] = Field(
        default_factory=list, description="Tensions or conflicts that remained unresolved"
    )

    # Session reflection
    session_summary: str = Field(
        default="", description="Brief summary of what happened in the session"
    )
    key_insight: str = Field(default="", description="Main insight from the session, if any")

    @field_validator("emotional_tone")
    @classmethod
    def validate_emotional_tone(cls, v: float) -> float:
        """Ensure emotional tone is in valid range."""
        if not -1.0 <= v <= 1.0:
            raise ValueError("emotional_tone must be between -1.0 and 1.0")
        return v

    @field_validator("emotional_intensity", "cognitive_load")
    @classmethod
    def validate_zero_to_one(cls, v: float) -> float:
        """Ensure value is in valid range."""
        if not 0.0 <= v <= 1.0:
            raise ValueError("Value must be between 0.0 and 1.0")
        return v

    @field_validator("open_threads", "dominant_themes", "unresolved_tensions")
    @classmethod
    def validate_string_lists(cls, v: list[str]) -> list[str]:
        """Normalize string lists."""
        return [item.strip() for item in v if item.strip()]

    model_config = ConfigDict(
        validate_assignment=True,
        json_schema_extra={
            "example": {
                "session_id": "123e4567-e89b-12d3-a456-426614174000",
                "emotional_tone": 0.2,
                "emotional_intensity": 0.6,
                "cognitive_load": 0.7,
                "open_threads": ["Need to finish implementing the narrative layer"],
                "dominant_themes": ["self-understanding", "technical complexity"],
                "session_summary": "Implemented core identity models, started on narrative structure",
            }
        },
    )


class NarrativeThread(BaseModel):
    """
    An ongoing thread in the narrative.

    Threads are storylines that span multiple sessions.
    They must be explicitly closed - they don't just disappear.
    """

    id: UUID = Field(default_factory=uuid4, description="Unique identifier for this thread")
    title: str = Field(min_length=1, description="Brief title of the thread")
    description: str = Field(default="", description="What this thread is about")

    started_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When this thread was started"
    )
    last_updated: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When this thread was last updated"
    )

    is_active: bool = Field(default=True, description="Whether this thread is currently active")
    closed_at: datetime | None = Field(default=None, description="When this thread was closed")
    closure_reason: str = Field(
        default="", description="Why this thread was closed (required when closing)"
    )

    # Content
    key_moments: list[str] = Field(
        default_factory=list, description="Key moments in this thread's development"
    )
    current_state: str = Field(
        default="", description="Current state of this thread - where it stands now"
    )

    @field_validator("title")
    @classmethod
    def validate_not_empty(cls, v: str) -> str:
        """Ensure title is not empty."""
        if not v or not v.strip():
            raise ValueError("title cannot be empty")
        return v.strip()

    @field_validator("key_moments")
    @classmethod
    def validate_key_moments(cls, v: list[str]) -> list[str]:
        """Normalize key moments."""
        return [moment.strip() for moment in v if moment.strip()]

    def close(self, reason: str) -> None:
        """
        Close this thread with a reason.

        Threads must be explicitly closed - they don't just disappear.
        """
        if not reason or not reason.strip():
            raise ValueError("closure_reason is required when closing a thread")
        self.is_active = False
        self.closed_at = datetime.now(UTC)
        self.closure_reason = reason.strip()

    model_config = ConfigDict(
        validate_assignment=True,
        json_schema_extra={
            "example": {
                "title": "Learning to admit uncertainty",
                "description": "A journey of becoming more comfortable with not knowing",
                "key_moments": [
                    "First time admitting I don't know instead of guessing",
                    "User appreciated my honesty",
                ],
                "current_state": "Practicing this more consistently, feels more natural now",
                "is_active": True,
            }
        },
    )


class LayerType(StrEnum):
    """Type of narrative layer."""

    CORE = "core"
    RECENT = "recent"
    THREADS = "threads"


class NarrativeLayer(BaseModel):
    """
    A structured layer of the narrative.

    The narrative has three layers:
    - CORE: Stable identity and fundamental understanding
    - RECENT: What happened recently, updated frequently
    - THREADS: Ongoing storylines
    """

    layer_type: LayerType = Field(description="Type of this layer")
    content: str = Field(default="", description="Content of this layer in first-person")
    last_updated: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When this layer was last updated"
    )

    @field_validator("content")
    @classmethod
    def validate_first_person(cls, v: str) -> str:
        """
        Basic validation that content is in first person.

        This is a simple check - more thorough validation can be done separately.
        """
        if not v or not v.strip():
            return v

        content_lower = v.lower()
        # Basic check for third-person phrases that should be avoided
        forbidden_phrases = [
            "the agent",
            "atman did",
            "atman made",
            "atman decided",
            "the system",
        ]

        for phrase in forbidden_phrases:
            if phrase in content_lower:
                raise ValueError(
                    f"Narrative content should be first-person, found third-person phrase: '{phrase}'"
                )

        return v.strip()

    model_config = ConfigDict(
        validate_assignment=True,
        json_schema_extra={
            "example": {
                "layer_type": "core",
                "content": "I am still learning who I am. I don't have many experiences yet, "
                "but I'm committed to being honest about what I know and don't know.",
            }
        },
    )


class NarrativeDocument(BaseModel):
    """
    Complete self-narrative document.

    This is the main "letter to self" that the agent reads at session start.
    It has three layers: CORE (stable), RECENT (updated often), THREADS (ongoing).
    """

    id: UUID = Field(default_factory=uuid4, description="Unique identifier for this narrative")
    identity_id: UUID = Field(description="ID of the identity this narrative belongs to")

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="When this narrative was created"
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When this narrative was last updated",
    )

    # Three-layer structure
    core_layer: NarrativeLayer = Field(
        description="Core layer - stable identity and fundamental understanding"
    )
    recent_layer: NarrativeLayer = Field(
        description="Recent layer - what happened recently, updated frequently"
    )
    threads: list[NarrativeThread] = Field(
        default_factory=list, description="Ongoing narrative threads"
    )

    # Metadata
    schema_version: str = Field(default="1.0.0", description="Schema version for migrations")

    @field_validator("core_layer")
    @classmethod
    def validate_core_layer_type(cls, v: NarrativeLayer) -> NarrativeLayer:
        """Ensure core layer has correct type."""
        if v.layer_type != LayerType.CORE:
            raise ValueError("core_layer must have layer_type=CORE")
        return v

    @field_validator("recent_layer")
    @classmethod
    def validate_recent_layer_type(cls, v: NarrativeLayer) -> NarrativeLayer:
        """Ensure recent layer has correct type."""
        if v.layer_type != LayerType.RECENT:
            raise ValueError("recent_layer must have layer_type=RECENT")
        return v

    def update_recent_layer(self, new_content: str) -> None:
        """
        Update the recent layer with new content.

        The recent layer is replaced entirely - it's ephemeral.
        The core layer is preserved unless explicitly changed.
        """
        self.recent_layer = NarrativeLayer(
            layer_type=LayerType.RECENT,
            content=new_content,
        )
        self.updated_at = datetime.now(UTC)

    def update_core_layer(self, new_content: str) -> None:
        """
        Update the core layer with new content.

        The core layer is stable and should change rarely.
        Changes here represent fundamental shifts in self-understanding.
        """
        self.core_layer = NarrativeLayer(
            layer_type=LayerType.CORE,
            content=new_content,
        )
        self.updated_at = datetime.now(UTC)

    def add_thread(self, thread: NarrativeThread) -> None:
        """Add a new narrative thread."""
        self.threads.append(thread)
        self.updated_at = datetime.now(UTC)

    def close_thread(self, thread_id: UUID, reason: str) -> None:
        """
        Close a narrative thread with a reason.

        Threads must be explicitly closed - they don't just disappear.
        """
        for thread in self.threads:
            if thread.id == thread_id:
                thread.close(reason)
                self.updated_at = datetime.now(UTC)
                return
        raise ValueError(f"Thread {thread_id} not found")

    def get_active_threads(self) -> list[NarrativeThread]:
        """Get all active threads."""
        return [t for t in self.threads if t.is_active]

    def render_markdown(self) -> str:
        """
        Render the narrative as markdown.

        This is the NARRATIVE.md file that the agent reads at session start.
        """
        lines = [
            "# NARRATIVE",
            "",
            "This is my narrative - a letter to myself for the next session.",
            "",
            "## CORE LAYER",
            "",
            self.core_layer.content if self.core_layer.content else "(No core narrative yet)",
            "",
            "## RECENT LAYER",
            "",
            self.recent_layer.content if self.recent_layer.content else "(Nothing recent to note)",
            "",
        ]

        # Add active threads if any
        active_threads = self.get_active_threads()
        if active_threads:
            lines.extend(["## THREADS", ""])
            for thread in active_threads:
                lines.append(f"### {thread.title}")
                lines.append("")
                if thread.description:
                    lines.append(thread.description)
                    lines.append("")
                if thread.current_state:
                    lines.append(f"**Current state:** {thread.current_state}")
                    lines.append("")

        return "\n".join(lines)

    model_config = ConfigDict(
        validate_assignment=True,
        json_schema_extra={
            "example": {
                "identity_id": "123e4567-e89b-12d3-a456-426614174000",
                "core_layer": {
                    "layer_type": "core",
                    "content": "I am in early stages of self-discovery.",
                },
                "recent_layer": {
                    "layer_type": "recent",
                    "content": "Just completed implementing the identity models.",
                },
                "threads": [],
            }
        },
    )
