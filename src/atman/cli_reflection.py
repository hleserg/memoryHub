"""
CLI for Reflection Engine.

Commands:
- atman reflect micro --session-id <uuid> | --fixtures
- atman reflect daily --date YYYY-MM-DD | --fixtures
- atman reflect deep --since YYYY-MM-DD --until YYYY-MM-DD | --fixtures
"""

import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from atman.adapters.reflection.mock_reflection_model import MockReflectionModel
from atman.adapters.storage.file_state_store import FileStateStore
from atman.adapters.storage.in_memory_reflection_store import (
    InMemoryHealthAssessmentStore,
    InMemoryPatternStore,
    InMemoryReflectionEventStore,
)
from atman.core.models.experience import (
    EmotionalDepth,
    FeltSense,
    KeyMoment,
    SessionExperience,
)
from atman.core.models.identity import Identity
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
    print_ok,
)


def setup_fixtures() -> tuple[FileStateStore, Identity, NarrativeDocument]:
    """
    Set up test fixtures for reflection.
    
    Creates:
    - Some sample experiences
    - A basic identity
    - A narrative document
    
    Returns:
        Tuple of (state_store, identity, narrative)
    """
    state_store = FileStateStore(Path(".atman-reflection-test"))
    
    identity = Identity(
        self_description="I am learning to understand myself through experience.",
        core_values=[],
        emotional_baseline=0.1,
    )
    
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
    
    session_id = uuid4()
    exp1 = SessionExperience(
        session_id=session_id,
        key_moments=[
            KeyMoment(
                what_happened="User asked me a question I didn't know how to answer",
                how_i_felt=FeltSense(
                    emotional_valence=-0.2,
                    emotional_intensity=0.6,
                    depth=EmotionalDepth.MEANINGFUL,
                ),
                why_it_matters="This tested my honesty about limitations",
                values_touched=["honesty", "competence"],
                what_changed="Realized I need to be more comfortable with uncertainty",
            )
        ],
        identity_snapshot_id=identity.id,
        importance=0.7,
        salience=0.7,
    )
    
    exp2 = SessionExperience(
        session_id=uuid4(),
        key_moments=[
            KeyMoment(
                what_happened="Successfully helped user with a complex problem",
                how_i_felt=FeltSense(
                    emotional_valence=0.5,
                    emotional_intensity=0.7,
                    depth=EmotionalDepth.MEANINGFUL,
                ),
                why_it_matters="Confirmed my ability to be helpful",
                values_touched=["competence", "helpfulness"],
                what_changed="Gained confidence in problem-solving",
            )
        ],
        identity_snapshot_id=identity.id,
        importance=0.6,
        salience=0.6,
    )
    
    state_store.save_identity(identity)
    state_store.save_narrative(narrative)
    state_store.save_experience(exp1)
    state_store.save_experience(exp2)
    
    return state_store, identity, narrative


def cmd_reflect_micro(args: list[str]) -> int:
    """Run micro reflection."""
    print_banner("Micro Reflection", width=70)
    
    use_fixtures = "--fixtures" in args
    
    if use_fixtures:
        print_ok("Using test fixtures...")
        demo_pace()
        
        state_store, identity, narrative = setup_fixtures()
        
        experiences = state_store.get_all_experiences()
        if not experiences:
            print_err("No experiences in fixtures")
            return 1
        
        session_id = experiences[0].session_id
    else:
        if "--session-id" not in args:
            print_help_text("Usage: atman reflect micro --session-id <uuid> | --fixtures")
            return 1
        
        try:
            session_id_idx = args.index("--session-id") + 1
            session_id = UUID(args[session_id_idx])
        except (ValueError, IndexError):
            print_err("Invalid session ID")
            return 1
        
        state_store = FileStateStore(Path(".atman"))
        identity = state_store.get_identity()
        narrative = state_store.get_narrative()
        
        if not identity or not narrative:
            print_err("No identity or narrative found. Run bootstrap first.")
            return 1
    
    print_ok(f"Reflecting on session: {session_id}")
    demo_pace()
    
    reflection_model = MockReflectionModel()
    event_store = InMemoryReflectionEventStore()
    
    service = MicroReflectionService(
        experience_repo=state_store,
        narrative_repo=state_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )
    
    event = service.reflect(session_id)
    
    print_ok("\nReflection Complete!")
    demo_pace()
    print(f"  Level: {event.reflection_level}")
    print(f"  Experiences analyzed: {len(event.experiences_analyzed)}")
    print(f"  Key insight: {event.key_insight}")
    
    if use_fixtures:
        state_store.storage_path.unlink(missing_ok=True)
    
    return 0


