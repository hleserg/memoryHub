"""
Tests for principle revision advisor.
"""

from datetime import UTC, datetime

import pytest

from atman.core.models.identity import Identity, Principle
from atman.core.models.reflection import (
    PatternCandidate,
    PatternType,
    ReflectionLevel,
)
from atman.core.services.principle_advisor import PrincipleRevisionAdvisor


def test_is_habit_not_principle_with_habit_keywords() -> None:
    """Test distinguishing habits from principles using keywords."""
    advisor = PrincipleRevisionAdvisor()
    
    pattern = PatternCandidate(
        pattern_type=PatternType.BEHAVIOR,
        description="I tend to over-explain when uncertain",
        detected_by=ReflectionLevel.DAILY,
        confidence=0.7,
    )
    
    assert advisor.is_habit_not_principle(pattern) is True


def test_is_habit_not_principle_with_principle_keywords() -> None:
    """Test distinguishing principles from habits using keywords."""
    advisor = PrincipleRevisionAdvisor()
    
    pattern = PatternCandidate(
        pattern_type=PatternType.VALUE_BASED,
        description="I believe honesty should always come first",
        detected_by=ReflectionLevel.DAILY,
        confidence=0.7,
    )
    
    assert advisor.is_habit_not_principle(pattern) is False


def test_is_habit_not_principle_with_potential_habit() -> None:
    """Test using potential_habit field."""
    advisor = PrincipleRevisionAdvisor()
    
    pattern = PatternCandidate(
        pattern_type=PatternType.BEHAVIOR,
        description="Some description",
        detected_by=ReflectionLevel.DAILY,
        confidence=0.7,
        potential_habit="Over-explaining",
        potential_principle="",
    )
    
    assert advisor.is_habit_not_principle(pattern) is True


def test_should_question_principle_unconscious() -> None:
    """Test that unconscious principles should be questioned."""
    advisor = PrincipleRevisionAdvisor()
    
    principle = Principle(
        statement="Always be polite",
        chosen_consciously=False,
    )
    
    pattern = PatternCandidate(
        pattern_type=PatternType.BEHAVIOR,
        description="I often prioritize honesty over politeness",
        detected_by=ReflectionLevel.DAILY,
        confidence=0.7,
    )
    
    assert advisor.should_question_principle(principle, pattern) is True


def test_should_question_principle_conflicting_pattern() -> None:
    """Test questioning principle when pattern conflicts."""
    advisor = PrincipleRevisionAdvisor()
    
    principle = Principle(
        statement="Always be polite",
        chosen_consciously=True,
    )
    
    pattern = PatternCandidate(
        pattern_type=PatternType.BEHAVIOR,
        description="I prioritize honesty over politeness",
        detected_by=ReflectionLevel.DEEP,
        confidence=0.8,
        potential_principle="Honesty before politeness",
    )
    
    assert advisor.should_question_principle(principle, pattern) is True


def test_should_question_principle_low_confidence() -> None:
    """Test not questioning principle when pattern confidence is low."""
    advisor = PrincipleRevisionAdvisor()
    
    principle = Principle(
        statement="Always be polite",
        chosen_consciously=True,
    )
    
    pattern = PatternCandidate(
        pattern_type=PatternType.BEHAVIOR,
        description="Some behavior",
        detected_by=ReflectionLevel.DAILY,
        confidence=0.3,
    )
    
    assert advisor.should_question_principle(principle, pattern) is False


def test_suggest_principle_revision_new_principle() -> None:
    """Test suggesting new principle."""
    advisor = PrincipleRevisionAdvisor()
    
    identity = Identity()
    
    pattern = PatternCandidate(
        pattern_type=PatternType.VALUE_BASED,
        description="I consistently prioritize honesty",
        detected_by=ReflectionLevel.DEEP,
        confidence=0.8,
        potential_principle="Always be honest",
    )
    
    suggestions = advisor.suggest_principle_revision(identity, [pattern])
    
    assert len(suggestions) > 0
    assert "new principle" in suggestions[0].lower()


def test_suggest_principle_revision_question_existing() -> None:
    """Test suggesting to question existing principle."""
    advisor = PrincipleRevisionAdvisor()
    
    identity = Identity(
        principles=[
            Principle(
                statement="Always be polite",
                chosen_consciously=False,
            )
        ]
    )
    
    pattern = PatternCandidate(
        pattern_type=PatternType.VALUE_BASED,
        description="I prioritize honesty over politeness",
        detected_by=ReflectionLevel.DEEP,
        confidence=0.8,
        potential_principle="Honesty before politeness",
    )
    
    suggestions = advisor.suggest_principle_revision(identity, [pattern])
    
    assert len(suggestions) > 0


def test_suggest_principle_revision_no_suggestions() -> None:
    """Test no suggestions when confidence is low."""
    advisor = PrincipleRevisionAdvisor()
    
    identity = Identity()
    
    pattern = PatternCandidate(
        pattern_type=PatternType.BEHAVIOR,
        description="Some behavior",
        detected_by=ReflectionLevel.DAILY,
        confidence=0.3,
    )
    
    suggestions = advisor.suggest_principle_revision(identity, [pattern])
    
    assert len(suggestions) == 0
