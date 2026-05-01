"""
Unit-тесты для моделей данных Factual Memory.
"""

from datetime import datetime
from uuid import uuid4

import pytest

from atman.core.models import FactRecord, Relation


def test_fact_record_creation():
    """Тест создания факта с валидными данными."""
    fact = FactRecord(content="Тестовый факт", source="test_source")

    assert fact.content == "Тестовый факт"
    assert fact.source == "test_source"
    assert fact.id is not None
    assert isinstance(fact.created_at, datetime)
    assert len(fact.tags) == 0
    assert len(fact.relations) == 0
    assert len(fact.metadata) == 0


def test_fact_record_with_tags():
    """Тест создания факта с тегами."""
    fact = FactRecord(content="Факт с тегами", source="test", tags=["tag1", "TAG2", " tag3 "])

    assert fact.tags == ["tag1", "tag2", "tag3"]


def test_fact_record_empty_content_validation():
    """Тест валидации пустого content."""
    with pytest.raises(ValueError):
        FactRecord(content="", source="test")

    with pytest.raises(ValueError):
        FactRecord(content="   ", source="test")


def test_fact_record_empty_source_validation():
    """Тест валидации пустого source."""
    with pytest.raises(ValueError):
        FactRecord(content="test", source="")

    with pytest.raises(ValueError):
        FactRecord(content="test", source="   ")


def test_fact_record_with_metadata():
    """Тест создания факта с метаданными."""
    metadata = {"priority": "high", "count": 42}
    fact = FactRecord(content="Факт с метаданными", source="test", metadata=metadata)

    assert fact.metadata == metadata


def test_relation_creation():
    """Тест создания связи."""
    target_id = uuid4()
    relation = Relation(target_id=target_id, relation_type="caused_by")

    assert relation.target_id == target_id
    assert relation.relation_type == "caused_by"
    assert isinstance(relation.created_at, datetime)


def test_relation_type_normalization():
    """Тест нормализации типа связи."""
    relation = Relation(target_id=uuid4(), relation_type=" RELATED_TO ")

    assert relation.relation_type == "related_to"


def test_relation_empty_type_validation():
    """Тест валидации пустого типа связи."""
    with pytest.raises(ValueError):
        Relation(target_id=uuid4(), relation_type="")

    with pytest.raises(ValueError):
        Relation(target_id=uuid4(), relation_type="   ")


def test_fact_with_relations():
    """Тест факта со связями."""
    target_id = uuid4()
    relation = Relation(target_id=target_id, relation_type="related_to")

    fact = FactRecord(content="Факт со связями", source="test", relations=[relation])

    assert len(fact.relations) == 1
    assert fact.relations[0].target_id == target_id
    assert fact.relations[0].relation_type == "related_to"


def test_fact_record_serialization():
    """Тест сериализации и десериализации факта."""
    original = FactRecord(
        content="Тест сериализации", source="test", tags=["tag1", "tag2"], metadata={"key": "value"}
    )

    json_data = original.model_dump_json()
    restored = FactRecord.model_validate_json(json_data)

    assert restored.id == original.id
    assert restored.content == original.content
    assert restored.source == original.source
    assert restored.tags == original.tags
    assert restored.metadata == original.metadata
    assert restored.created_at == original.created_at
