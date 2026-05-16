"""Tests for :mod:`atman.core.services.divergence_aggregator` (R6)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from atman.adapters.memory.in_memory_divergence_events import InMemoryDivergenceEventStore
from atman.adapters.storage.in_memory_reflection_store import InMemoryPatternStore
from atman.core.models.reflection import PatternType, ReflectionLevel
from atman.core.models.validation import (
    DivergenceEvent,
    DivergenceSeverity,
    DivergenceType,
)
from atman.core.reflection_run_keys import daily_divergence_pattern_detection_key
from atman.core.services.divergence_aggregator import (
    DivergenceAggregator,
    aggregate_divergence_events,
    collect_rupture_observations,
)

AGENT_ID = UUID("00000000-0000-4000-8000-000000000001")
DAY_START = datetime(2026, 5, 16, 0, 0, 0, tzinfo=UTC)
DAY_END = datetime(2026, 5, 16, 23, 59, 59, tzinfo=UTC)


def _event(
    *,
    div_type: DivergenceType = DivergenceType.thinking_suppression,
    severity: DivergenceSeverity = DivergenceSeverity.notable,
    when: datetime | None = None,
    agent_id: UUID = AGENT_ID,
    moment_id: UUID | None = None,
) -> DivergenceEvent:
    return DivergenceEvent(
        agent_id=agent_id,
        session_id=uuid4(),
        key_moment_id=moment_id,
        divergence_type=div_type,
        severity=severity,
        created_at=when or DAY_START + timedelta(hours=12),
    )


# ---------------------------------------------------------------------------
# Pure aggregation helpers
# ---------------------------------------------------------------------------


def test_aggregate_below_threshold_yields_nothing():
    events = [_event() for _ in range(2)]
    assert aggregate_divergence_events(events, min_count=3) == []


def test_aggregate_at_threshold_returns_group():
    events = [_event(when=DAY_START + timedelta(hours=i)) for i in range(3)]
    groups = aggregate_divergence_events(events, min_count=3)
    assert len(groups) == 1
    assert groups[0][0] == DivergenceType.thinking_suppression.value
    assert len(groups[0][1]) == 3


def test_aggregate_mixed_types():
    events = (
        [_event(div_type=DivergenceType.thinking_suppression) for _ in range(3)]
        + [_event(div_type=DivergenceType.message_entity_gap) for _ in range(3)]
        + [_event(div_type=DivergenceType.cognitive_load_spike) for _ in range(2)]
    )
    groups = aggregate_divergence_events(events, min_count=3)
    types = [g[0] for g in groups]
    assert DivergenceType.thinking_suppression.value in types
    assert DivergenceType.message_entity_gap.value in types
    assert DivergenceType.cognitive_load_spike.value not in types


def test_collect_rupture_observations_filters_and_orders():
    events = [
        _event(severity=DivergenceSeverity.notable),
        _event(
            severity=DivergenceSeverity.rupture,
            when=DAY_START + timedelta(hours=2),
        ),
        _event(
            severity=DivergenceSeverity.rupture,
            when=DAY_START + timedelta(hours=1),
        ),
    ]
    obs = collect_rupture_observations(events)
    assert len(obs) == 2
    # Time-ordered, earliest first.
    assert "01:00" in obs[0]
    assert "02:00" in obs[1]


# ---------------------------------------------------------------------------
# DivergenceAggregator orchestration
# ---------------------------------------------------------------------------


def test_analyze_persists_pattern_and_collects_ruptures():
    estore = InMemoryDivergenceEventStore()
    pstore = InMemoryPatternStore()
    moment_id = uuid4()
    for i in range(3):
        estore.write_event(_event(when=DAY_START + timedelta(hours=i + 1), moment_id=moment_id))
    estore.write_event(
        _event(
            div_type=DivergenceType.message_entity_gap,
            severity=DivergenceSeverity.rupture,
            when=DAY_START + timedelta(hours=4),
        )
    )

    agg = DivergenceAggregator(estore, pstore, min_count=3)
    patterns, ruptures = agg.analyze(
        agent_id=AGENT_ID, start=DAY_START, end=DAY_END, run_key="rk-day"
    )

    assert len(patterns) == 1
    p = patterns[0]
    assert p.pattern_type == PatternType.BEHAVIOR
    assert p.detected_by == ReflectionLevel.DAILY
    assert moment_id in p.based_on_moment_ids
    assert "thinking_suppression" in p.description

    # One rupture observation captured.
    assert len(ruptures) == 1
    assert "message_entity_gap" in ruptures[0]


def test_analyze_is_idempotent_via_detection_key():
    estore = InMemoryDivergenceEventStore()
    pstore = InMemoryPatternStore()
    for i in range(3):
        estore.write_event(_event(when=DAY_START + timedelta(hours=i + 1)))

    agg = DivergenceAggregator(estore, pstore, min_count=3)
    first = agg.analyze(agent_id=AGENT_ID, start=DAY_START, end=DAY_END, run_key="rk-day")[0]
    second = agg.analyze(agent_id=AGENT_ID, start=DAY_START, end=DAY_END, run_key="rk-day")[0]
    assert first[0].id == second[0].id
    assert len(pstore.get_all()) == 1
    # Detection key spec.
    key = daily_divergence_pattern_detection_key(
        "rk-day", DivergenceType.thinking_suppression.value
    )
    again = pstore.save_with_detection_key(key, first[0])
    assert again.id == first[0].id


def test_analyze_returns_empty_when_no_events():
    estore = InMemoryDivergenceEventStore()
    pstore = InMemoryPatternStore()
    agg = DivergenceAggregator(estore, pstore)
    assert agg.analyze(agent_id=AGENT_ID, start=DAY_START, end=DAY_END, run_key="rk") == ([], [])


def test_analyze_swallows_store_errors():
    class _Broken(InMemoryDivergenceEventStore):
        def list_in_range(self, *args, **kwargs):  # type: ignore[override]
            raise RuntimeError("db down")

    agg = DivergenceAggregator(_Broken(), InMemoryPatternStore())
    assert agg.analyze(agent_id=AGENT_ID, start=DAY_START, end=DAY_END, run_key="rk") == ([], [])


def test_analyze_empty_run_key_returns_empty():
    estore = InMemoryDivergenceEventStore()
    pstore = InMemoryPatternStore()
    for _ in range(5):
        estore.write_event(_event())
    agg = DivergenceAggregator(estore, pstore)
    assert agg.analyze(agent_id=AGENT_ID, start=DAY_START, end=DAY_END, run_key="") == ([], [])


def test_rupture_alone_does_not_create_pattern_when_below_threshold():
    estore = InMemoryDivergenceEventStore()
    pstore = InMemoryPatternStore()
    estore.write_event(
        _event(severity=DivergenceSeverity.rupture, when=DAY_START + timedelta(hours=1))
    )
    agg = DivergenceAggregator(estore, pstore, min_count=3)
    patterns, ruptures = agg.analyze(agent_id=AGENT_ID, start=DAY_START, end=DAY_END, run_key="rk")
    assert patterns == []
    assert len(ruptures) == 1
