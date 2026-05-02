"""
CLI for Reflection Engine.

Commands:
- atman reflect micro --fixtures
- atman reflect daily --fixtures
- atman reflect deep --fixtures

Note: Non-fixtures modes require integration with FileStateStore,
which is not yet implemented. Use demo_reflection.py for full walkthrough.
"""

import sys
from datetime import UTC, datetime
from uuid import UUID

from atman.adapters.reflection.fixture_loader import (
    anchor_session_experiences_to_utc_day_window,
    load_reflection_identity,
    load_reflection_session_experiences,
)
from atman.adapters.reflection.mock_reflection_model import MockReflectionModel
from atman.adapters.storage.in_memory_reflection_store import (
    InMemoryHealthAssessmentStore,
    InMemoryPatternStore,
    InMemoryReflectionEventStore,
)
from atman.core.exceptions import NarrativePersistenceConflictError
from atman.core.models.experience import ReframingNote, SessionExperience
from atman.core.models.identity import Identity, IdentitySnapshot
from atman.core.models.narrative import LayerType, NarrativeDocument, NarrativeLayer
from atman.core.services.reflection_service import (
    DailyReflectionService,
    DeepReflectionService,
    MicroReflectionService,
)
from atman.term import (
    demo_pace,
    print_banner,
    print_err,
    print_help_text,
    print_info,
    print_ok,
)


class MockExperienceRepo:
    """Mock experience repository."""

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
        sorted_exps = sorted(self.experiences.values(), key=lambda e: e.timestamp, reverse=True)
        return sorted_exps[:limit]

    def get_in_range(self, start: datetime, end: datetime) -> list[SessionExperience]:
        """Get experiences in date range."""
        return [exp for exp in self.experiences.values() if start <= exp.timestamp <= end]

    def update(self, experience: SessionExperience) -> None:
        """Update experience."""
        self.experiences[experience.id] = experience

    def add_reframing_note(self, experience_id: UUID, note: ReframingNote) -> bool:
        """Add reframing note; return True if the experience existed."""
        exp = self.experiences.get(experience_id)
        if exp is None:
            return False
        exp.add_reframing_note(note)
        return True


class MockIdentityRepo:
    """Mock identity repository."""

    def __init__(self, identity: Identity):
        """Initialize with identity."""
        self.identity = identity

    def get_current(self) -> Identity | None:
        """Get current identity."""
        return self.identity

    def get_snapshot(self, snapshot_id: UUID) -> IdentitySnapshot | None:
        """Get snapshot."""
        return None

    def get_history(self) -> list[IdentitySnapshot]:
        """Get history."""
        return []

    def update(self, identity: Identity) -> None:
        """Update identity."""
        self.identity = identity

    def create_snapshot(
        self, identity: Identity, description: str, change_summary: str
    ) -> IdentitySnapshot:
        """Create snapshot."""
        return IdentitySnapshot(
            identity_id=identity.id,
            identity_snapshot=identity,
            description=description,
            change_summary=change_summary,
        )


class MockNarrativeRepo:
    """Mock narrative repository."""

    def __init__(self, narrative: NarrativeDocument):
        """Initialize with narrative."""
        self.narrative = narrative

    def get_current(self) -> NarrativeDocument | None:
        """Get current narrative."""
        if self.narrative is None:
            return None
        return self.narrative.model_copy(deep=True)

    def update(
        self, narrative: NarrativeDocument, *, expected_updated_at: datetime | None = None
    ) -> None:
        """Update narrative with optional optimistic concurrency on ``updated_at``."""
        if self.narrative is None:
            self.narrative = narrative.model_copy(deep=True)
            return
        if expected_updated_at is not None and self.narrative.updated_at != expected_updated_at:
            raise NarrativePersistenceConflictError(
                "Narrative was modified concurrently since this snapshot was read."
            )
        self.narrative = narrative.model_copy(deep=True)

    def get_history(self) -> list[NarrativeDocument]:
        """Get history."""
        return []


def setup_fixtures() -> tuple[MockExperienceRepo, MockIdentityRepo, MockNarrativeRepo]:
    """
    Set up test fixtures for reflection CLI.

    Loads `fixtures/reflection/experiences.json` and `identity.json`, anchors
    experience timestamps into the current UTC day (so deep/daily in-range
    queries match), and builds a minimal narrative for the loaded identity.

    Returns:
        Tuple of (experience_repo, identity_repo, narrative_repo)
    """
    experiences = anchor_session_experiences_to_utc_day_window(
        load_reflection_session_experiences()
    )
    identity = load_reflection_identity()

    narrative = NarrativeDocument(
        identity_id=identity.id,
        core_layer=NarrativeLayer(
            layer_type=LayerType.CORE,
            content="I am in early stages of self-discovery. I don't have much experience yet.",
        ),
        recent_layer=NarrativeLayer(
            layer_type=LayerType.RECENT,
            content="Just starting to explore reflection.",
        ),
    )

    experience_repo = MockExperienceRepo(experiences)
    identity_repo = MockIdentityRepo(identity)
    narrative_repo = MockNarrativeRepo(narrative)

    return experience_repo, identity_repo, narrative_repo


