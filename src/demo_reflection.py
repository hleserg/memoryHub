"""
Demo walkthrough for Reflection Engine (WP-04).

This demonstrates the three levels of reflection:
- Micro: After-session checkpoint
- Daily: Pattern detection across sessions
- Deep: Health assessment and identity revision

All outputs use Rich via atman.term for consistent styling.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from rich.table import Table

from atman.adapters.reflection.mock_reflection_model import MockReflectionModel
from atman.adapters.storage.in_memory_reflection_store import (
    InMemoryHealthAssessmentStore,
    InMemoryPatternStore,
    InMemoryReflectionEventStore,
)
from atman.core.models.experience import SessionExperience
from atman.core.models.identity import Identity
from atman.core.models.narrative import LayerType, NarrativeDocument, NarrativeLayer
from atman.core.services.principle_advisor import PrincipleRevisionAdvisor
from atman.core.services.reflection_service import (
    DailyReflectionService,
    DeepReflectionService,
    MicroReflectionService,
)
from atman.term import (
    console,
    demo_pace,
    print_banner,
    print_help_text,
    print_ok,
)


class MockExperienceRepo:
    """Mock experience repository for demo."""

    def __init__(self, experiences: list[SessionExperience]):
        """Initialize with experiences."""
        self.experiences = {exp.id: exp for exp in experiences}

    def get(self, experience_id: UUID) -> SessionExperience | None:
        """Get experience by ID."""
        return self.experiences.get(experience_id)

    def get_all(self) -> list[SessionExperience]:
        """Get all experiences."""
        return list(self.experiences.values())

    def get_by_session(self, session_id: UUID) -> list[SessionExperience]:
        """Get experiences by session."""
        return [exp for exp in self.experiences.values() if exp.session_id == session_id]

    def get_recent(self, limit: int = 10) -> list[SessionExperience]:
        """Get recent experiences."""
        sorted_exps = sorted(
            self.experiences.values(), key=lambda e: e.timestamp, reverse=True
        )
        return sorted_exps[:limit]

    def get_in_range(
        self, start: datetime, end: datetime
    ) -> list[SessionExperience]:
        """Get experiences in date range."""
        return [
            exp
            for exp in self.experiences.values()
            if start <= exp.timestamp <= end
        ]

    def update(self, experience: SessionExperience) -> None:
        """Update experience."""
        self.experiences[experience.id] = experience

    def add_reframing_note(self, experience_id: UUID, note) -> None:
        """Add reframing note."""
        exp = self.experiences.get(experience_id)
        if exp:
            exp.add_reframing_note(note)


class MockIdentityRepo:
    """Mock identity repository for demo."""

    def __init__(self, identity: Identity):
        """Initialize with identity."""
        self.identity = identity

    def get_current(self) -> Identity | None:
        """Get current identity."""
        return self.identity

    def get_snapshot(self, snapshot_id: UUID):
        """Get snapshot."""
        return None

    def get_history(self):
        """Get history."""
        return []

    def update(self, identity: Identity) -> None:
        """Update identity."""
        self.identity = identity

    def create_snapshot(self, identity: Identity, description: str, change_summary: str):
        """Create snapshot."""
        pass


class MockNarrativeRepo:
    """Mock narrative repository for demo."""

    def __init__(self, narrative: NarrativeDocument):
        """Initialize with narrative."""
        self.narrative = narrative

    def get_current(self) -> NarrativeDocument | None:
        """Get current narrative."""
        return self.narrative

    def update(self, narrative: NarrativeDocument) -> None:
        """Update narrative."""
        self.narrative = narrative

    def get_history(self):
        """Get history."""
        return []


def load_fixtures() -> tuple[list[SessionExperience], Identity]:
    """Load test fixtures."""
    fixtures_path = Path("fixtures/reflection")
    
    with open(fixtures_path / "experiences.json") as f:
        exp_data = json.load(f)
        experiences = [SessionExperience(**exp) for exp in exp_data]
    
    with open(fixtures_path / "identity.json") as f:
        identity_data = json.load(f)
        identity = Identity(**identity_data)
    
    return experiences, identity


def demo_micro_reflection(
    experiences: list[SessionExperience],
    identity: Identity,
) -> None:
    """Demonstrate micro reflection."""
    print_banner("1. MICRO REFLECTION", width=70)
    print_help_text(
        "Micro reflection runs after each session to update the recent narrative layer."
    )
    demo_pace()
    
    narrative = NarrativeDocument(
        identity_id=identity.id,
        core_layer=NarrativeLayer(
            layer_type=LayerType.CORE,
            content="I am in early stages of self-discovery.",
        ),
        recent_layer=NarrativeLayer(
            layer_type=LayerType.RECENT,
            content="Starting to explore reflection.",
        ),
    )
    
    exp_repo = MockExperienceRepo(experiences)
    narrative_repo = MockNarrativeRepo(narrative)
    reflection_model = MockReflectionModel()
    event_store = InMemoryReflectionEventStore()
    
    service = MicroReflectionService(
        experience_repo=exp_repo,
        narrative_repo=narrative_repo,
        reflection_model=reflection_model,
        event_store=event_store,
    )
    
    session_id = experiences[0].session_id
    print_ok(f"Running micro reflection for session: {session_id}")
    demo_pace()
    
    event = service.reflect(session_id)
    
    print_ok("\nMicro Reflection Complete!")
    demo_pace()
    
    table = Table(title="Reflection Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    
    table.add_row("Level", str(event.reflection_level))
    table.add_row("Experiences Analyzed", str(len(event.experiences_analyzed)))
    table.add_row("Key Insight", event.key_insight)
    
    console.print(table)
    demo_pace()
    
    print_ok("\nUpdated Recent Layer:")
    console.print(f"  {narrative_repo.narrative.recent_layer.content}")
    demo_pace()


def demo_daily_reflection(
    experiences: list[SessionExperience],
    identity: Identity,
) -> None:
    """Demonstrate daily reflection."""
    print_banner("2. DAILY REFLECTION", width=70)
    print_help_text(
        "Daily reflection analyzes experiences across the day to detect patterns."
    )
    demo_pace()
    
    exp_repo = MockExperienceRepo(experiences)
    identity_repo = MockIdentityRepo(identity)
    pattern_store = InMemoryPatternStore()
    reflection_model = MockReflectionModel()
    event_store = InMemoryReflectionEventStore()
    
    service = DailyReflectionService(
        experience_repo=exp_repo,
        identity_repo=identity_repo,
        pattern_store=pattern_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )
    
    date = datetime.now(UTC)
    print_ok(f"Running daily reflection for: {date.strftime('%Y-%m-%d')}")
    demo_pace()
    
    event = service.reflect(date)
    
    print_ok("\nDaily Reflection Complete!")
    demo_pace()
    
    table = Table(title="Reflection Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    
    table.add_row("Level", str(event.reflection_level))
    table.add_row("Experiences Analyzed", str(len(event.experiences_analyzed)))
    table.add_row("Patterns Detected", str(len(event.patterns_detected)))
    table.add_row("Reframing Notes Added", str(event.reframing_notes_added))
    table.add_row("Key Insight", event.key_insight)
    
    console.print(table)
    demo_pace()
    
    if event.patterns_detected:
        print_ok("\nDetected Patterns:")
        for pattern_id in event.patterns_detected:
            pattern = pattern_store.get(pattern_id)
            if pattern:
                console.print(f"  • {pattern.description}")
        demo_pace()


def demo_deep_reflection(
    experiences: list[SessionExperience],
    identity: Identity,
) -> None:
    """Demonstrate deep reflection."""
    print_banner("3. DEEP REFLECTION", width=70)
    print_help_text(
        "Deep reflection performs health assessment and proposes identity/narrative revisions."
    )
    demo_pace()
    
    narrative = NarrativeDocument(
        identity_id=identity.id,
        core_layer=NarrativeLayer(
            layer_type=LayerType.CORE,
            content="I am in early stages of self-discovery.",
        ),
        recent_layer=NarrativeLayer(
            layer_type=LayerType.RECENT,
            content="Been exploring different approaches.",
        ),
    )
    
    exp_repo = MockExperienceRepo(experiences)
    identity_repo = MockIdentityRepo(identity)
    narrative_repo = MockNarrativeRepo(narrative)
    pattern_store = InMemoryPatternStore()
    health_store = InMemoryHealthAssessmentStore()
    reflection_model = MockReflectionModel()
    event_store = InMemoryReflectionEventStore()
    
    service = DeepReflectionService(
        experience_repo=exp_repo,
        identity_repo=identity_repo,
        narrative_repo=narrative_repo,
        pattern_store=pattern_store,
        health_store=health_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )
    
    since = datetime(2026, 4, 30, tzinfo=UTC)
    until = datetime(2026, 5, 1, 23, 59, 59, tzinfo=UTC)
    
    print_ok(
        f"Running deep reflection from {since.strftime('%Y-%m-%d')} to {until.strftime('%Y-%m-%d')}"
    )
    demo_pace()
    
    event = service.reflect(since, until)
    
    print_ok("\nDeep Reflection Complete!")
    demo_pace()
    
    table = Table(title="Reflection Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    
    table.add_row("Level", str(event.reflection_level))
    table.add_row("Experiences Analyzed", str(len(event.experiences_analyzed)))
    table.add_row("Patterns Detected", str(len(event.patterns_detected)))
    table.add_row("Reframing Notes Added", str(event.reframing_notes_added))
    
    if event.health_assessment_id:
        assessment = health_store.get(event.health_assessment_id)
        if assessment:
            table.add_row("Health Score", f"{assessment.overall_score:.2f}/1.0")
    
    table.add_row("Key Insight", event.key_insight)
    
    console.print(table)
    demo_pace()
    
    if event.health_assessment_id:
        assessment = health_store.get(event.health_assessment_id)
        if assessment:
            print_ok("\nHealth Assessment (6 Yakhoda Criteria):")
            
            health_table = Table()
            health_table.add_column("Criterion", style="cyan")
            health_table.add_column("Score", style="green")
            
            for criterion, crit_assessment in assessment.criteria.items():
                health_table.add_row(
                    criterion.value.replace("_", " ").title(),
                    f"{crit_assessment.score:.2f}",
                )
            
            console.print(health_table)
            demo_pace()


def demo_principle_advisor(identity: Identity) -> None:
    """Demonstrate principle revision advisor."""
    print_banner("4. PRINCIPLE REVISION ADVISOR", width=70)
    print_help_text(
        "The advisor helps distinguish habits from principles and suggests revisions."
    )
    demo_pace()
    
    from atman.core.models.reflection import (
        PatternCandidate,
        PatternType,
        ReflectionLevel,
    )
    
    pattern = PatternCandidate(
        pattern_type=PatternType.BEHAVIOR,
        description="I usually over-explain when uncertain",
        detected_by=ReflectionLevel.DAILY,
        confidence=0.7,
        potential_habit="Over-explaining as uncertainty response",
        potential_principle="",
    )
    
    advisor = PrincipleRevisionAdvisor()
    
    print_ok("Analyzing pattern: " + pattern.description)
    demo_pace()
    
    is_habit = advisor.is_habit_not_principle(pattern)
    print_ok(f"\nIs this a habit (not a principle)? {is_habit}")
    demo_pace()
    
    if is_habit:
        console.print("  → This describes what I DO, not what I BELIEVE is right.")
    
    demo_pace()
    
    suggestions = advisor.suggest_principle_revision(identity, [pattern])
    
    if suggestions:
        print_ok("\nPrinciple Revision Suggestions:")
        for suggestion in suggestions:
            console.print(f"  • {suggestion}")
        demo_pace()


def main() -> None:
    """Run the reflection engine demo."""
    print_banner("REFLECTION ENGINE DEMO", width=70, style="bold magenta")
    print_help_text(
        "This demo showcases WP-04: Reflection Engine with three levels of reflection."
    )
    demo_pace()
    
    print_ok("Loading fixtures...")
    demo_pace()
    
    experiences, identity = load_fixtures()
    
    print_ok(f"Loaded {len(experiences)} experiences and 1 identity")
    demo_pace()
    
    demo_micro_reflection(experiences, identity)
    demo_daily_reflection(experiences, identity)
    demo_deep_reflection(experiences, identity)
    demo_principle_advisor(identity)
    
    print_banner("DEMO COMPLETE", width=70, style="bold green")
    print_ok(
        "The Reflection Engine demonstrates three levels of reflection:\n"
        "  • Micro: Session checkpoint\n"
        "  • Daily: Pattern detection\n"
        "  • Deep: Health assessment and identity revision"
    )
    demo_pace()


if __name__ == "__main__":
    main()
