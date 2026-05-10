"""
Unit-тесты для моделей данных Factual Memory.
"""

from datetime import datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from atman.core.models import FactRecord, FactStatus, Relation


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


# --- SYSTEM_MAP §4.1 P2 additions ---


def test_fact_record_accepts_very_long_content():
    """SYSTEM_MAP §4.1: ``FactRecord.content`` has no upper bound — large payloads are accepted."""
    long_content = "x" * 100_000  # 100 KiB
    fact = FactRecord(content=long_content, source="long-source")
    assert len(fact.content) == 100_000
    # Round-trip through JSON to confirm it can be persisted.
    reloaded = FactRecord.model_validate_json(fact.model_dump_json())
    assert len(reloaded.content) == 100_000


def test_fact_record_with_unicode_and_emoji_content():
    """SYSTEM_MAP §4.1: non-ASCII content (incl. emoji) round-trips through JSON."""
    text = "Пользователь сказал «всё работает» — 🎉"
    fact = FactRecord(content=text, source="unicode-test")
    reloaded = FactRecord.model_validate_json(fact.model_dump_json())
    assert reloaded.content == text


# --- E24.1: FactStatus and fact validity fields ---


def test_fact_status_enum_values():
    """E24.1 AC-1: FactStatus has expected string values."""
    assert FactStatus.ACTIVE == "active"
    assert FactStatus.SUPERSEDED == "superseded"
    assert FactStatus.INVALIDATED == "invalidated"
    assert FactStatus.DISPUTED == "disputed"


def test_fact_record_default_status_is_active():
    """E24.1 AC-2: FactRecord defaults to ACTIVE status."""
    fact = FactRecord.model_validate({"content": "x", "source": "y"})
    assert fact.status == FactStatus.ACTIVE
    assert fact.superseded_by is None
    assert fact.invalidated_at is None
    assert fact.invalidation_note == ""


def test_fact_record_status_roundtrip():
    """E24.1: FactStatus round-trips through JSON serialization."""
    fact = FactRecord(
        content="Old fact",
        source="test",
        status=FactStatus.SUPERSEDED,
        invalidation_note="replaced",
        superseded_by=uuid4(),
    )
    json_data = fact.model_dump_json()
    restored = FactRecord.model_validate_json(json_data)
    assert restored.status == FactStatus.SUPERSEDED
    assert restored.invalidation_note == "replaced"
    assert restored.superseded_by == fact.superseded_by


def test_fact_record_invalidated_at_field():
    """E24.1: invalidated_at field can be set and round-trips."""
    now = datetime.now()
    fact = FactRecord(
        content="Fact",
        source="test",
        status=FactStatus.INVALIDATED,
        invalidated_at=now,
    )
    restored = FactRecord.model_validate_json(fact.model_dump_json())
    assert restored.invalidated_at is not None


def test_validate_assignment_blocks_out_of_range_salience():
    """``validate_assignment=True`` rejects out-of-range salience mutations.

    Without this, ``confirm()`` / ``invalidate()`` and the backend
    ``decay_stale_facts`` paths could push ``salience`` past its declared
    [0.0, 1.0] bounds without re-running the field validator.
    """
    fact = FactRecord(content="x", source="y")
    with pytest.raises(ValidationError):
        fact.salience = 1.5
    with pytest.raises(ValidationError):
        fact.salience = -0.1


def test_validate_assignment_blocks_negative_confirmation_count():
    """``validate_assignment=True`` rejects negative confirmation counts."""
    fact = FactRecord(content="x", source="y")
    with pytest.raises(ValidationError):
        fact.confirmation_count = -1


def test_confirm_caps_salience_and_increments_count():
    """``confirm()`` honors the upper salience bound and bumps the counter."""
    fact = FactRecord(content="x", source="y", salience=0.95, confirmation_count=2)
    fact.confirm()
    assert fact.confirmation_count == 3
    assert fact.salience == pytest.approx(1.0)
    # A second ``confirm()`` stays clamped at 1.0 rather than blowing past
    # the field validator (which would raise under validate_assignment).
    fact.confirm()
    assert fact.salience == pytest.approx(1.0)
