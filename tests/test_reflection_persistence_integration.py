"""
Integration tests for reflection persistence flow.

These tests demonstrate the integration between:
- OllamaReflectionModel (generates reflection content)
- ReflectionStore (persists to reflections table)
- Helper functions (bridge between model output and storage)
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from atman.adapters.storage.in_memory_postgres_reflection_store import InMemoryReflectionStore
from atman.adapters.storage.reflection_persistence_helper import (
    persist_daily_reflection,
    persist_deep_reflection,
    persist_micro_reflection,
)
from atman.core.models.reflection import ReflectionLevel


def test_persist_micro_reflection_after_session():
    """Micro reflection: persist after session completion."""
    store = InMemoryReflectionStore()
    agent_id = uuid4()
    session_id = uuid4()
    exp_id1 = uuid4()
    exp_id2 = uuid4()

    # Simulate: OllamaReflectionModel generated narrative update for session
    content = (
        "Session completed successfully. User was collaborative, "
        "I maintained clarity throughout the interaction."
    )

    # Persist micro reflection
    record = persist_micro_reflection(
        store,
        agent_id=agent_id,
        session_id=session_id,
        content=content,
        summary="Positive collaborative session",
        experience_refs=[exp_id1, exp_id2],
        model_provider="ollama",
        model_name="qwen3:14b",
    )

    # Verify persistence
    assert record.id is not None
    assert record.level == ReflectionLevel.MICRO
    assert record.session_id == session_id
    assert record.period_start is None  # Not used for micro
    assert record.period_end is None
    assert "collaborative" in record.content
    assert len(record.experience_refs) == 2

    # Verify retrieval
    retrieved = store.get(record.id)
    assert retrieved is not None
    assert retrieved.content == content


def test_persist_daily_reflection_pattern_detection():
    """Daily reflection: persist end-of-day pattern detection."""
    store = InMemoryReflectionStore()
    agent_id = uuid4()
    today_start = datetime(2026, 5, 10, 0, 0, 0, tzinfo=UTC)
    today_end = datetime(2026, 5, 10, 23, 59, 59, tzinfo=UTC)

    # Simulate: OllamaReflectionModel detected pattern across day's sessions
    content = (
        "Today I noticed a recurring pattern: I tend to over-explain "
        "when uncertain about a concept. This happened in 3 out of 5 "
        "sessions. Consider being more concise and asking clarifying "
        "questions instead."
    )

    # Persist daily reflection
    record = persist_daily_reflection(
        store,
        agent_id=agent_id,
        period_start=today_start,
        period_end=today_end,
        content=content,
        summary="Pattern: over-explaining when uncertain",
        experience_refs=[uuid4(), uuid4(), uuid4()],
        model_provider="ollama",
        model_name="qwen3:14b",
    )

    # Verify persistence
    assert record.id is not None
    assert record.level == ReflectionLevel.DAILY
    assert record.session_id is None  # Not used for daily
    assert record.period_start == today_start
    assert record.period_end == today_end
    assert "over-explain" in record.content
    assert len(record.experience_refs) == 3

    # Verify list_by_level
    daily_reflections = store.list_by_level(agent_id, ReflectionLevel.DAILY)
    assert len(daily_reflections) == 1
    assert daily_reflections[0].id == record.id


def test_persist_deep_reflection_with_health_assessment():
    """Deep reflection: persist with health assessment metadata."""
    store = InMemoryReflectionStore()
    agent_id = uuid4()
    week_start = datetime(2026, 5, 4, 0, 0, 0, tzinfo=UTC)
    week_end = datetime(2026, 5, 10, 23, 59, 59, tzinfo=UTC)

    # Simulate: Deep reflection with health assessment
    content = (
        "Weekly reflection: Overall emotional baseline is stable. "
        "Identity development shows healthy growth in self-awareness. "
        "Open questions remain about balancing honesty with kindness. "
        "Jahoda criteria assessment: positive_self_attitude 0.7, "
        "growth 0.8, integration 0.6. Recommend continued honest "
        "self-reflection and seeking diverse experiences."
    )

    # Persist deep reflection (health assessment stored in metadata)
    record = persist_deep_reflection(
        store,
        agent_id=agent_id,
        period_start=week_start,
        period_end=week_end,
        content=content,
        summary="Weekly health check: stable growth",
        experience_refs=[uuid4() for _ in range(10)],
        reframing_note_ids=[uuid4(), uuid4()],
        model_provider="ollama",
        model_name="qwen3:14b",
    )

    # Verify persistence
    assert record.id is not None
    assert record.level == ReflectionLevel.DEEP
    assert record.session_id is None
    assert record.period_start == week_start
    assert record.period_end == week_end
    assert len(record.experience_refs) == 10
    assert len(record.reframing_note_ids) == 2

    # Verify list_by_level
    deep_reflections = store.list_by_level(agent_id, ReflectionLevel.DEEP)
    assert len(deep_reflections) == 1


def test_persist_multiple_reflections_different_levels():
    """Store can handle reflections at all three levels."""
    store = InMemoryReflectionStore()
    agent_id = uuid4()
    now = datetime.now(UTC)

    # Micro reflection
    persist_micro_reflection(
        store,
        agent_id=agent_id,
        session_id=uuid4(),
        content="Micro reflection",
        model_provider="ollama",
    )

    # Daily reflection
    persist_daily_reflection(
        store,
        agent_id=agent_id,
        period_start=now - timedelta(days=1),
        period_end=now,
        content="Daily reflection",
        model_provider="ollama",
    )

    # Deep reflection
    persist_deep_reflection(
        store,
        agent_id=agent_id,
        period_start=now - timedelta(days=7),
        period_end=now,
        content="Deep reflection",
        model_provider="ollama",
    )

    # Verify all three are stored
    recent = store.list_recent(agent_id, limit=10)
    assert len(recent) == 3
    assert {r.level for r in recent} == {
        ReflectionLevel.MICRO,
        ReflectionLevel.DAILY,
        ReflectionLevel.DEEP,
    }


def test_persist_reflection_with_reframing_notes():
    """Store reframing_note_ids created by reflection."""
    store = InMemoryReflectionStore()
    agent_id = uuid4()
    note_ids = [uuid4(), uuid4(), uuid4()]

    record = persist_daily_reflection(
        store,
        agent_id=agent_id,
        period_start=datetime.now(UTC) - timedelta(days=1),
        period_end=datetime.now(UTC),
        content="Generated 3 reframing notes during reflection",
        reframing_note_ids=note_ids,
        model_provider="ollama",
    )

    assert record.reframing_note_ids == note_ids

    # Verify retrieval
    retrieved = store.get(record.id)
    assert retrieved is not None
    assert retrieved.reframing_note_ids == note_ids


def test_persist_reflection_tracks_model_metadata():
    """Reflection records track which model generated them."""
    store = InMemoryReflectionStore()
    agent_id = uuid4()

    # Simulate using different models
    record_ollama = persist_micro_reflection(
        store,
        agent_id=agent_id,
        session_id=uuid4(),
        content="Generated by Ollama",
        model_provider="ollama",
        model_name="qwen3.5:9b",
    )

    record_anthropic = persist_micro_reflection(
        store,
        agent_id=agent_id,
        session_id=uuid4(),
        content="Generated by Anthropic",
        model_provider="anthropic",
        model_name="claude-3.5-sonnet",
    )

    # Verify model metadata
    assert record_ollama.model_provider == "ollama"
    assert record_ollama.model_name == "qwen3.5:9b"

    assert record_anthropic.model_provider == "anthropic"
    assert record_anthropic.model_name == "claude-3.5-sonnet"


def test_list_reflections_by_experience():
    """Can query which reflections analyzed a specific experience."""
    store = InMemoryReflectionStore()
    agent_id = uuid4()
    exp_target = uuid4()
    exp_other = uuid4()

    # Two reflections reference exp_target
    r1 = persist_micro_reflection(
        store,
        agent_id=agent_id,
        session_id=uuid4(),
        content="Analyzed exp_target",
        experience_refs=[exp_target],
    )

    persist_micro_reflection(
        store,
        agent_id=agent_id,
        session_id=uuid4(),
        content="Analyzed exp_other",
        experience_refs=[exp_other],
    )

    r3 = persist_daily_reflection(
        store,
        agent_id=agent_id,
        period_start=datetime.now(UTC) - timedelta(days=1),
        period_end=datetime.now(UTC),
        content="Analyzed both",
        experience_refs=[exp_target, exp_other],
    )

    # Query reflections that analyzed exp_target
    reflections = store.list_by_experience(exp_target)

    assert len(reflections) == 2
    assert {r.id for r in reflections} == {r1.id, r3.id}
