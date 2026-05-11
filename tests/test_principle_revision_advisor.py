"""Tests for PrincipleRevisionAdvisor (principle vs habit, revision suggestions)."""

from __future__ import annotations

from uuid import uuid4

from atman.core.models.identity import Identity, Principle
from atman.core.models.reflection import (
    PatternCandidate,
    PatternType,
    ReflectionLevel,
)
from atman.core.services.principle_advisor import PrincipleRevisionAdvisor


def _pattern(
    *,
    description: str,
    confidence: float,
    potential_principle: str,
    potential_habit: str = "",
    pattern_type: PatternType = PatternType.BEHAVIOR,
) -> PatternCandidate:
    return PatternCandidate(
        pattern_type=pattern_type,
        description=description,
        detected_by=ReflectionLevel.MICRO,
        confidence=confidence,
        potential_principle=potential_principle,
        potential_habit=potential_habit,
    )


def test_suggest_new_principle_when_none_similar() -> None:
    adv = PrincipleRevisionAdvisor()
    ident = Identity(
        id=uuid4(),
        self_description="x",
        core_values=[],
        goals=[],
        emotional_baseline=0.0,
        principles=[],
    )
    p = _pattern(
        description="observed tension",
        confidence=0.9,
        potential_principle="Always verify before shipping",
    )
    out = adv.suggest_principle_revision(ident, [p])
    assert any("Consider new principle" in s for s in out)


def test_suggest_question_existing_principle() -> None:
    adv = PrincipleRevisionAdvisor()
    ident = Identity(
        id=uuid4(),
        self_description="x",
        core_values=[],
        goals=[],
        emotional_baseline=0.0,
        principles=[Principle(statement="one two three four", chosen_consciously=True)],
    )
    p = _pattern(
        description="repeated tension between habits",
        confidence=0.95,
        potential_principle="one two three five",
    )
    out = adv.suggest_principle_revision(ident, [p])
    assert any("Question principle" in s for s in out)


def test_find_similar_principle_by_word_overlap() -> None:
    adv = PrincipleRevisionAdvisor()
    ident = Identity(
        id=uuid4(),
        self_description="x",
        core_values=[],
        goals=[],
        emotional_baseline=0.0,
        principles=[Principle(statement="be kind to users always")],
    )
    p = _pattern(
        description="pattern",
        confidence=0.9,
        potential_principle="always be kind to people",
    )
    out = adv.suggest_principle_revision(ident, [p])
    assert any("Question principle" in s for s in out)


def test_word_overlap_empty_branch() -> None:
    adv = PrincipleRevisionAdvisor()
    assert adv._word_overlap([], ["a"]) == 0.0
    assert adv._word_overlap(["a"], []) == 0.0
