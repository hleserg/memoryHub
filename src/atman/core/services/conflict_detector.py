"""
ConflictDetector - cognitive tension from contradictory facts.

Detects when two active facts contradict each other and produces
a cognitive tension signal (small, not overwhelming).
"""

import re
from dataclasses import dataclass
from uuid import UUID

from atman.core.models.fact import FactRecord, FactStatus
from atman.core.ports import FactualMemory


@dataclass
class FactConflict:
    """A detected conflict between two facts."""

    fact1_id: UUID
    fact2_id: UUID
    fact1_content: str
    fact2_content: str
    conflict_type: str  # "contradiction", "inconsistency", "update_needed"
    confidence: float  # 0.0-1.0, how sure we are this is a conflict
    description: str  # Human-readable description of the conflict


class ConflictDetector:
    """
    Detects contradictions between active facts.

    Produces small cognitive tension signals when contradictory
    facts are both active - similar to human cognitive dissonance.

    This is intentionally lightweight - not an exhaustive
    reasoning system, but a simple signal generator.
    """

    # Simple contradiction patterns (can be expanded)
    NEGATION_PATTERNS = [
        r"\bnot\b",
        r"\bno longer\b",
        r"\bnever\b",
        r"\bcancelled\b",
        r"\bremoved\b",
        r"\bdeprecated\b",
    ]

    def __init__(
        self,
        factual_memory: FactualMemory,
        similarity_threshold: float = 0.7,
    ) -> None:
        """
        Initialize conflict detector.

        Args:
            factual_memory: Storage for facts
            similarity_threshold: Minimum content similarity to check
        """
        self.factual_memory = factual_memory
        self.similarity_threshold = similarity_threshold

    def check_fact(self, fact: FactRecord) -> list[FactConflict]:
        """
        Check a new fact against existing facts for conflicts.

        Args:
            fact: The fact to check

        Returns:
            list[FactConflict]: Detected conflicts
        """
        if fact.status == FactStatus.INVALIDATED:
            return []

        conflicts: list[FactConflict] = []

        # Get candidate facts with similar tags or content
        candidates = self.factual_memory.search(
            query=fact.content[:50],  # First 50 chars as query
            tags=fact.tags[:2] if fact.tags else None,
            limit=20,
            include_invalidated=False,
        )

        for candidate in candidates:
            if candidate.id == fact.id:
                continue
            if candidate.status == FactStatus.INVALIDATED:
                continue

            conflict = self._detect_conflict(fact, candidate)
            if conflict:
                conflicts.append(conflict)

        return conflicts

    def scan_all_conflicts(self, limit: int = 100) -> list[FactConflict]:
        """
        Scan all active facts for conflicts.

        Args:
            limit: Maximum facts to check

        Returns:
            list[FactConflict]: All detected conflicts
        """
        # Get recent active facts
        recent_facts = self.factual_memory.list_recent(limit=limit)
        active_facts = [f for f in recent_facts if f.status == FactStatus.ACTIVE]

        conflicts: list[FactConflict] = []
        checked: set[tuple[UUID, UUID]] = set()

        for i, fact1 in enumerate(active_facts):
            for fact2 in active_facts[i + 1 :]:
                # Avoid duplicate checks (order doesn't matter)
                pair = tuple(sorted([fact1.id, fact2.id]))  # type: ignore
                if pair in checked:
                    continue
                checked.add(pair)

                conflict = self._detect_conflict(fact1, fact2)
                if conflict:
                    conflicts.append(conflict)

        return conflicts

    def _detect_conflict(
        self, fact1: FactRecord, fact2: FactRecord
    ) -> FactConflict | None:
        """
        Detect if two facts contradict each other.

        Simple heuristics:
        1. Same subject, opposite polarity (one has negation)
        2. Similar content but different values
        3. Same tags, overlapping timeframe, different conclusions
        """
        # Check content similarity first
        content_sim = self._content_similarity(fact1.content, fact2.content)
        if content_sim < 0.3:
            return None

        # Check for negation patterns
        fact1_has_neg = any(
            re.search(p, fact1.content, re.IGNORECASE) for p in self.NEGATION_PATTERNS
        )
        fact2_has_neg = any(
            re.search(p, fact2.content, re.IGNORECASE) for p in self.NEGATION_PATTERNS
        )

        # If one has negation and other doesn't, potential contradiction
        if fact1_has_neg != fact2_has_neg and content_sim > 0.5:
            neg_fact = fact1 if fact1_has_neg else fact2
            pos_fact = fact2 if fact1_has_neg else fact1

            return FactConflict(
                fact1_id=fact1.id,
                fact2_id=fact2.id,
                fact1_content=fact1.content,
                fact2_content=fact2.content,
                conflict_type="contradiction",
                confidence=min(0.9, content_sim),
                description=f"Potential contradiction: '{pos_fact.content[:50]}...' vs negated '{neg_fact.content[:50]}...'",
            )

        # Check for value differences in similar contexts
        if content_sim > 0.6 and fact1.tags and fact2.tags:
            shared_tags = set(fact1.tags) & set(fact2.tags)
            if shared_tags:
                return FactConflict(
                    fact1_id=fact1.id,
                    fact2_id=fact2.id,
                    fact1_content=fact1.content,
                    fact2_content=fact2.content,
                    conflict_type="inconsistency",
                    confidence=content_sim * 0.7,
                    description=f"Inconsistent facts on {shared_tags}",
                )

        return None

    def _content_similarity(self, text1: str, text2: str) -> float:
        """
        Calculate simple word overlap similarity.

        Returns 0.0-1.0 where 1.0 is identical.
        """
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())

        if not words1 or not words2:
            return 0.0

        intersection = words1 & words2
        union = words1 | words2

        return len(intersection) / len(union)

    def get_cognitive_tension(self, conflicts: list[FactConflict]) -> float:
        """
        Calculate overall cognitive tension from conflicts.

        Small value (0.0-1.0) representing mental discomfort
        from contradictory information.

        Args:
            conflicts: List of detected conflicts

        Returns:
            float: Cognitive tension level (0.0 = none, 1.0 = high)
        """
        if not conflicts:
            return 0.0

        # Sum confidence scores, cap at 1.0
        # Use diminishing returns for multiple conflicts
        total = sum(c.confidence for c in conflicts)
        return min(1.0, total / (1 + total * 0.5))