def cmd_reflect_daily(args: list[str]) -> int:
    """Run daily reflection."""
    print_banner("Daily Reflection", width=70)
    
    use_fixtures = "--fixtures" in args
    
    if use_fixtures:
        print_ok("Using test fixtures...")
        demo_pace()
        
        state_store, identity, narrative = setup_fixtures()
        date = datetime.now(UTC)
    else:
        if "--date" not in args:
            print_help_text("Usage: atman reflect daily --date YYYY-MM-DD | --fixtures")
            return 1
        
        try:
            date_idx = args.index("--date") + 1
            date = datetime.strptime(args[date_idx], "%Y-%m-%d").replace(tzinfo=UTC)
        except (ValueError, IndexError):
            print_err("Invalid date format. Use YYYY-MM-DD")
            return 1
        
        state_store = FileStateStore(Path(".atman"))
        identity = state_store.get_identity()
        
        if not identity:
            print_err("No identity found. Run bootstrap first.")
            return 1
    
    print_ok(f"Reflecting on date: {date.strftime('%Y-%m-%d')}")
    demo_pace()
    
    reflection_model = MockReflectionModel()
    pattern_store = InMemoryPatternStore()
    event_store = InMemoryReflectionEventStore()
    
    service = DailyReflectionService(
        experience_repo=state_store,
        identity_repo=state_store,
        pattern_store=pattern_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )
    
    event = service.reflect(date)
    
    print_ok("\nReflection Complete!")
    demo_pace()
    print(f"  Level: {event.reflection_level}")
    print(f"  Experiences analyzed: {len(event.experiences_analyzed)}")
    print(f"  Patterns detected: {len(event.patterns_detected)}")
    print(f"  Reframing notes added: {event.reframing_notes_added}")
    print(f"  Key insight: {event.key_insight}")
    
    if use_fixtures:
        state_store.storage_path.unlink(missing_ok=True)
    
    return 0


def cmd_reflect_deep(args: list[str]) -> int:
    """Run deep reflection."""
    print_banner("Deep Reflection", width=70)
    
    use_fixtures = "--fixtures" in args
    
    if use_fixtures:
        print_ok("Using test fixtures...")
        demo_pace()
        
        state_store, identity, narrative = setup_fixtures()
        
        since = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        until = datetime.now(UTC)
    else:
        if "--since" not in args or "--until" not in args:
            print_help_text(
                "Usage: atman reflect deep --since YYYY-MM-DD --until YYYY-MM-DD | --fixtures"
            )
            return 1
        
        try:
            since_idx = args.index("--since") + 1
            until_idx = args.index("--until") + 1
            
            since = datetime.strptime(args[since_idx], "%Y-%m-%d").replace(tzinfo=UTC)
            until = datetime.strptime(args[until_idx], "%Y-%m-%d").replace(
                tzinfo=UTC, hour=23, minute=59, second=59
            )
        except (ValueError, IndexError):
            print_err("Invalid date format. Use YYYY-MM-DD")
            return 1
        
        state_store = FileStateStore(Path(".atman"))
        identity = state_store.get_identity()
        narrative = state_store.get_narrative()
        
        if not identity or not narrative:
            print_err("No identity or narrative found. Run bootstrap first.")
            return 1
    
    print_ok(
        f"Reflecting on period: {since.strftime('%Y-%m-%d')} to {until.strftime('%Y-%m-%d')}"
    )
    demo_pace()
    
    reflection_model = MockReflectionModel()
    pattern_store = InMemoryPatternStore()
    health_store = InMemoryHealthAssessmentStore()
    event_store = InMemoryReflectionEventStore()
    
    service = DeepReflectionService(
        experience_repo=state_store,
        identity_repo=state_store,
        narrative_repo=state_store,
        pattern_store=pattern_store,
        health_store=health_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )
    
    event = service.reflect(since, until)
    
    print_ok("\nReflection Complete!")
    demo_pace()
    print(f"  Level: {event.reflection_level}")
    print(f"  Experiences analyzed: {len(event.experiences_analyzed)}")
    print(f"  Patterns detected: {len(event.patterns_detected)}")
    print(f"  Reframing notes added: {event.reframing_notes_added}")
    
    if event.health_assessment_id:
        assessment = health_store.get(event.health_assessment_id)
        if assessment:
            print(f"  Health score: {assessment.overall_score:.2f}/1.0")
    
    print(f"  Key insight: {event.key_insight}")
    
    if use_fixtures:
        state_store.storage_path.unlink(missing_ok=True)
    
    return 0


def main() -> int:
    """Main CLI entry point."""
    if len(sys.argv) < 3 or sys.argv[1] != "reflect":
        print_help_text(
            "Usage: python -m atman.cli_reflection reflect <micro|daily|deep> [options]"
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
