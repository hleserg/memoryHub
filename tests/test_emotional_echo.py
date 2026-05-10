"""Tests for EmotionalEcho service (E24.7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from atman.adapters.storage.in_memory_state_store import InMemoryStateStore
from atman.core.models import KeyMoment, SessionExperience
from atman.core.models.experience import EmotionalDepth, ExperienceRecord, FeltSense
from atman.core.services.emotional_echo import EmotionalEcho


def _experience(
    *,
    session_id=None,
    timestamp: datetime,
    valence: float,
    intensity: float,
    depth: EmotionalDepth = EmotionalDepth.MEANINGFUL,
    what_happened: str = "moment",
) -> SessionExperience:
    moment = KeyMoment(
        what_happened=what_happened,
        when=timestamp,
        how_i_felt=FeltSense(
            emotional_valence=valence,
            emotional_intensity=intensity,
            depth=depth,
        ),
        why_it_matters="matters",
    )
    return SessionExperience(
        session_id=session_id or uuid4(),
        timestamp=timestamp,
        key_moments=[moment],
    )


@pytest.fixture()
def now() -> datetime:
    return datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


def test_build_echo_returns_empty_when_store_empty(now: datetime):
    store = InMemoryStateStore()
    echo = EmotionalEcho(state_store=store)
    assert echo.build_echo(current_time=now) == []


def test_build_echo_orders_by_recency_times_intensity(now: datetime):
    store = InMemoryStateStore()
    recent = _experience(
        timestamp=now - timedelta(hours=2),
        valence=0.5,
        intensity=0.4,
        depth=EmotionalDepth.SURFACE,
    )
    older_intense = _experience(
        timestamp=now - timedelta(hours=24),
        valence=-0.4,
        intensity=0.9,
        depth=EmotionalDepth.PROFOUND,
    )
    store.create_experience(ExperienceRecord(experience=recent))
    store.create_experience(ExperienceRecord(experience=older_intense))

    service = EmotionalEcho(state_store=store, recency_halflife_hours=24)
    echoes = service.build_echo(current_time=now)
    assert len(echoes) == 2
    # Recent surface vs older profound: profound depth should dominate intensity
    # but recent will have ~1.0 recency vs ~0.5 for older. Ordering is data-driven —
    # assert ordering by echo_score desc.
    assert echoes[0].echo_score >= echoes[1].echo_score


def test_build_echo_excludes_session(now: datetime):
    store = InMemoryStateStore()
    excluded_session = uuid4()
    keep = _experience(
        timestamp=now - timedelta(hours=1),
        valence=0.1,
        intensity=0.5,
    )
    drop = _experience(
        session_id=excluded_session,
        timestamp=now - timedelta(hours=1),
        valence=0.1,
        intensity=0.5,
    )
    store.create_experience(ExperienceRecord(experience=keep))
    store.create_experience(ExperienceRecord(experience=drop))

    service = EmotionalEcho(state_store=store)
    echoes = service.build_echo(
        exclude_session_id=str(excluded_session),
        current_time=now,
    )
    assert len(echoes) == 1
    assert echoes[0].experience_id == str(keep.id)


def test_build_echo_respects_lookback_window(now: datetime):
    store = InMemoryStateStore()
    inside = _experience(
        timestamp=now - timedelta(days=2),
        valence=0.0,
        intensity=0.5,
    )
    outside = _experience(
        timestamp=now - timedelta(days=30),
        valence=0.0,
        intensity=0.9,
    )
    store.create_experience(ExperienceRecord(experience=inside))
    store.create_experience(ExperienceRecord(experience=outside))

    service = EmotionalEcho(state_store=store, lookback_days=7)
    echoes = service.build_echo(current_time=now)
    assert {e.experience_id for e in echoes} == {str(inside.id)}


def test_build_echo_caps_to_max_echoes(now: datetime):
    store = InMemoryStateStore()
    for _ in range(5):
        store.create_experience(
            ExperienceRecord(
                experience=_experience(
                    timestamp=now - timedelta(hours=1),
                    valence=0.0,
                    intensity=0.5,
                )
            )
        )
    service = EmotionalEcho(state_store=store, max_echoes=2)
    echoes = service.build_echo(current_time=now)
    assert len(echoes) == 2


def test_build_context_summary_has_no_echoes_message(now: datetime):
    service = EmotionalEcho(state_store=InMemoryStateStore())
    assert service.build_context_summary(current_time=now) == "No recent emotional context."


def test_build_context_summary_renders_tones(now: datetime):
    store = InMemoryStateStore()
    store.create_experience(
        ExperienceRecord(
            experience=_experience(
                timestamp=now - timedelta(hours=1),
                valence=0.6,
                intensity=0.5,
                what_happened="positive moment that mattered",
            )
        )
    )
    store.create_experience(
        ExperienceRecord(
            experience=_experience(
                timestamp=now - timedelta(hours=1),
                valence=-0.6,
                intensity=0.5,
                what_happened="negative moment that mattered",
            )
        )
    )
    store.create_experience(
        ExperienceRecord(
            experience=_experience(
                timestamp=now - timedelta(hours=1),
                valence=0.0,
                intensity=0.4,
                what_happened="neutral moment that mattered",
            )
        )
    )
    summary = EmotionalEcho(state_store=store).build_context_summary(current_time=now)
    assert "positive" in summary
    assert "negative" in summary
    assert "neutral" in summary


def test_build_context_summary_truncation_only_for_long_text(now: datetime):
    """Short ``what_happened`` strings render verbatim; long ones get a ``...`` suffix."""
    store = InMemoryStateStore()
    short_text = "short moment"
    long_text = "x" * 100  # > 80 chars triggers truncation
    store.create_experience(
        ExperienceRecord(
            experience=_experience(
                timestamp=now - timedelta(hours=1),
                valence=0.5,
                intensity=0.5,
                what_happened=short_text,
            )
        )
    )
    store.create_experience(
        ExperienceRecord(
            experience=_experience(
                timestamp=now - timedelta(hours=1),
                valence=0.5,
                intensity=0.5,
                what_happened=long_text,
            )
        )
    )
    summary = EmotionalEcho(state_store=store).build_context_summary(current_time=now)

    # Short text should appear verbatim with no preceding "..." sentinel.
    assert f"- {short_text} (" in summary
    # Long text is truncated to 80 chars and ends with "...".
    assert f"- {'x' * 80}... (" in summary


def test_get_dominant_emotional_tone_zero_when_empty(now: datetime):
    service = EmotionalEcho(state_store=InMemoryStateStore())
    assert service.get_dominant_emotional_tone(current_time=now) == 0.0


def test_get_dominant_emotional_tone_weighted_average(now: datetime):
    store = InMemoryStateStore()
    store.create_experience(
        ExperienceRecord(
            experience=_experience(
                timestamp=now - timedelta(hours=1),
                valence=0.8,
                intensity=0.9,
            )
        )
    )
    store.create_experience(
        ExperienceRecord(
            experience=_experience(
                timestamp=now - timedelta(hours=1),
                valence=-0.4,
                intensity=0.2,
            )
        )
    )
    tone = EmotionalEcho(state_store=store).get_dominant_emotional_tone(current_time=now)
    # Higher-intensity positive valence dominates
    assert tone > 0.0
