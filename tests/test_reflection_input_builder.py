"""Tests for prepare_reflection_input (memory optimization)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from atman.core.models.experience import EmotionalDepth, FeltSense, KeyMoment
from atman.core.services.reflection_input_builder import prepare_reflection_input


def _moment(
    *,
    what_happened: str = "something",
    salience: float = 0.5,
    session_id=None,
    markers: dict | None = None,
) -> KeyMoment:
    return KeyMoment(
        what_happened=what_happened,
        when=datetime.now(UTC),
        how_i_felt=FeltSense(
            emotional_valence=0.0,
            emotional_intensity=0.5,
            depth=EmotionalDepth.MEANINGFUL,
        ),
        why_it_matters="test",
        salience=salience,
        session_id=session_id,
        structured_markers=markers,
    )


def test_empty_input():
    result = prepare_reflection_input([])
    assert result.total_selected == 0
    assert result.total_skipped == 0
    assert result.session_summaries == []
    assert result.remaining_moments == []


def test_sorts_by_salience_descending():
    moments = [_moment(salience=0.2), _moment(salience=0.9), _moment(salience=0.5)]
    result = prepare_reflection_input(moments, max_moments=10)
    top = result.session_summaries[0].top_moments
    assert top[0].salience >= top[-1].salience


def test_cap_at_max_moments():
    moments = [_moment(salience=float(i) / 100) for i in range(50)]
    result = prepare_reflection_input(moments, max_moments=30)
    assert result.total_selected == 30
    assert result.total_skipped == 20
    assert len(result.remaining_moments) == 20


def test_remaining_are_lowest_salience():
    moments = [_moment(salience=float(i) / 10) for i in range(10)]
    result = prepare_reflection_input(moments, max_moments=7)
    max_remaining = max(m.salience for m in result.remaining_moments)
    min_selected = min(m.salience for s in result.session_summaries for m in s.top_moments)
    assert max_remaining <= min_selected


def test_groups_by_session_id():
    sid1, sid2 = uuid4(), uuid4()
    moments = [
        _moment(salience=0.9, session_id=sid1),
        _moment(salience=0.8, session_id=sid1),
        _moment(salience=0.7, session_id=sid2),
    ]
    result = prepare_reflection_input(moments, max_moments=10)
    session_ids = {s.session_id for s in result.session_summaries}
    assert sid1 in session_ids
    assert sid2 in session_ids


def test_top_moments_capped_at_3_per_session():
    sid = uuid4()
    moments = [_moment(salience=float(i) / 10, session_id=sid) for i in range(8)]
    result = prepare_reflection_input(moments, max_moments=10)
    summary = next(s for s in result.session_summaries if s.session_id == sid)
    assert len(summary.top_moments) <= 3


def test_total_count_reflects_all_session_moments():
    sid = uuid4()
    moments = [_moment(salience=0.5, session_id=sid) for _ in range(5)]
    result = prepare_reflection_input(moments, max_moments=10)
    summary = next(s for s in result.session_summaries if s.session_id == sid)
    assert summary.total_count == 5


def test_marker_counts_aggregated():
    sid = uuid4()
    moments = [
        _moment(session_id=sid, markers={"growth": True, "fear": True}),
        _moment(session_id=sid, markers={"growth": True}),
        _moment(session_id=sid, markers=None),
    ]
    result = prepare_reflection_input(moments, max_moments=10)
    summary = next(s for s in result.session_summaries if s.session_id == sid)
    assert summary.marker_counts.get("growth") == 2
    assert summary.marker_counts.get("fear") == 1


def test_none_session_id_grouped_together():
    moments = [_moment(salience=0.5, session_id=None) for _ in range(3)]
    result = prepare_reflection_input(moments, max_moments=10)
    none_summaries = [s for s in result.session_summaries if s.session_id is None]
    assert len(none_summaries) == 1
    assert none_summaries[0].total_count == 3


def test_summaries_sorted_by_highest_salience():
    sid1, sid2, sid3 = uuid4(), uuid4(), uuid4()
    moments = [
        _moment(salience=0.3, session_id=sid1),
        _moment(salience=0.9, session_id=sid2),
        _moment(salience=0.6, session_id=sid3),
    ]
    result = prepare_reflection_input(moments, max_moments=10)
    top_saliences = [s.top_moments[0].salience for s in result.session_summaries]
    assert top_saliences == sorted(top_saliences, reverse=True)


def test_max_moments_exactly_met():
    moments = [_moment() for _ in range(5)]
    result = prepare_reflection_input(moments, max_moments=5)
    assert result.total_selected == 5
    assert result.total_skipped == 0
    assert result.remaining_moments == []
