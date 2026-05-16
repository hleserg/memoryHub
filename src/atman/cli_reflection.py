"""
CLI for Reflection Engine.

Commands (run from the repo with the package installed, e.g. ``pip install -e ".[dev]"``):

- python -m atman.cli_reflection reflect micro --fixtures
- python -m atman.cli_reflection reflect daily --fixtures
- python -m atman.cli_reflection reflect deep --fixtures

Note: Non-fixtures modes require integration with FileStateStore,
which is not yet implemented. Use ``python src/demo_reflection.py`` for the full walkthrough.
"""

import sys
from datetime import UTC, datetime
from uuid import UUID, uuid4

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
from atman.core.models.experience import (
    EmotionalDepth,
    FeltSense,
    KeyMoment,
    ReframingNote,
    ReframingNoteAppendResult,
    SessionExperience,
)
from atman.core.models.identity import Identity, IdentitySnapshot
from atman.core.models.narrative import LayerType, NarrativeDocument, NarrativeLayer
from atman.core.models.session import Session
from atman.core.narrative_write_audit import NoOpNarrativeWriteAudit
from atman.core.services.narrative_revision import NarrativeRevisionService
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

    def add_reframing_note(
        self, experience_id: UUID, note: ReframingNote
    ) -> ReframingNoteAppendResult:
        """Add reframing note; return explicit append outcome."""
        exp = self.experiences.get(experience_id)
        if exp is None:
            return ReframingNoteAppendResult.EXPERIENCE_NOT_FOUND
        if note.triggered_by and any(
            n.triggered_by == note.triggered_by for n in exp.reframing_notes
        ):
            return ReframingNoteAppendResult.DUPLICATE_TRIGGERED_BY
        exp.add_reframing_note(note)
        return ReframingNoteAppendResult.STORED

    # ---- SessionRepository surface (R3) ----------------------------------

    def _synth(self, exp: SessionExperience) -> tuple[Session, list[KeyMoment]]:
        session = Session(
            id=exp.id,
            agent_id=uuid4(),
            started_at=exp.timestamp,
            identity_snapshot_id=exp.identity_snapshot_id,
        )
        depth = EmotionalDepth.PROFOUND if exp.has_profound_moment else EmotionalDepth.MEANINGFUL
        moments = [
            KeyMoment(
                id=km_id,
                session_id=exp.id,
                what_happened="synthetic",
                how_i_felt=FeltSense(
                    emotional_valence=0.0,
                    emotional_intensity=exp.avg_emotional_intensity,
                    depth=depth,
                ),
                why_it_matters="synthetic CLI moment",
                values_touched=[],
            )
            for km_id in exp.key_moment_ids
        ]
        return session, moments

    def get_session(self, session_id: UUID) -> Session | None:
        exp = self.get(session_id)
        return None if exp is None else self._synth(exp)[0]

    def list_recent_sessions(
        self, agent_id: UUID | None = None, *, limit: int = 10
    ) -> list[Session]:
        return [self._synth(e)[0] for e in self.get_recent(limit)]

    def get_sessions_in_range(
        self,
        agent_id_or_start,
        start_or_end,
        end=None,
    ) -> list[Session]:
        if isinstance(agent_id_or_start, datetime):
            start, end_dt = agent_id_or_start, start_or_end
        else:
            start, end_dt = start_or_end, end
        assert end_dt is not None
        return sorted(
            (self._synth(e)[0] for e in self.get_in_range(start, end_dt)),
            key=lambda s: s.started_at,
        )

    def get_key_moments_for_session(self, session_id: UUID) -> list[KeyMoment]:
        exp = self.get(session_id)
        return [] if exp is None else self._synth(exp)[1]

    def get_key_moments_in_range(self, start: datetime, end: datetime) -> list[KeyMoment]:
        out: list[KeyMoment] = []
        for e in self.get_in_range(start, end):
            out.extend(self._synth(e)[1])
        return out


class MockIdentityRepo:
    """Mock identity repository."""

    def __init__(self, identity: Identity):
        """Initialize with identity."""
        self.identity = identity
        self._snapshots: dict[UUID, IdentitySnapshot] = {}

    def get_current(self) -> Identity | None:
        """Get current identity."""
        return self.identity

    def get_snapshot(self, snapshot_id: UUID) -> IdentitySnapshot | None:
        """Get snapshot."""
        return self._snapshots.get(snapshot_id)

    def get_history(self) -> list[IdentitySnapshot]:
        """Get history."""
        return list(self._snapshots.values())

    def update(self, identity: Identity) -> None:
        """Update identity."""
        self.identity = identity

    def create_snapshot(
        self,
        identity: Identity,
        description: str,
        change_summary: str,
        *,
        snapshot_id: UUID | None = None,
    ) -> IdentitySnapshot:
        """Create snapshot."""
        sid = snapshot_id or uuid4()
        snap = IdentitySnapshot(
            id=sid,
            identity_id=identity.id,
            identity_snapshot=identity.model_copy(deep=True),
            description=description,
            change_summary=change_summary,
        )
        self._snapshots[sid] = snap
        return snap


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
    narrative_revision = NarrativeRevisionService(
        narrative_repo, reflection_model, narrative_audit=NoOpNarrativeWriteAudit()
    )

    service = MicroReflectionService(
        session_repo=experience_repo,
        narrative_revision=narrative_revision,
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
        session_repo=experience_repo,
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
        session_repo=experience_repo,
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
