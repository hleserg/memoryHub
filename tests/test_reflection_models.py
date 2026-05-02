"""
Tests for reflection models.
"""

from uuid import uuid4

import pytest

from atman.core.models.reflection import (
    CriterionAssessment,
    HealthAssessment,
    JahodaCriterion,
    PatternCandidate,
    PatternStatus,
    PatternType,
    ReflectionEvent,
    ReflectionLevel,
)


def test_pattern_candidate_creation() -> None:
    """Test creating a pattern candidate."""
    pattern = PatternCandidate(
        pattern_type=PatternType.BEHAVIOR,
        description="I tend to over-explain when uncertain",
        detected_by=ReflectionLevel.DAILY,
        confidence=0.7,
    )

    assert pattern.pattern_type == PatternType.BEHAVIOR
    assert pattern.status == PatternStatus.CANDIDATE
    assert pattern.confidence == 0.7
    assert pattern.detected_by == ReflectionLevel.DAILY


def test_pattern_candidate_validation() -> None:
    """Test pattern candidate validation."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        PatternCandidate(
            pattern_type=PatternType.BEHAVIOR,
            description="",
            detected_by=ReflectionLevel.DAILY,
        )

    with pytest.raises(ValidationError):
        PatternCandidate(
            pattern_type=PatternType.BEHAVIOR,
            description="Some pattern",
            detected_by=ReflectionLevel.DAILY,
            confidence=1.5,
        )


def test_criterion_assessment_creation() -> None:
    """Test creating a criterion assessment."""
    assessment = CriterionAssessment(
        criterion=JahodaCriterion.POSITIVE_SELF_ATTITUDE,
        score=0.7,
        evidence=["Shows self-awareness", "Honest about limitations"],
        concerns=["Limited experience base"],
    )

    assert assessment.criterion == JahodaCriterion.POSITIVE_SELF_ATTITUDE
    assert assessment.score == 0.7
    assert len(assessment.evidence) == 2
    assert len(assessment.concerns) == 1


def test_criterion_assessment_score_validation() -> None:
    """Test criterion assessment score validation."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        CriterionAssessment(
            criterion=JahodaCriterion.AUTONOMY,
            score=1.5,
            evidence=[],
            concerns=[],
        )


def test_health_assessment_all_criteria_required() -> None:
    """Test that health assessment requires all 6 criteria."""
    criteria = {
        JahodaCriterion.POSITIVE_SELF_ATTITUDE: CriterionAssessment(
            criterion=JahodaCriterion.POSITIVE_SELF_ATTITUDE,
            score=0.6,
            evidence=["Test"],
            concerns=[],
        ),
    }

    with pytest.raises(ValueError, match="All 6 Jahoda criteria must be assessed"):
        HealthAssessment(
            criteria=criteria,
            overall_score=0.6,
        )


def test_health_assessment_complete() -> None:
    """Test creating a complete health assessment."""
    criteria = {}
    for criterion in JahodaCriterion:
        criteria[criterion] = CriterionAssessment(
            criterion=criterion,
            score=0.6,
            evidence=["Test evidence"],
            concerns=["Test concern"],
        )

    assessment = HealthAssessment(
        criteria=criteria,
        overall_score=0.6,
        summary="Test assessment",
    )

    assert len(assessment.criteria) == 6
    assert assessment.overall_score == 0.6
    assert assessment.summary == "Test assessment"


def test_health_assessment_overall_must_match_criteria_mean() -> None:
    """overall_score cannot drift from the six criterion scores (ingest / adapter guard)."""
    from pydantic import ValidationError

    criteria = {}
    for criterion in JahodaCriterion:
        criteria[criterion] = CriterionAssessment(
            criterion=criterion,
            score=0.5,
            evidence=["e"],
            concerns=["c"],
        )

    with pytest.raises(ValidationError) as exc_info:
        HealthAssessment(criteria=criteria, overall_score=0.99, summary="bad")
    assert "mean" in str(exc_info.value).lower()


def test_reflection_event_creation() -> None:
    """Test creating a reflection event."""
    event = ReflectionEvent(
        reflection_level=ReflectionLevel.MICRO,
        experiences_analyzed=[uuid4(), uuid4()],
        key_insight="Test insight",
    )

    assert event.reflection_level == ReflectionLevel.MICRO
    assert len(event.experiences_analyzed) == 2
    assert event.key_insight == "Test insight"
    assert event.reframing_notes_added == 0


def test_reflection_event_with_patterns() -> None:
    """Test reflection event with detected patterns."""
    pattern_ids = [uuid4(), uuid4()]

    event = ReflectionEvent(
        reflection_level=ReflectionLevel.DAILY,
        experiences_analyzed=[uuid4()],
        patterns_detected=pattern_ids,
        reframing_notes_added=2,
        key_insight="Detected patterns",
    )

    assert event.reflection_level == ReflectionLevel.DAILY
    assert len(event.patterns_detected) == 2
    assert event.reframing_notes_added == 2


def test_reflection_event_validation() -> None:
    """Test reflection event validation."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ReflectionEvent(
            reflection_level=ReflectionLevel.MICRO,
            reframing_notes_added=-1,
        )
