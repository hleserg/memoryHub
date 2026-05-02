"""
In-memory implementations of reflection storage ports.

These are simple implementations for testing and prototyping.
Production implementations would use persistent storage (JSONL, SQLite, etc.).
"""

from datetime import datetime
from uuid import UUID

from atman.core.models.reflection import (
    HealthAssessment,
    PatternCandidate,
    ReflectionEvent,
    ReflectionLevel,
)
from atman.core.ports.reflection import (
    HealthAssessmentStore,
    PatternStore,
    ReflectionEventStore,
)


class InMemoryPatternStore(PatternStore):
    """
    In-memory storage for pattern candidates.
    
    Patterns are stored in a simple list with no persistence.
    """

    def __init__(self) -> None:
        """Initialize empty pattern store."""
        self._patterns: dict[UUID, PatternCandidate] = {}

    def save(self, pattern: PatternCandidate) -> None:
        """Save a pattern candidate."""
        self._patterns[pattern.id] = pattern

    def get(self, pattern_id: UUID) -> PatternCandidate | None:
        """Get a pattern by ID."""
        return self._patterns.get(pattern_id)

    def get_all(self) -> list[PatternCandidate]:
        """Get all patterns."""
        return list(self._patterns.values())

    def get_by_level(self, level: ReflectionLevel) -> list[PatternCandidate]:
        """Get patterns detected at a specific reflection level."""
        return [p for p in self._patterns.values() if p.detected_by == level]

    def update(self, pattern: PatternCandidate) -> None:
        """Update a pattern (e.g., change status to confirmed)."""
        if pattern.id not in self._patterns:
            raise ValueError(f"Pattern {pattern.id} not found")
        self._patterns[pattern.id] = pattern


class InMemoryReflectionEventStore(ReflectionEventStore):
    """
    In-memory storage for reflection events.
    
    Events are stored in a simple list with no persistence.
    """

    def __init__(self) -> None:
        """Initialize empty event store."""
        self._events: dict[UUID, ReflectionEvent] = {}

    def save(self, event: ReflectionEvent) -> None:
        """Save a reflection event."""
        self._events[event.id] = event

    def get(self, event_id: UUID) -> ReflectionEvent | None:
        """Get a reflection event by ID."""
        return self._events.get(event_id)

    def get_all(self) -> list[ReflectionEvent]:
        """Get all reflection events."""
        return list(self._events.values())

    def get_by_level(self, level: ReflectionLevel) -> list[ReflectionEvent]:
        """Get reflection events at a specific level."""
        return [e for e in self._events.values() if e.reflection_level == level]

    def get_recent(self, limit: int = 10) -> list[ReflectionEvent]:
        """Get most recent reflection events."""
        events = sorted(
            self._events.values(), key=lambda e: e.timestamp, reverse=True
        )
        return events[:limit]


class InMemoryHealthAssessmentStore(HealthAssessmentStore):
    """
    In-memory storage for health assessments.
    
    Assessments are stored in a simple list with no persistence.
    """

    def __init__(self) -> None:
        """Initialize empty assessment store."""
        self._assessments: dict[UUID, HealthAssessment] = {}

    def save(self, assessment: HealthAssessment) -> None:
        """Save a health assessment."""
        self._assessments[assessment.id] = assessment

    def get(self, assessment_id: UUID) -> HealthAssessment | None:
        """Get a health assessment by ID."""
        return self._assessments.get(assessment_id)

    def get_all(self) -> list[HealthAssessment]:
        """Get all health assessments."""
        return list(self._assessments.values())

    def get_latest(self) -> HealthAssessment | None:
        """Get the most recent health assessment."""
        if not self._assessments:
            return None
        
        assessments = sorted(
            self._assessments.values(), key=lambda a: a.timestamp, reverse=True
        )
        return assessments[0]
