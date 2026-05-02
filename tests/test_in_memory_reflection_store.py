"""Extra coverage for in-memory reflection stores."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from atman.adapters.storage.in_memory_reflection_store import (
    InMemoryHealthAssessmentStore,
    InMemoryPatternStore,
    InMemoryReflectionEventStore,
)
from atman.core.models.reflection import (
    CriterionAssessment,
    HealthAssessment,
    PatternCandidate,
    PatternType,
    ReflectionEvent,
    ReflectionLevel,
    YakhodaCriterion,
)


def test_pattern_store_get_by_level_and_update() -> None:
    store = InMemoryPatternStore()
    p = PatternCandidate(
        pattern_type=PatternType.BEHAVIOR,
        description="d1",
        detected_by=ReflectionLevel.DAILY,
    )
    store.save(p)
    assert store.get(p.id) == p
    assert store.get_by_level(ReflectionLevel.DAILY) == [p]
    assert store.get_by_level(ReflectionLevel.MICRO) == []

    p2 = PatternCandidate(
        id=p.id,
        pattern_type=PatternType.BEHAVIOR,
        description="d2",
        detected_by=ReflectionLevel.DAILY,
        confidence=0.9,
    )
    store.update(p2)
    got = store.get(p.id)
    assert got is not None
    assert got.description == "d2"

    with pytest.raises(ValueError, match="not found"):
        store.update(
            PatternCandidate(
                pattern_type=PatternType.BEHAVIOR,
                description="x",
                detected_by=ReflectionLevel.MICRO,
            )
        )


def test_reflection_event_store_queries() -> None:
    store = InMemoryReflectionEventStore()
    e1 = ReflectionEvent(
        reflection_level=ReflectionLevel.MICRO,
        experiences_analyzed=[],
        key_insight="a",
    )
    e2 = ReflectionEvent(
        reflection_level=ReflectionLevel.DEEP,
        experiences_analyzed=[],
        key_insight="b",
    )
    store.save(e1)
    store.save(e2)

    assert store.get(e1.id) == e1
    assert len(store.get_all()) == 2
    assert len(store.get_by_level(ReflectionLevel.MICRO)) == 1
    recent = store.get_recent(limit=1)
    assert len(recent) == 1


def _full_criteria() -> dict[YakhodaCriterion, CriterionAssessment]:
    criteria: dict[YakhodaCriterion, CriterionAssessment] = {}
    for criterion in YakhodaCriterion:
        criteria[criterion] = CriterionAssessment(
            criterion=criterion,
            score=0.6,
            evidence=["e"],
            concerns=["c"],
        )
    return criteria


def test_health_assessment_store_get_latest() -> None:
    store = InMemoryHealthAssessmentStore()
    assert store.get_latest() is None

    a1 = HealthAssessment(
        criteria=_full_criteria(),
        overall_score=0.5,
        timestamp=datetime(2025, 1, 1, tzinfo=UTC),
    )
    a2 = HealthAssessment(
        criteria=_full_criteria(),
        overall_score=0.8,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
    )
    store.save(a1)
    store.save(a2)

    latest = store.get_latest()
    assert latest is not None
    assert latest.overall_score == 0.8
    assert store.get(a2.id) == a2
