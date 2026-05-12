"""Tests for reflection JSON fixture loading and timestamp anchoring."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

from atman.adapters.reflection.fixture_loader import (
    anchor_session_experiences_to_utc_day_window,
    load_reflection_identity,
    load_reflection_session_experiences,
)
from atman.core.models.experience import EmotionalDepth, FeltSense, KeyMoment, SessionExperience

_SID = UUID("550e8400-e29b-41d4-a716-446655440010")


def _exp(*, session_id: UUID | None = None) -> SessionExperience:
    sid = session_id or _SID
    km = KeyMoment(
        what_happened="x",
        how_i_felt=FeltSense(
            emotional_valence=0.0,
            emotional_intensity=0.5,
            depth=EmotionalDepth.MEANINGFUL,
        ),
        why_it_matters="y",
        values_touched=["z"],
    )
    return SessionExperience(
        session_id=sid,
        key_moment_ids=[km.id],
        avg_emotional_intensity=km.how_i_felt.emotional_intensity,
        has_profound_moment=km.how_i_felt.depth == EmotionalDepth.PROFOUND,
    )


def test_anchor_empty_list() -> None:
    assert anchor_session_experiences_to_utc_day_window([]) == []


def test_anchor_naive_interval_end_gets_utc() -> None:
    exp = _exp()
    naive = datetime(2026, 6, 15, 14, 30, 0)
    out = anchor_session_experiences_to_utc_day_window([exp], interval_end=naive)
    assert out[0].timestamp.tzinfo is not None


def test_anchor_end_equals_start_of_day_collapses() -> None:
    exp = _exp()
    midnight = datetime(2026, 7, 1, 0, 0, 0, tzinfo=UTC)
    out = anchor_session_experiences_to_utc_day_window([exp], interval_end=midnight)
    assert out[0].timestamp == midnight


def test_anchor_non_utc_interval_end_normalized() -> None:
    exp = _exp()
    plus3 = timezone(timedelta(hours=3))
    end = datetime(2026, 8, 10, 15, 0, 0, tzinfo=plus3)
    out = anchor_session_experiences_to_utc_day_window([exp], interval_end=end)
    assert out[0].timestamp.tzinfo == UTC


def test_anchor_timestamps_stay_within_window_with_many_experiences() -> None:
    """Many experiences in a tiny UTC window must not exceed interval_end."""
    base = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)
    end = base + timedelta(microseconds=50)
    exps = [_exp(session_id=uuid4()) for _ in range(200)]
    out = anchor_session_experiences_to_utc_day_window(exps, interval_end=end)
    assert all(e.timestamp <= end for e in out)


def test_load_reflection_json_roundtrip() -> None:
    exps = load_reflection_session_experiences()
    identity = load_reflection_identity()
    assert len(exps) >= 3
    assert identity.id is not None
