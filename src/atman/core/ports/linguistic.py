"""Port: LinguisticAnalyzer — NER and classification for messages and key moments."""

from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict, Field

from atman.core.models.entity import EntityType


class AmbientAnchor(BaseModel):
    """A salient contextual signal extracted from a user message."""

    model_config = ConfigDict(frozen=True)

    anchor_type: str = Field(
        description=("person_ref | topic | location | time_ref | action | emotion_ref")
    )
    text: str
    entity_type: EntityType | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    span: tuple[int, int] | None = Field(
        default=None,
        description="Character offsets (start, end) in the original text",
    )


class DetectedEntity(BaseModel):
    """A named entity recognised in a piece of text."""

    model_config = ConfigDict(frozen=True)

    text: str
    entity_type: EntityType
    confidence: float = Field(ge=0.0, le=1.0)
    span: tuple[int, int] | None = Field(
        default=None,
        description="Character offsets (start, end) in the original text",
    )


class UserMessageAnalysis(BaseModel):
    """NER + ambient anchor extraction result for a single user message."""

    model_config = ConfigDict(frozen=True)

    text: str
    entities: list[DetectedEntity] = []
    anchors: list[AmbientAnchor] = []
    detected_language: str = "ru"


class AgentMessageAnalysis(BaseModel):
    """Linguistic analysis of an agent message, optionally against its thinking trace."""

    model_config = ConfigDict(frozen=True)

    message_entities: list[DetectedEntity] = []
    thinking_entities: list[DetectedEntity] = []
    divergence_signals: list[str] = Field(
        default=[],
        description="Detected divergence markers between thinking and message",
    )
    boundary_markers: list[str] = Field(
        default=[],
        description="Principle invocations, refusals, disclaimers",
    )
    trust_signals: list[str] = Field(
        default=[],
        description="Positive or negative trust indicators",
    )
    cognitive_load_high: bool = False
    detected_language: str = "ru"


class KeyMomentAnalysis(BaseModel):
    """Linguistic analysis of a key moment's narrative fields."""

    model_config = ConfigDict(frozen=True)

    entities: list[DetectedEntity] = []
    topic_labels: list[str] = []
    cognitive_load: float = Field(default=0.0, ge=0.0, le=1.0)
    boundary_event: bool = Field(
        default=False,
        description="True when a principle invocation or refusal is detected",
    )
    trust_signal: str | None = Field(
        default=None,
        description='"positive" | "negative" | None',
    )
    principle_invocations: list[str] = []


class LinguisticAnalyzer(ABC):
    """Hexagonal port for NER and zero-shot classification over conversation text."""

    @abstractmethod
    def analyze_user_message(self, text: str) -> UserMessageAnalysis:
        """Extract entities and ambient anchors from a raw user message."""

    @abstractmethod
    def analyze_agent_message(
        self,
        message: str,
        *,
        thinking: str | None = None,
    ) -> AgentMessageAnalysis:
        """Analyse an agent's outgoing message.

        When thinking is provided, cross-reference it with the message to detect
        divergence signals (e.g. the agent hedged in thinking but stated
        confidently in message).
        """

    @abstractmethod
    def analyze_key_moment(
        self,
        what_happened: str,
        why_it_matters: str,
    ) -> KeyMomentAnalysis:
        """Analyse the two narrative fields of a KeyMoment record.

        Both fields are processed together so the analyzer can reason about
        whether the stated significance is consistent with the event description.
        """