def cmd_reflect_micro(args: list[str]) -> int:
    """Run micro reflection."""
    print_banner("Micro Reflection")

    if "--fixtures" not in args:
        print_err("Only --fixtures mode is supported for now")
        print_help_text("Usage: atman reflect micro --fixtures")
        return 1

    print_ok("Using test fixtures...")
    demo_pace()

    experience_repo, _identity_repo, narrative_repo = setup_fixtures()

    experiences = experience_repo.get_all()
    if not experiences:
        print_err("No experiences in fixtures")
        return 1

    session_id = experiences[0].session_id

    print_ok(f"Reflecting on session: {session_id}")
    demo_pace()

    reflection_model = MockReflectionModel()
    event_store = InMemoryReflectionEventStore()

    service = MicroReflectionService(
        experience_repo=experience_repo,
        narrative_repo=narrative_repo,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    event = service.reflect(session_id)

    print_ok("\nReflection Complete!")
    demo_pace()
    print_info(f"  Level: {event.reflection_level}")
    print_info(f"  Experiences analyzed: {len(event.experiences_analyzed)}")
    print_info(f"  Key insight: {event.key_insight}")

    return 0


def cmd_reflect_daily(args: list[str]) -> int:
    """Run daily reflection."""
    print_banner("Daily Reflection")

    if "--fixtures" not in args:
        print_err("Only --fixtures mode is supported for now")
        print_help_text("Usage: atman reflect daily --fixtures")
        return 1

    print_ok("Using test fixtures...")
    demo_pace()

    experience_repo, identity_repo, _narrative_repo = setup_fixtures()
    date = datetime.now(UTC)

    print_ok(f"Reflecting on date: {date.strftime('%Y-%m-%d')}")
    demo_pace()

    reflection_model = MockReflectionModel()
    pattern_store = InMemoryPatternStore()
    event_store = InMemoryReflectionEventStore()

    service = DailyReflectionService(
        experience_repo=experience_repo,
        identity_repo=identity_repo,
        pattern_store=pattern_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    event = service.reflect(date)

    print_ok("\nReflection Complete!")
    demo_pace()
    print_info(f"  Level: {event.reflection_level}")
    print_info(f"  Experiences analyzed: {len(event.experiences_analyzed)}")
    print_info(f"  Patterns detected: {len(event.patterns_detected)}")
    print_info(f"  Reframing notes added: {event.reframing_notes_added}")
    print_info(f"  Key insight: {event.key_insight}")

    return 0


def cmd_reflect_deep(args: list[str]) -> int:
    """Run deep reflection."""
    print_banner("Deep Reflection")

    if "--fixtures" not in args:
        print_err("Only --fixtures mode is supported for now")
        print_help_text("Usage: atman reflect deep --fixtures")
        return 1

    print_ok("Using test fixtures...")
    demo_pace()

    experience_repo, identity_repo, narrative_repo = setup_fixtures()

    since = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    until = datetime.now(UTC)

    print_ok(f"Reflecting on period: {since.strftime('%Y-%m-%d')} to {until.strftime('%Y-%m-%d')}")
    demo_pace()

    reflection_model = MockReflectionModel()
    pattern_store = InMemoryPatternStore()
    health_store = InMemoryHealthAssessmentStore()
    event_store = InMemoryReflectionEventStore()

    service = DeepReflectionService(
        experience_repo=experience_repo,
        identity_repo=identity_repo,
        narrative_repo=narrative_repo,
        pattern_store=pattern_store,
        health_store=health_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    event = service.reflect(since, until)

    print_ok("\nReflection Complete!")
    demo_pace()
    print_info(f"  Level: {event.reflection_level}")
    print_info(f"  Experiences analyzed: {len(event.experiences_analyzed)}")
    print_info(f"  Patterns detected: {len(event.patterns_detected)}")
    print_info(f"  Reframing notes added: {event.reframing_notes_added}")

    if event.health_assessment_id:
        assessment = health_store.get(event.health_assessment_id)
        if assessment:
            print_info(f"  Health score: {assessment.overall_score:.2f}/1.0")

    print_info(f"  Key insight: {event.key_insight}")

    return 0


def main() -> int:
    """Main CLI entry point."""
    if len(sys.argv) < 3 or sys.argv[1] != "reflect":
        print_help_text(
            "Usage: python -m atman.cli_reflection reflect <micro|daily|deep> --fixtures"
        )
        return 1

    command = sys.argv[2]
    args = sys.argv[3:]

    if command == "micro":
        return cmd_reflect_micro(args)
    elif command == "daily":
        return cmd_reflect_daily(args)
    elif command == "deep":
        return cmd_reflect_deep(args)
    else:
        print_err(f"Unknown command: {command}")
        print_help_text("Available commands: micro, daily, deep")
        return 1


if __name__ == "__main__":
    sys.exit(main())
