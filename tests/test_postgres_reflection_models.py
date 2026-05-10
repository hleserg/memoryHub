"""
Tests for PostgreSQL reflection persistence models.

These tests verify:
- Field validation (content not empty, schema_version >= 1, etc.)
- Serialization/deserialization to/from JSON
- Correct handling of optional fields (session_id for micro, period_* for daily/deep)
- UUID list validation
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from atman.core.models.reflection import ReflectionLevel, ReflectionRecord


def test_reflection_record_minimal_micro():
    """Minimal valid micro reflection record."""
    agent_id = uuid4()
    session_id = uuid4()

    record = ReflectionRecord(
        agent_id=agent_id,
        level=ReflectionLevel.MICRO,
        session_id=session_id,
        content="Session completed successfully.",
    )

    assert record.id is None  # Not yet inserted
    assert record.agent_id == agent_id
    assert record.level == ReflectionLevel.MICRO
    assert record.session_id == session_id
    assert record.period_start is None
    assert record.period_end is None
    assert record.content == "Session completed successfully."
    assert record.summary is None
    assert record.experience_refs == []
    assert record.reframing_note_ids == []
    assert record.model_provider is None
    assert record.model_name is None
    assert record.schema_version == 1
    assert record.metadata == {}


def test_reflection_record_minimal_daily():
    """Minimal valid daily reflection record."""
    agent_id = uuid4()
    period_start = datetime(2026, 5, 10, 0, 0, 0, tzinfo=UTC)
    period_end = datetime(2026, 5, 10, 23, 59, 59, tzinfo=UTC)

    record = ReflectionRecord(
        agent_id=agent_id,
        level=ReflectionLevel.DAILY,
        period_start=period_start,
        period_end=period_end,
        content="Today I noticed a pattern of over-explaining when uncertain.",
    )

    assert record.level == ReflectionLevel.DAILY
    assert record.session_id is None  # NULL for daily
    assert record.period_start == period_start
    assert record.period_end == period_end
    assert record.content == "Today I noticed a pattern of over-explaining when uncertain."


def test_reflection_record_full_fields():
    """Reflection record with all optional fields populated."""
    agent_id = uuid4()
    session_id = uuid4()
    exp_id_1 = uuid4()
    exp_id_2 = uuid4()
    note_id_1 = uuid4()

    record = ReflectionRecord(
        id=42,  # Simulating a retrieved record
        agent_id=agent_id,
        level=ReflectionLevel.MICRO,
        session_id=session_id,
        content="Detailed reflection on the session",
        summary="Good session with clear progress",
        experience_refs=[exp_id_1, exp_id_2],
        reframing_note_ids=[note_id_1],
        model_provider="ollama",
        model_name="qwen3:14b",
        schema_version=1,
        metadata={"temperature": 0.7, "top_p": 0.9},
    )

    assert record.id == 42
    assert record.summary == "Good session with clear progress"
    assert record.experience_refs == [exp_id_1, exp_id_2]
    assert record.reframing_note_ids == [note_id_1]
    assert record.model_provider == "ollama"
    assert record.model_name == "qwen3:14b"
    assert record.metadata == {"temperature": 0.7, "top_p": 0.9}


def test_reflection_record_empty_content_fails():
    """Empty content should fail validation."""
    agent_id = uuid4()

    with pytest.raises(ValidationError) as exc_info:
        ReflectionRecord(
            agent_id=agent_id,
            level=ReflectionLevel.MICRO,
            content="",
        )

    errors = exc_info.value.errors()
    assert any(e["loc"] == ("content",) for e in errors)


def test_reflection_record_whitespace_only_content_fails():
    """Whitespace-only content should fail validation."""
    agent_id = uuid4()

    with pytest.raises(ValidationError) as exc_info:
        ReflectionRecord(
            agent_id=agent_id,
            level=ReflectionLevel.MICRO,
            content="   \n\t  ",
        )

    errors = exc_info.value.errors()
    assert any(e["loc"] == ("content",) for e in errors)


def test_reflection_record_invalid_schema_version_fails():
    """Schema version < 1 should fail validation."""
    agent_id = uuid4()

    with pytest.raises(ValidationError) as exc_info:
        ReflectionRecord(
            agent_id=agent_id,
            level=ReflectionLevel.MICRO,
            content="Valid content",
            schema_version=0,
        )

    errors = exc_info.value.errors()
    assert any(e["loc"] == ("schema_version",) for e in errors)


def test_reflection_record_json_roundtrip():
    """Serialization to JSON and back should preserve data."""
    agent_id = uuid4()
    session_id = uuid4()
    exp_id = uuid4()
    created_at = datetime(2026, 5, 10, 12, 30, 0, tzinfo=UTC)

    original = ReflectionRecord(
        id=123,
        agent_id=agent_id,
        level=ReflectionLevel.MICRO,
        session_id=session_id,
        created_at=created_at,
        content="Reflection content",
        summary="Summary",
        experience_refs=[exp_id],
        model_provider="ollama",
        model_name="qwen3:14b",
        schema_version=1,
        metadata={"key": "value"},
    )

    # Serialize to JSON
    json_data = original.model_dump_json()

    # Deserialize from JSON
    restored = ReflectionRecord.model_validate_json(json_data)

    assert restored.id == original.id
    assert restored.agent_id == original.agent_id
    assert restored.level == original.level
    assert restored.session_id == original.session_id
    assert restored.created_at == original.created_at
    assert restored.content == original.content
    assert restored.summary == original.summary
    assert restored.experience_refs == original.experience_refs
    assert restored.model_provider == original.model_provider
    assert restored.model_name == original.model_name
    assert restored.schema_version == original.schema_version
    assert restored.metadata == original.metadata


def test_reflection_record_dict_roundtrip():
    """Serialization to dict and back should preserve data."""
    agent_id = uuid4()
    period_start = datetime(2026, 5, 10, 0, 0, 0, tzinfo=UTC)
    period_end = datetime(2026, 5, 10, 23, 59, 59, tzinfo=UTC)

    original = ReflectionRecord(
        agent_id=agent_id,
        level=ReflectionLevel.DAILY,
        period_start=period_start,
        period_end=period_end,
        content="Daily reflection",
    )

    # Serialize to dict
    data_dict = original.model_dump()

    # Deserialize from dict
    restored = ReflectionRecord.model_validate(data_dict)

    assert restored.agent_id == original.agent_id
    assert restored.level == original.level
    assert restored.period_start == original.period_start
    assert restored.period_end == original.period_end
    assert restored.content == original.content


def test_reflection_record_experience_refs_empty_list():
    """Empty experience_refs list is valid."""
    agent_id = uuid4()

    record = ReflectionRecord(
        agent_id=agent_id,
        level=ReflectionLevel.DEEP,
        content="Deep reflection without specific experience references",
        experience_refs=[],
    )

    assert record.experience_refs == []


def test_reflection_record_multiple_experience_refs():
    """Multiple experience references are preserved in order."""
    agent_id = uuid4()
    exp_ids = [uuid4() for _ in range(5)]

    record = ReflectionRecord(
        agent_id=agent_id,
        level=ReflectionLevel.DAILY,
        content="Analyzed multiple experiences",
        experience_refs=exp_ids,
    )

    assert record.experience_refs == exp_ids


def test_reflection_record_reframing_note_ids_preserved():
    """Reframing note IDs are preserved."""
    agent_id = uuid4()
    note_ids = [uuid4() for _ in range(3)]

    record = ReflectionRecord(
        agent_id=agent_id,
        level=ReflectionLevel.DEEP,
        content="Deep reflection producing reframing notes",
        reframing_note_ids=note_ids,
    )

    assert record.reframing_note_ids == note_ids


def test_reflection_record_metadata_arbitrary_json():
    """Metadata field accepts arbitrary JSON-serializable data."""
    agent_id = uuid4()

    record = ReflectionRecord(
        agent_id=agent_id,
        level=ReflectionLevel.MICRO,
        content="Test",
        metadata={
            "nested": {"key": "value"},
            "list": [1, 2, 3],
            "string": "test",
            "number": 42,
            "bool": True,
        },
    )

    assert record.metadata["nested"]["key"] == "value"
    assert record.metadata["list"] == [1, 2, 3]
    assert record.metadata["bool"] is True


def test_reflection_record_all_levels_valid():
    """All three reflection levels are valid."""
    agent_id = uuid4()

    for level in [ReflectionLevel.MICRO, ReflectionLevel.DAILY, ReflectionLevel.DEEP]:
        record = ReflectionRecord(
            agent_id=agent_id,
            level=level,
            content=f"Reflection at {level} level",
        )
        assert record.level == level


def test_reflection_record_content_stripped():
    """Leading/trailing whitespace in content is stripped."""
    agent_id = uuid4()

    record = ReflectionRecord(
        agent_id=agent_id,
        level=ReflectionLevel.MICRO,
        content="  Content with spaces  \n",
    )

    assert record.content == "Content with spaces"


def test_reflection_record_default_created_at():
    """created_at defaults to current UTC time."""
    agent_id = uuid4()
    before = datetime.now(UTC)

    record = ReflectionRecord(
        agent_id=agent_id,
        level=ReflectionLevel.MICRO,
        content="Test",
    )

    after = datetime.now(UTC)

    assert before <= record.created_at <= after


def test_reflection_record_explicit_created_at():
    """Explicit created_at is preserved."""
    agent_id = uuid4()
    explicit_time = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

    record = ReflectionRecord(
        agent_id=agent_id,
        level=ReflectionLevel.MICRO,
        content="Test",
        created_at=explicit_time,
    )

    assert record.created_at == explicit_time
