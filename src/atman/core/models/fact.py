"""
Модели данных для Factual Memory Adapter.

Здесь определены структуры для хранения фактов и связей между ними.
Факты - это проверяемые утверждения без психологической интерпретации.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FactStatus(StrEnum):
    """Lifecycle status of a fact."""

    ACTIVE = "active"
    DISPUTED = "disputed"
    SUPERSEDED = "superseded"
    INVALIDATED = "invalidated"


class FactRecord(BaseModel):
    """
    Проверяемый факт без интерпретаций.

    Факт отвечает "что известно", но не "что это значит".
    Не содержит эмоциональной окраски или выводов.
    """

    id: UUID = Field(default_factory=uuid4)
    content: str = Field(min_length=1, description="Содержание факта")
    source: str = Field(min_length=1, description="Источник факта")
    tags: list[str] = Field(default_factory=list, description="Теги для категоризации")
    relations: list["Relation"] = Field(default_factory=list, description="Связи с другими фактами")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict, description="Дополнительные метаданные")

    # Fact lifecycle and validity fields (E24.1)
    status: FactStatus = Field(default=FactStatus.ACTIVE, description="Lifecycle status")
    invalidated_at: datetime | None = Field(default=None, description="When fact was invalidated")
    invalidation_note: str = Field(default="", description="Reason or context for invalidation")
    superseded_by: UUID | None = Field(
        default=None, description="ID of fact that replaces this one"
    )
    disputed_at: datetime | None = Field(default=None, description="When fact was marked disputed")

    # Fact salience fields (E24.3)
    confirmation_count: int = Field(default=0, ge=0, description="Times this fact was confirmed")
    last_confirmed_at: datetime | None = Field(default=None, description="Last confirmation time")
    salience: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Current salience score (0.0-1.0)"
    )

    @field_validator("content", "source")
    @classmethod
    def validate_not_empty(cls, v: str) -> str:
        """Проверка что content и source не пустые."""
        if not v or not v.strip():
            raise ValueError("Поле не может быть пустым")
        return v.strip()

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: list[str]) -> list[str]:
        """Нормализация тегов."""
        return [tag.strip().lower() for tag in v if tag.strip()]

    @field_validator("confirmation_count")
    @classmethod
    def validate_confirmation_count(cls, v: int) -> int:
        """Ensure confirmation count is non-negative."""
        if v < 0:
            raise ValueError("confirmation_count cannot be negative")
        return v

    @field_validator("salience")
    @classmethod
    def validate_salience(cls, v: float) -> float:
        """Ensure salience is in valid range."""
        if not 0.0 <= v <= 1.0:
            raise ValueError("salience must be between 0.0 and 1.0")
        return v

    def invalidate(self, reason: str) -> None:
        """Mark this fact as invalidated with a reason."""
        self.status = FactStatus.INVALIDATED
        self.invalidated_at = datetime.now(UTC)
        self.invalidation_note = reason
        self.salience = 0.0

    def confirm(self) -> None:
        """Increment confirmation count and update timestamp."""
        self.confirmation_count += 1
        self.last_confirmed_at = datetime.now(UTC)
        # Increase salience slightly on confirmation, cap at 1.0
        self.salience = min(1.0, self.salience + 0.1)

    @property
    def effective_lifecycle_timestamp(self) -> datetime | None:
        """
        Timestamp at which the fact entered its current non-ACTIVE status.

        ``DISPUTED`` facts are stamped with ``disputed_at``;
        ``INVALIDATED`` and ``SUPERSEDED`` facts are stamped with
        ``invalidated_at``. ``ACTIVE`` facts have no lifecycle timestamp.
        """
        if self.status == FactStatus.DISPUTED:
            return self.disputed_at
        if self.status in (FactStatus.INVALIDATED, FactStatus.SUPERSEDED):
            return self.invalidated_at
        return None

    # ``validate_assignment=True`` re-runs field validators on every attribute
    # assignment so mutating helpers (``confirm()``, ``invalidate()``, the
    # ``decay_stale_facts`` paths in the backends) cannot silently bypass the
    # ``ge``/``le`` field constraints on ``salience``/``confirmation_count``.
    model_config = ConfigDict(
        validate_assignment=True,
        json_schema_extra={
            "example": {
                "content": "Пользователь попросил реализовать factual memory adapter",
                "source": "session_2024_01_15",
                "tags": ["task", "request"],
                "metadata": {"priority": "high"},
                "status": "active",
                "confirmation_count": 1,
                "salience": 0.5,
            }
        },
    )


class Relation(BaseModel):
    """
    Связь между двумя фактами.

    Описывает тип отношения и связанный факт.
    """

    target_id: UUID = Field(description="ID связанного факта")
    relation_type: str = Field(
        min_length=1, description="Тип связи (например: caused_by, related_to)"
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("relation_type")
    @classmethod
    def validate_relation_type(cls, v: str) -> str:
        """Нормализация типа связи."""
        if not v or not v.strip():
            raise ValueError("Тип связи не может быть пустым")
        return v.strip().lower()

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "target_id": "123e4567-e89b-12d3-a456-426614174000",
                "relation_type": "caused_by",
                "metadata": {"confidence": 0.9},
            }
        }
    )


# Обновление forward reference
FactRecord.model_rebuild()
