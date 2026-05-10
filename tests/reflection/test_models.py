"""Tests for reflection persistence models."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from atman.reflection.models import ReflectionEvent, ReflectionLevel


class TestReflectionEvent:
    """Tests for ReflectionEvent model."""

    def test_create_minimal_reflection_event(self) -> None:
        """Test creating a reflection event with minimal fields."""
        agent_id = uuid4()
        event = ReflectionEvent(
            agent_id=agent_id,
            level=ReflectionLevel.DAILY,
            content="I noticed a pattern in my recent interactions",
        )

        assert event.agent_id == agent_id
        assert event.level == ReflectionLevel.DAILY
        assert event.content == "I noticed a pattern in my recent interactions"
        assert event.id is None
        assert event.session_id is None
        assert event.period_start is None
        assert event.period_end is None
        assert event.summary is None
        assert event.experience_refs == []
        assert event.reframing_note_ids == []
        assert event.model_provider is None
        assert event.model_name is None
        assert event.schema_version == 1
        assert event.metadata == {}

    def test_create_full_reflection_event(self) -> None:
        """Test creating a reflection event with all fields."""
        agent_id = uuid4()
        session_id = uuid4()
        exp_ref1 = uuid4()
        exp_ref2 = uuid4()
        note_ref1 = uuid4()

        event = ReflectionEvent(
            id=123,
            agent_id=agent_id,
            level=ReflectionLevel.MICRO,
            created_at=datetime(2026, 5, 10, 12, 0, 0, tzinfo=UTC),
            session_id=session_id,
            period_start=datetime(2026, 5, 10, 0, 0, 0, tzinfo=UTC),
            period_end=datetime(2026, 5, 10, 23, 59, 59, tzinfo=UTC),
            content="This is a detailed reflection content",
            summary="Brief summary",
            experience_refs=[exp_ref1, exp_ref2],
            reframing_note_ids=[note_ref1],
            model_provider="ollama",
            model_name="qwen3.5:9b",
            schema_version=1,
            metadata={"key": "value"},
        )

        assert event.id == 123
        assert event.agent_id == agent_id
        assert event.level == ReflectionLevel.MICRO
        assert event.session_id == session_id
        assert event.period_start is not None
        assert event.period_end is not None
        assert event.summary == "Brief summary"
        assert len(event.experience_refs) == 2
        assert len(event.reframing_note_ids) == 1
        assert event.model_provider == "ollama"
        assert event.model_name == "qwen3.5:9b"

    def test_content_cannot_be_empty(self) -> None:
        """Test that content cannot be empty."""
        agent_id = uuid4()

        with pytest.raises(ValueError, match="content cannot be empty"):
            ReflectionEvent(
                agent_id=agent_id,
                level=ReflectionLevel.DAILY,
                content="",
            )

    def test_content_cannot_be_whitespace_only(self) -> None:
        """Test that content cannot be whitespace only."""
        agent_id = uuid4()

        with pytest.raises(ValueError, match="content cannot be empty"):
            ReflectionEvent(
                agent_id=agent_id,
                level=ReflectionLevel.DAILY,
                content="   ",
            )

    def test_content_is_stripped(self) -> None:
        """Test that content is stripped of leading/trailing whitespace."""
        agent_id = uuid4()
        event = ReflectionEvent(
            agent_id=agent_id,
            level=ReflectionLevel.DAILY,
            content="  valid content  ",
        )

        assert event.content == "valid content"

    def test_summary_is_stripped(self) -> None:
        """Test that summary is stripped of leading/trailing whitespace."""
        agent_id = uuid4()
        event = ReflectionEvent(
            agent_id=agent_id,
            level=ReflectionLevel.DAILY,
            content="valid content",
            summary="  summary  ",
        )

        assert event.summary == "summary"

    def test_summary_whitespace_becomes_none(self) -> None:
        """Test that whitespace-only summary becomes None."""
        agent_id = uuid4()
        event = ReflectionEvent(
            agent_id=agent_id,
            level=ReflectionLevel.DAILY,
            content="valid content",
            summary="  ",
        )

        assert event.summary is None

    def test_model_provider_is_stripped(self) -> None:
        """Test that model_provider is stripped."""
        agent_id = uuid4()
        event = ReflectionEvent(
            agent_id=agent_id,
            level=ReflectionLevel.DAILY,
            content="valid content",
            model_provider="  ollama  ",
        )

        assert event.model_provider == "ollama"

    def test_model_name_is_stripped(self) -> None:
        """Test that model_name is stripped."""
        agent_id = uuid4()
        event = ReflectionEvent(
            agent_id=agent_id,
            level=ReflectionLevel.DAILY,
            content="valid content",
            model_name="  qwen3.5:9b  ",
        )

        assert event.model_name == "qwen3.5:9b"

    def test_reflection_level_enum(self) -> None:
        """Test ReflectionLevel enum values."""
        assert ReflectionLevel.MICRO.value == "micro"
        assert ReflectionLevel.DAILY.value == "daily"
        assert ReflectionLevel.DEEP.value == "deep"

    def test_reflection_level_micro(self) -> None:
        """Test creating a micro reflection."""
        agent_id = uuid4()
        session_id = uuid4()

        event = ReflectionEvent(
            agent_id=agent_id,
            level=ReflectionLevel.MICRO,
            session_id=session_id,
            content="Micro reflection content",
        )

        assert event.level == ReflectionLevel.MICRO
        assert event.session_id == session_id
        assert event.period_start is None
        assert event.period_end is None

    def test_reflection_level_daily(self) -> None:
        """Test creating a daily reflection."""
        agent_id = uuid4()
        period_start = datetime(2026, 5, 10, 0, 0, 0, tzinfo=UTC)
        period_end = datetime(2026, 5, 10, 23, 59, 59, tzinfo=UTC)

        event = ReflectionEvent(
            agent_id=agent_id,
            level=ReflectionLevel.DAILY,
            period_start=period_start,
            period_end=period_end,
            content="Daily reflection content",
        )

        assert event.level == ReflectionLevel.DAILY
        assert event.session_id is None
        assert event.period_start == period_start
        assert event.period_end == period_end

    def test_reflection_level_deep(self) -> None:
        """Test creating a deep reflection."""
        agent_id = uuid4()
        period_start = datetime(2026, 5, 1, 0, 0, 0, tzinfo=UTC)
        period_end = datetime(2026, 5, 7, 23, 59, 59, tzinfo=UTC)

        event = ReflectionEvent(
            agent_id=agent_id,
            level=ReflectionLevel.DEEP,
            period_start=period_start,
            period_end=period_end,
            content="Deep reflection content",
        )

        assert event.level == ReflectionLevel.DEEP
        assert event.session_id is None
        assert event.period_start == period_start
        assert event.period_end == period_end

    def test_experience_refs_defaults_to_empty_list(self) -> None:
        """Test that experience_refs defaults to empty list."""
        agent_id = uuid4()
        event = ReflectionEvent(
            agent_id=agent_id,
            level=ReflectionLevel.DAILY,
            content="valid content",
        )

        assert event.experience_refs == []

    def test_reframing_note_ids_defaults_to_empty_list(self) -> None:
        """Test that reframing_note_ids defaults to empty list."""
        agent_id = uuid4()
        event = ReflectionEvent(
            agent_id=agent_id,
            level=ReflectionLevel.DAILY,
            content="valid content",
        )

        assert event.reframing_note_ids == []

    def test_metadata_defaults_to_empty_dict(self) -> None:
        """Test that metadata defaults to empty dict."""
        agent_id = uuid4()
        event = ReflectionEvent(
            agent_id=agent_id,
            level=ReflectionLevel.DAILY,
            content="valid content",
        )

        assert event.metadata == {}

    def test_schema_version_defaults_to_1(self) -> None:
        """Test that schema_version defaults to 1."""
        agent_id = uuid4()
        event = ReflectionEvent(
            agent_id=agent_id,
            level=ReflectionLevel.DAILY,
            content="valid content",
        )

        assert event.schema_version == 1

    def test_created_at_defaults_to_now(self) -> None:
        """Test that created_at defaults to current time."""
        agent_id = uuid4()
        before = datetime.now(UTC)
        event = ReflectionEvent(
            agent_id=agent_id,
            level=ReflectionLevel.DAILY,
            content="valid content",
        )
        after = datetime.now(UTC)

        assert before <= event.created_at <= after

    def test_model_validation_assignment(self) -> None:
        """Test that model validates on assignment."""
        agent_id = uuid4()
        event = ReflectionEvent(
            agent_id=agent_id,
            level=ReflectionLevel.DAILY,
            content="valid content",
        )

        # Valid assignment
        event.content = "new valid content"
        assert event.content == "new valid content"

        # Invalid assignment
        with pytest.raises(ValueError, match="content cannot be empty"):
            event.content = ""
