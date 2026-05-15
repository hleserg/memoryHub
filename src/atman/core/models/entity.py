"""Domain models for Entity Registry."""

from datetime import UTC, date, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EntityType(StrEnum):
    person = "person"
    place = "place"
    organization = "organization"
    object = "object"
    topic = "topic"
    event = "event"
    tool = "tool"
    health_condition = "health_condition"
    skill = "skill"
    value = "value"
    principle = "principle"


class ResolutionMethod(StrEnum):
    L1_exact = "exact match"
    L2_embedding = "cosine similarity ≥ threshold"
    L3_new = "created new entity"


class Entity(BaseModel):
    model_config = ConfigDict(frozen=False, validate_assignment=True)

    id: UUID = Field(default_factory=uuid4)
    agent_id: UUID
    canonical_name: str = Field(min_length=1)
    entity_type: EntityType
    description: str | None = None
    first_seen_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_seen_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    mention_count: int = Field(default=1, ge=1)
    needs_disambiguation: bool = False
    embedding: list[float] | None = Field(
        default=None,
        description="halfvec(1024) bge-m3 embedding; None until computed",
    )
    schema_version: str = "atman-1.0"
    metadata: dict = Field(default_factory=dict)

    @field_validator("canonical_name", mode="before")
    @classmethod
    def strip_and_check_canonical_name(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("canonical_name must not be empty or whitespace")
        return stripped


class EntityAlias(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    entity_id: UUID
    agent_id: UUID
    alias_text: str = Field(min_length=1)
    learned_from_fact_id: UUID | None = None
    learned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("alias_text", mode="before")
    @classmethod
    def strip_and_lower_alias_text(cls, v: str) -> str:
        stripped = v.strip().lower()
        if not stripped:
            raise ValueError("alias_text must not be empty or whitespace")
        return stripped


class EntityRelation(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    agent_id: UUID
    from_entity_id: UUID
    to_entity_id: UUID
    relation_type: str = Field(min_length=1)
    since: date | None = None
    until: date | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    learned_from_fact_id: UUID | None = None
    learned_by: str = Field(description="mrebel | rules | reflection | manual")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("learned_by")
    @classmethod
    def validate_learned_by(cls, v: str) -> str:
        allowed = ("mrebel", "rules", "reflection", "manual")
        if v not in allowed:
            raise ValueError(f"learned_by must be one of {allowed}, got {v!r}")
        return v

    @model_validator(mode="after")
    def validate_no_self_relation(self) -> "EntityRelation":
        if self.from_entity_id == self.to_entity_id:
            raise ValueError("from_entity_id and to_entity_id must differ")
        return self


class EntityStance(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    id: UUID = Field(default_factory=uuid4)
    agent_id: UUID
    entity_id: UUID
    stance_text: str = Field(min_length=1)
    valence: float | None = Field(default=None, ge=-1.0, le=1.0)
    intensity: float | None = Field(default=None, ge=0.0, le=1.0)
    formed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    formed_in_reflection_id: UUID | None = None
    based_on_moment_ids: list[UUID] = Field(default_factory=list)
    superseded_at: datetime | None = None
    superseded_by: UUID | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    is_provisional: bool = True

    @property
    def is_active(self) -> bool:
        return self.superseded_at is None


class FactEntityLink(BaseModel):
    model_config = ConfigDict(frozen=True)

    fact_id: UUID
    entity_id: UUID
    agent_id: UUID
    role: str = Field(description="subject | object | context | mentioned")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        allowed = ("subject", "object", "context", "mentioned")
        if v not in allowed:
            raise ValueError(f"role must be one of {allowed}, got {v!r}")
        return v


class KeyMomentEntityLink(BaseModel):
    model_config = ConfigDict(frozen=True)

    key_moment_id: UUID
    entity_id: UUID
    agent_id: UUID
    involvement: str = Field(
        description="primary_subject | present | mentioned | evoked"
    )
    valence_toward_entity: float | None = Field(default=None, ge=-1.0, le=1.0)
    intensity_toward_entity: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("involvement")
    @classmethod
    def validate_involvement(cls, v: str) -> str:
        allowed = ("primary_subject", "present", "mentioned", "evoked")
        if v not in allowed:
            raise ValueError(f"involvement must be one of {allowed}, got {v!r}")
        return v
