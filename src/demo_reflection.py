"""
Demo walkthrough for Reflection Engine (WP-04).

This demonstrates the three levels of reflection:
- Micro: After-session checkpoint
- Daily: Pattern detection across sessions
- Deep: Health assessment and identity revision

All outputs use Rich via atman.term for consistent styling.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from rich.table import Table

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
                why_it_matters="synthetic demo moment",
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
    """Mock identity repository for demo."""

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
    """Mock narrative repository for demo."""

    def __init__(self, narrative: NarrativeDocument):
        """Initialize with narrative."""
        self.narrative = narrative

    def get_current(self) -> NarrativeDocument | None:
        """Get current narrative."""
        return self.narrative.model_copy(deep=True)

    def update(
        self, narrative: NarrativeDocument, *, expected_updated_at: datetime | None = None
    ) -> None:
        """Update narrative with optional optimistic concurrency on ``updated_at``."""
        if expected_updated_at is not None and self.narrative.updated_at != expected_updated_at:
            raise NarrativePersistenceConflictError(
                "Narrative was modified concurrently since this snapshot was read."
            )
        self.narrative = narrative.model_copy(deep=True)

    def get_history(self) -> list[NarrativeDocument]:
        """Get history."""
        return []


def load_fixtures() -> tuple[list[SessionExperience], Identity]:
    """Load fixtures and anchor experience timestamps to the current UTC day (same as CLI)."""
    experiences = anchor_session_experiences_to_utc_day_window(
        load_reflection_session_experiences()
    )
    identity = load_reflection_identity()
    return experiences, identity


def demo_micro_reflection(
    experiences: list[SessionExperience],
    identity: Identity,
) -> None:
    """Demonstrate micro reflection."""
    print_banner("1. MICRO REFLECTION")
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
    narrative_revision = NarrativeRevisionService(
        narrative_repo, reflection_model, narrative_audit=NoOpNarrativeWriteAudit()
    )

    service = MicroReflectionService(
        experience_repo=exp_repo,
        narrative_revision=narrative_revision,
        event_store=event_store,
    )

    session_id = experiences[0].session_id
    print_ok(f"Running micro reflection for session: {session_id}")
    demo_pace()

    event = service.reflect(session_id)

    print_ok("\nMicro Reflection Complete!")
    demo_pace()

    table = Table(title="Reflection Summary")
    table.add_column("Metric")
    table.add_column("Value")

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
    print_banner("2. DAILY REFLECTION")
    print_help_text("Daily reflection analyzes experiences across the day to detect patterns.")
    demo_pace()

    exp_repo = MockExperienceRepo(experiences)
    identity_repo = MockIdentityRepo(identity)
    pattern_store = InMemoryPatternStore()
    reflection_model = MockReflectionModel()
    event_store = InMemoryReflectionEventStore()

    service = DailyReflectionService(
        session_repo=exp_repo,
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
    table.add_column("Metric")
    table.add_column("Value")

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
    print_banner("3. DEEP REFLECTION")
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
        session_repo=exp_repo,
        identity_repo=identity_repo,
        narrative_repo=narrative_repo,
        pattern_store=pattern_store,
        health_store=health_store,
        reflection_model=reflection_model,
        event_store=event_store,
    )

    until = datetime.now(UTC)
    since = until.replace(hour=0, minute=0, second=0, microsecond=0)

    print_ok(
        f"Running deep reflection from {since.strftime('%Y-%m-%d %H:%M')} "
        f"UTC to {until.strftime('%Y-%m-%d %H:%M')} UTC"
    )
    demo_pace()

    event = service.reflect(since, until)

    print_ok("\nDeep Reflection Complete!")
    demo_pace()

    table = Table(title="Reflection Summary")
    table.add_column("Metric")
    table.add_column("Value")

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
            print_ok("\nHealth Assessment (6 Jahoda criteria):")

            health_table = Table()
            health_table.add_column("Criterion")
            health_table.add_column("Score")

            for criterion, crit_assessment in assessment.criteria.items():
                health_table.add_row(
                    criterion.value.replace("_", " ").title(),
                    f"{crit_assessment.score:.2f}",
                )

            console.print(health_table)
            demo_pace()

    if event.narrative_changes_proposed:
        print_ok("\nProposed narrative update (carried on ReflectionEvent):")
        console.print(f"  {event.narrative_changes_proposed}")
        demo_pace()

    if event.identity_changes_proposed:
        print_ok("\nProposed identity changes (carried on ReflectionEvent):")
        console.print(f"  {event.identity_changes_proposed}")
        demo_pace()


def demo_narrative_revision(narrative: NarrativeDocument) -> None:
    """Demonstrate narrative revision service."""
    print_banner("4. NARRATIVE REVISION SERVICE")
    print_help_text(
        "NarrativeRevisionService manages narrative threads and layer updates during reflection."
    )
    demo_pace()

    from atman.core.narrative_write_audit import NoOpNarrativeWriteAudit
    from atman.core.services.narrative_revision import NarrativeRevisionService

    narrative_repo = MockNarrativeRepo(narrative)
    reflection_model = MockReflectionModel()

    service = NarrativeRevisionService(
        narrative_repo=narrative_repo,
        reflection_model=reflection_model,
        narrative_audit=NoOpNarrativeWriteAudit(),
    )

    print_ok("\n1. Opening a narrative thread:")
    demo_pace()

    thread = service.open_thread(
        title="Learning to handle uncertainty",
        description="A journey of becoming more comfortable with not knowing",
        context="Started when I first admitted I don't know something",
    )

    console.print(f"  ✓ Thread created: '{thread.title}'")
    console.print(f"    Status: {'active' if thread.is_active else 'closed'}")
    demo_pace()

    print_ok("\n2. Updating thread state:")
    demo_pace()

    updated_thread = service.update_thread(
        thread_id=str(thread.id),
        new_state="Making progress, feels more natural now",
        add_moment="Realized that admitting uncertainty builds trust",
    )

    if updated_thread:
        console.print(f"  ✓ Thread updated: {updated_thread.current_state}")
        console.print(f"    Key moments: {len(updated_thread.key_moments)}")
    demo_pace()

    print_ok("\n3. Closing the thread:")
    demo_pace()

    success = service.close_thread(
        thread_id=str(thread.id),
        reason="This has become a stable part of my identity",
    )

    if success:
        console.print("  ✓ Thread closed successfully")
        closed_narrative = narrative_repo.get_current()
        if closed_narrative:
            for t in closed_narrative.threads:
                if t.id == thread.id:
                    console.print(f"    Closure reason: {t.closure_reason}")
    demo_pace()

    print_ok("\n4. Active threads summary:")
    demo_pace()

    current_narrative = narrative_repo.get_current()
    if current_narrative:
        active = current_narrative.get_active_threads()
        console.print(f"  Active threads: {len(active)}")
        console.print(f"  Total threads: {len(current_narrative.threads)}")
    demo_pace()


def demo_principle_advisor(identity: Identity) -> None:
    """Demonstrate principle revision advisor."""
    print_banner("5. PRINCIPLE REVISION ADVISOR")
    print_help_text("The advisor helps distinguish habits from principles and suggests revisions.")
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
    print_banner("REFLECTION ENGINE DEMO")
    print_help_text(
        "This demo showcases WP-04: Reflection Engine (micro / daily / deep), "
        "then narrative revision and principle advisor walkthroughs."
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

    demo_narrative_revision(narrative)
    demo_principle_advisor(identity)

    print_banner("DEMO COMPLETE")
    print_ok(
        "Walkthrough covered:\n"
        "  • Micro, daily, and deep reflection\n"
        "  • NarrativeRevisionService (threads / layers)\n"
        "  • PrincipleRevisionAdvisor"
    )
    demo_pace()


if __name__ == "__main__":
    main()
