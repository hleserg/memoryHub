"""Tests for R11 — Identity-level signals in DeepReflectionService._propose_identity_revision."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from atman.adapters.reflection.mock_reflection_model import MockReflectionModel
from atman.adapters.storage.in_memory_reflection_store import (
    InMemoryHealthAssessmentStore,
    InMemoryPatternStore,
    InMemoryReflectionEventStore,
)
from atman.core.models.identity import Identity
from atman.core.models.reflection import (
    CriterionAssessment,
    HealthAssessment,
    JahodaCriterion,
    PatternCandidate,
    PatternType,
    ReflectionLevel,
)
from atman.core.services.reflection_service import DeepReflectionService


def _service() -> DeepReflectionService:
    return DeepReflectionService(
        session_repo=None,  # type: ignore[arg-type]
        identity_repo=None,  # type: ignore[arg-type]
        narrative_repo=None,  # type: ignore[arg-type]
        pattern_store=InMemoryPatternStore(),
        health_store=InMemoryHealthAssessmentStore(),
        reflection_model=MockReflectionModel(),
        event_store=InMemoryReflectionEventStore(),
    )


def _pattern(
    description: str, *, potential_habit: str = "", potential_principle: str = ""
) -> PatternCandidate:
    return PatternCandidate(
        pattern_type=PatternType.BEHAVIOR,
        description=description,
        detected_by=ReflectionLevel.DEEP,
        potential_habit=potential_habit,
        potential_principle=potential_principle,
    )


def _health(score: float = 0.7) -> HealthAssessment:
    return HealthAssessment(
        criteria={c: CriterionAssessment(criterion=c, score=score) for c in JahodaCriterion},
        overall_score=score,
        summary="ok",
        recommendations=[],
        timestamp=datetime.now(UTC),
    )


@dataclass
class _Stance:
    formulated: int = 0
    promoted: int = 0


@dataclass
class _Relation:
    formulated: int = 0
    pairs_considered: int = 0


@dataclass
class _Merge:
    merged: int = 0
    ignored: int = 0
    skipped: int = 0


@dataclass
class _Triage:
    resolved_count: int = 0
    requires_attention_count: int = 0
    skipped_count: int = 0


# ---------------------------------------------------------------------------
# Existing behaviour preserved
# ---------------------------------------------------------------------------


def test_no_signals_falls_back_to_default_text():
    s = _service()
    out = s._propose_identity_revision(Identity(), [], _health(0.7))
    assert out == "No identity changes proposed"


def test_potential_habit_and_principle_still_surface():
    s = _service()
    out = s._propose_identity_revision(
        Identity(),
        [_pattern("p", potential_habit="be present", potential_principle="trust slowness")],
        _health(0.7),
    )
    assert "New habit: be present" in out
    assert "New principle: trust slowness" in out


# ---------------------------------------------------------------------------
# R5 marker-driven signals
# ---------------------------------------------------------------------------


def test_growth_indicator_progress_surfaces_promotion_hint():
    s = _service()
    p = _pattern(
        "structured_markers signal 'growth_indicator'='progress' observed in 6 moments today"
    )
    out = s._propose_identity_revision(Identity(), [p], _health(0.7))
    assert "Growth observed" in out


def test_growth_indicator_regression_surfaces_review_hint():
    s = _service()
    p = _pattern(
        "structured_markers signal 'growth_indicator'='regression' observed in 5 moments today"
    )
    out = s._propose_identity_revision(Identity(), [p], _health(0.7))
    assert "Regression on growth_indicator" in out


def test_agency_level_high_surfaces_ownership_hint():
    s = _service()
    p = _pattern("structured_markers signal 'agency_level'='high' observed in 6 moments today")
    out = s._propose_identity_revision(Identity(), [p], _health(0.7))
    assert "ownership" in out


# ---------------------------------------------------------------------------
# R7 stance signals
# ---------------------------------------------------------------------------


def test_promoted_stances_suggest_lifting_into_principles():
    s = _service()
    out = s._propose_identity_revision(
        Identity(), [], _health(0.7), stance_outcome=_Stance(promoted=2)
    )
    assert "promoted to non-provisional" in out


def test_many_new_stances_suggest_governance_review():
    s = _service()
    out = s._propose_identity_revision(
        Identity(), [], _health(0.7), stance_outcome=_Stance(formulated=5)
    )
    assert "governance / R11.5" in out


def test_few_new_stances_silent():
    s = _service()
    out = s._propose_identity_revision(
        Identity(), [], _health(0.7), stance_outcome=_Stance(formulated=1)
    )
    assert out == "No identity changes proposed"


# ---------------------------------------------------------------------------
# R9 relation, R10 merge, R8 triage
# ---------------------------------------------------------------------------


def test_many_new_relations_request_principle_verification():
    s = _service()
    out = s._propose_identity_revision(
        Identity(), [], _health(0.7), relation_outcome=_Relation(formulated=4)
    )
    assert "don't contradict existing principles" in out


def test_merge_outcome_requests_principle_re_verification():
    s = _service()
    out = s._propose_identity_revision(Identity(), [], _health(0.7), merge_outcome=_Merge(merged=2))
    assert "re-verify principles" in out


def test_triage_attention_records_deferral():
    s = _service()
    out = s._propose_identity_revision(
        Identity(),
        [],
        _health(0.7),
        triage_outcome=_Triage(requires_attention_count=3),
    )
    assert "deferring identity-level inferences" in out


def test_low_health_still_recommends_principle_review():
    s = _service()
    out = s._propose_identity_revision(Identity(), [], _health(0.3))
    assert "low health score" in out
