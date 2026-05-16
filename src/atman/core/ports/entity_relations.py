"""Port: EntityRelationExtractor — extract typed relations between entities from text."""

from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict, Field

from atman.core.ports.linguistic import DetectedEntity


class ExtractedRelation(BaseModel):
    """A typed binary relation between two detected entities, sourced from text."""

    model_config = ConfigDict(frozen=True)

    subject: DetectedEntity = Field(description="Head entity (subject of the relation)")
    object: DetectedEntity = Field(description="Tail entity (object of the relation)")
    relation_type: str = Field(min_length=1, description="Canonical relation label")
    confidence: float = Field(ge=0.0, le=1.0, default=1.0)
    learned_by: str = Field(
        default="rules",
        description="'mrebel' | 'rules' | 'reflection' | 'manual'",
    )


class EntityRelationExtractor(ABC):
    """Hexagonal port for binary relation extraction from text + entity spans."""

    @abstractmethod
    def extract_relations(
        self,
        text: str,
        entities: list[DetectedEntity],
    ) -> list[ExtractedRelation]:
        """Return zero or more typed relations holding between entities in ``text``.

        Implementations should be deterministic for the same `(text, entities)`
        input and MUST NOT mutate the input lists.
        """
