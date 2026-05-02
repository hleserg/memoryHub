"""
Principle Revision Advisor.

This service helps distinguish between habits and principles,
and advises on when to revise principles based on experience.
"""

from atman.core.models.identity import Habit, Identity, MoralOrientation, Principle
from atman.core.models.reflection import PatternCandidate, PatternType


class PrincipleRevisionAdvisor:
    """
    Advisor for principle revision decisions.
    
    Key responsibilities:
    - Distinguish habits from principles
    - Detect when a principle is being questioned vs violated
    - Propose principle revisions based on patterns
    """

    def is_habit_not_principle(self, pattern: PatternCandidate) -> bool:
        """
        Determine if a pattern represents a habit rather than a principle.
        
        Habits describe what you DO.
        Principles describe what you BELIEVE is right.
        
        Args:
            pattern: Pattern to evaluate
            
        Returns:
            True if this is a habit, False if it's a principle
        """
        if pattern.pattern_type == PatternType.BEHAVIOR:
            if pattern.potential_habit and not pattern.potential_principle:
                return True
        
        keywords_habit = ["usually", "tend to", "often", "typically"]
        keywords_principle = ["should", "must", "believe", "value", "right", "wrong"]
        
        desc_lower = pattern.description.lower()
        
        has_habit_words = any(kw in desc_lower for kw in keywords_habit)
        has_principle_words = any(kw in desc_lower for kw in keywords_principle)
        
        if has_habit_words and not has_principle_words:
            return True
        
        return False

    def should_question_principle(
        self, principle: Principle, pattern: PatternCandidate
    ) -> bool:
        """
        Determine if a pattern should lead to questioning a principle.
        
        A principle should be questioned when:
        - It conflicts with observed behavior repeatedly
        - It leads to negative outcomes consistently
        - The agent experiences cognitive dissonance
        
        Args:
            principle: Principle to evaluate
            pattern: Pattern that might conflict with principle
            
        Returns:
            True if principle should be questioned
        """
        if not principle.chosen_consciously:
            return True
        
        if pattern.confidence > 0.7 and pattern.potential_principle:
            if pattern.potential_principle.lower() != principle.statement.lower():
                return True
        
        return False

    def suggest_principle_revision(
        self, identity: Identity, patterns: list[PatternCandidate]
    ) -> list[str]:
        """
        Suggest principle revisions based on detected patterns.
        
        Args:
            identity: Current identity
            patterns: Detected patterns
            
        Returns:
            List of revision suggestions
        """
        suggestions = []
        
        for pattern in patterns:
            if pattern.potential_principle and pattern.confidence > 0.6:
                existing_principle = self._find_similar_principle(
                    identity, pattern.potential_principle
                )
                
                if existing_principle:
                    if self.should_question_principle(existing_principle, pattern):
                        suggestions.append(
                            f"Question principle '{existing_principle.statement}' "
                            f"based on pattern: {pattern.description}"
                        )
                else:
                    suggestions.append(
                        f"Consider new principle: {pattern.potential_principle}"
                    )
        
        return suggestions

    def _find_similar_principle(
        self, identity: Identity, principle_statement: str
    ) -> Principle | None:
        """Find a similar principle in identity."""
        statement_lower = principle_statement.lower()
        
        for principle in identity.principles:
            if principle.statement.lower() == statement_lower:
                return principle
            
            overlap = self._word_overlap(
                principle.statement.lower().split(), statement_lower.split()
            )
            if overlap > 0.5:
                return principle
        
        return None

    def _word_overlap(self, words1: list[str], words2: list[str]) -> float:
        """Calculate word overlap between two lists."""
        if not words1 or not words2:
            return 0.0
        
        set1 = set(words1)
        set2 = set(words2)
        
        intersection = len(set1 & set2)
        union = len(set1 | set2)
        
        return intersection / union if union > 0 else 0.0
