"""
Модели данных для Factual Memory Adapter.

Здесь определены структуры для хранения фактов и связей между ними.
Факты - это проверяемые утверждения без психологической интерпретации.
"""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict, description="Дополнительные метаданные")
    
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
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "content": "Пользователь попросил реализовать factual memory adapter",
                "source": "session_2024_01_15",
                "tags": ["task", "request"],
                "metadata": {"priority": "high"}
            }
        }
    )


class Relation(BaseModel):
    """
    Связь между двумя фактами.
    
    Описывает тип отношения и связанный факт.
    """
    
    target_id: UUID = Field(description="ID связанного факта")
    relation_type: str = Field(min_length=1, description="Тип связи (например: caused_by, related_to)")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
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
                "metadata": {"confidence": 0.9}
            }
        }
    )


# Обновление forward reference
FactRecord.model_rebuild()
