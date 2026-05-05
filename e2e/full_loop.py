#!/usr/bin/env python3
"""
E2E-01: Full integration loop over WP-01..05.

Demonstrates end-to-end flow:
1. Create temp workspace with FileStateStore
2. Initialize identity + narrative
3. Open session via SessionManager
4. Record events + key moments from generated fixtures
5. Finish session
6. Run MicroReflectionService
7. Simulate 2-3 more sessions during a "day"
8. Run DailyReflectionService
9. Simulate week of sessions
10. Run DeepReflectionService

Fixture source: PR #142 session JSON files (e2e/fixtures/sessions/en/...).

SEAMS AND CONTRACT ISSUES:
- If reflection services require model/LLM: use mock or skip with warning
- If eigenstate conflicts with identity provenance: log issue reference
- If narrative concurrent writes fail: log retry behavior
- Missing methods in ports: document as separate issue, not fixed here
"""

import json
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from atman.adapters.storage.file_state_store import FileStateStore
from atman.adapters.storage.in_memory_reflection_store import (
    InMemoryHealthAssessmentStore,
    InMemoryPatternStore,
    InMemoryReflectionEventStore,
)
from atman.core.clock_impl import FrozenClock, SystemClock
from atman.core.models import (
    CoreValue,
    EmotionalDepth,
    Goal,
    GoalHorizon,
    GoalOwner,
    Identity,
    IdentitySnapshot,
    KeyMomentInput,
    LayerType,
    NarrativeDocument,
    NarrativeLayer,
    SessionEvent,
)
from atman.core.narrative_write_audit import NoOpNarrativeWriteAudit
from atman.core.ports.reflection import (
    ExperienceRepository,
    IdentityRepository,
    NarrativeRepository,
    ReflectionModel,
)
from atman.core.services import SessionManager
from atman.core.services.narrative_revision import NarrativeRevisionService
from atman.core.services.reflection_service import (
    DailyReflectionService,
    DeepReflectionService,
    MicroReflectionService,
)


def _load_fixture_sessions(locale: str = "en", max_count: int = 5) -> list[Path]:
    """Load session fixture JSON files from e2e/fixtures/sessions/{locale}/."""
    repo_root = Path(__file__).resolve().parent.parent
    fixtures_dir = repo_root / "e2e" / "fixtures" / "sessions" / locale
    if not fixtures_dir.exists():
        return []
    json_files = sorted(fixtures_dir.glob("session_*.json"))
    return json_files[:max_count]


def _parse_fixture(fixture_path: Path) -> tuple[list[SessionEvent], list[KeyMomentInput], dict]:
    """Parse fixture JSON into SessionEvent, KeyMomentInput, and expected outcome."""
    with open(fixture_path, encoding="utf-8") as f:
        data = json.load(f)

    # SEAM: e2e.models.SessionFixtureDocument is the canonical shape;
    # this function assumes same structure but doesn't import to avoid circular dependency.
    # If shapes diverge, this will raise ValueError.

    events_raw = data.get("events", [])
    moments_raw = data.get("key_moments", [])
    outcome = data.get("expected_session_outcome", {})

    # Convert to domain models (injecting session_id at call site)
    events = [
        SessionEvent(
            session_id=UUID(int=0),  # placeholder; replaced at call site
            event_type=e["event_type"],
            description=e["description"],
            metadata=e.get("metadata", {}),
        )
        for e in events_raw
    ]

    moments = [
        KeyMomentInput(
            what_happened=m["what_happened"],
            emotional_valence=m["emotional_valence"],
            emotional_intensity=m["emotional_intensity"],
            depth=EmotionalDepth(m["depth"]),
            why_it_matters=m["why_it_matters"],
            values_touched=m.get("values_touched", []),
            principles_confirmed=m.get("principles_confirmed", []),
            principles_questioned=m.get("principles_questioned", []),
            what_changed=m.get("what_changed", ""),
            incomplete_coloring=m.get("incomplete_coloring", False),
        )
        for m in moments_raw
    ]

    return events, moments, outcome


class DeterministicReflectionModel(ReflectionModel):
    """
    Mock reflection model for E2E testing.

    SEAM: Real LLM integration would inject actual model here.
    For E2E, we use deterministic placeholder text to avoid external dependencies.
    """

    def detect_pattern(
        self,
        experiences: list,
        context: dict,
    ) -> str:
        if len(experiences) < 2:
            return ""
        return f"Pattern detected: recurring theme across {len(experiences)} experiences"

    def generate_reframing_note(
        self,
        experience,
        context: dict,
    ) -> str:
        return f"Reframing: deeper perspective on experience {experience.id}"

    def propose_narrative_update(
        self,
        current_narrative,
        recent_experiences: list,
        reflection_level,
    ) -> str:
        return f"Narrative update proposal at {reflection_level.value} level"

    def assess_health_criterion(
        self,
        identity,
        experiences: list,
        criterion,
    ) -> tuple[float, list[str], list[str]]:
        # Return (score, evidence, concerns)
        return (
            0.7,
            [f"Criterion {criterion.value} assessed"],
            ["No major concerns"],
        )


class StateStoreExperienceAdapter(ExperienceRepository):
    """Adapter: StateStore → ExperienceRepository port."""

    def __init__(self, state_store: FileStateStore):
        self._state_store = state_store

    def get(self, experience_id: UUID):
        record = self._state_store.get_experience(experience_id)
        return record.experience if record else None

    def get_all(self) -> list:
        records = self._state_store.list_recent_experiences(limit=10000)
        return [r.experience for r in records]

    def get_by_session(self, session_id: UUID) -> list:
        from atman.core.ports.state_store import SessionExperienceQuery

        records = self._state_store.search_experiences(
            SessionExperienceQuery(session_id), limit=100
        )
        return [r.experience for r in records]

    def get_in_range(self, start: datetime, end: datetime) -> list:
        from atman.core.ports.state_store import DateRangeQuery

        records = self._state_store.search_experiences(DateRangeQuery(start, end), limit=1000)
        return [r.experience for r in records]

    def get_recent(self, limit: int = 10) -> list:
        records = self._state_store.list_recent_experiences(limit=limit)
        return [r.experience for r in records]

    def update(self, experience) -> None:
        # SEAM: FileStateStore doesn't have direct update; would need refactor
        pass

    def add_reframing_note(self, experience_id: UUID, note):
        from atman.core.models.experience import ReframingNoteAppendResult

        result = self._state_store.add_reframing_note(experience_id, note)
        if result is None:
            return ReframingNoteAppendResult.EXPERIENCE_NOT_FOUND
        # SEAM: FileStateStore doesn't yet return enum; we assume success
        return ReframingNoteAppendResult.STORED


class StateStoreIdentityAdapter(IdentityRepository):
    """Adapter: StateStore → IdentityRepository port."""

    def __init__(self, state_store: FileStateStore):
        self._state_store = state_store

    def get_current(self) -> Identity | None:
        # SEAM: assumes single identity in workspace; real system would track agent_id
        identity_path = self._state_store.identity_path
        if not identity_path.exists():
            return None
        with open(identity_path, encoding="utf-8") as f:
            data = json.load(f)
        return Identity.model_validate(data)

    def get_history(self) -> list[IdentitySnapshot]:
        # SEAM: FileStateStore doesn't expose all snapshots without identity_id
        return []

    def update(self, identity: Identity) -> None:
        self._state_store.save_identity(identity)

    def create_snapshot(
        self,
        identity: Identity,
        description: str,
        change_summary: str,
        *,
        snapshot_id: UUID | None = None,
    ):
        from atman.core.models.identity import IdentitySnapshot

        snap = IdentitySnapshot(
            id=snapshot_id or uuid4(),
            identity_id=identity.id,
            description=description,
            identity_snapshot=identity,
            change_summary=change_summary,
        )
        return self._state_store.create_identity_snapshot(snap)

    def get_snapshot(self, snapshot_id: UUID):
        # SEAM: FileStateStore doesn't have get_snapshot by ID; we search
        snapshots = self._state_store.list_identity_snapshots(identity_id=UUID(int=0), limit=1000)
        for snap in snapshots:
            if snap.id == snapshot_id:
                return snap
        return None


class StateStoreNarrativeAdapter(NarrativeRepository):
    """Adapter: StateStore → NarrativeRepository port."""

    def __init__(self, state_store: FileStateStore):
        self._state_store = state_store

    def get_current(self) -> NarrativeDocument | None:
        narrative_path = self._state_store.narrative_path
        if not narrative_path.exists():
            return None
        with open(narrative_path, encoding="utf-8") as f:
            data = json.load(f)
        return NarrativeDocument.model_validate(data)

    def get_history(self) -> list:
        # SEAM: FileStateStore doesn't have comprehensive narrative history API
        return []

    def update(self, narrative: NarrativeDocument, *, expected_updated_at: datetime | None = None) -> None:
        self._state_store.save_narrative(narrative, expected_updated_at=expected_updated_at)

    def save(self, narrative: NarrativeDocument) -> NarrativeDocument:
        return self._state_store.save_narrative(narrative)


def create_bootstrap_identity(agent_id: UUID) -> Identity:
    """Create minimal bootstrap identity for E2E demo."""
    return Identity(
        id=agent_id,
        self_description="E2E demo agent: exploring identity, experience, and reflection loops.",
        core_values=[
            CoreValue(
                name="clarity",
                description="Prefer clear, honest understanding over comfortable ambiguity",
                confidence=0.6,
                justification="Bootstrap value for testing",
            ),
            CoreValue(
                name="growth",
                description="Learning from experience and adjusting course",
                confidence=0.5,
                justification="Bootstrap value for testing",
            ),
        ],
        goals=[
            Goal(
                content="Complete E2E integration test successfully",
                horizon=GoalHorizon.SHORT,
                owner=GoalOwner.AGENT,
                active=True,
            )
        ],
        emotional_baseline=0.0,
    )


def create_bootstrap_narrative(identity_id: UUID) -> NarrativeDocument:
    """Create minimal bootstrap narrative for E2E demo."""
    return NarrativeDocument(
        identity_id=identity_id,
        core_layer=NarrativeLayer(
            layer_type=LayerType.CORE,
            content="I am a test agent learning to integrate experience, reflection, and identity. "
            "This is my first full loop.",
        ),
        recent_layer=NarrativeLayer(
            layer_type=LayerType.RECENT,
            content="Starting E2E integration test.",
        ),
    )


def run_session_from_fixture(
    fixture_path: Path,
    session_manager: SessionManager,
    agent_id: UUID,
    clock: SystemClock | FrozenClock,
) -> UUID:
    """
    Run a single session using fixture data.

    Returns session_id.
    """
    events, moments, outcome = _parse_fixture(fixture_path)

    print(f"  Starting session from {fixture_path.name}...")
    context = session_manager.start_session(agent_id)
    session_id = context.session_id

    # Record events
    for event in events:
        event_with_sid = event.model_copy(update={"session_id": session_id})
        session_manager.record_event(session_id, event_with_sid)

    # Record key moments
    for moment in moments:
        session_manager.record_key_moment(session_id, moment)

    # Finish session
    session_result = session_manager.finish_session(
        session_id,
        overall_emotional_tone=outcome.get("overall_emotional_tone", 0.0),
        key_insight=outcome.get("key_insight", "Session completed"),
        alignment_check=outcome.get("alignment_check", True),
    )

    print(f"  Session {session_id} finished")
    print(f"    Events: {len(events)}, Key moments: {len(moments)}")
    if session_result.eigenstate:
        print(
            f"    Eigenstate emotional_tone: {session_result.eigenstate.emotional_tone:+.2f}"
        )

    return session_id


def main() -> int:
    print("=" * 80)
    print("E2E-01: Full Integration Loop")
    print("=" * 80)
    print()

    # 1. Setup temp workspace
    print("[1] Setup: Creating temporary workspace")
    workspace_path = Path(tempfile.mkdtemp(prefix="atman-e2e-full-loop-"))
    print(f"    Workspace: {workspace_path}")
    state_store = FileStateStore(workspace=workspace_path)
    clock = SystemClock()

    # 2. Initialize identity + narrative
    print()
    print("[2] Initialize: Creating bootstrap identity and narrative")
    agent_id = uuid4()
    identity = create_bootstrap_identity(agent_id)
    state_store.save_identity(identity)
    print(f"    Identity ID: {agent_id}")
    print(f"    Core values: {', '.join(v.name for v in identity.core_values)}")

    narrative = create_bootstrap_narrative(agent_id)
    state_store.save_narrative(narrative)
    print("    Narrative created")

    # 3. Load fixture sessions
    print()
    print("[3] Fixtures: Loading session fixtures")
    fixture_files = _load_fixture_sessions(locale="en", max_count=5)
    if not fixture_files:
        print("    WARNING: No fixture files found under e2e/fixtures/sessions/en/")
        print(
            "    Run `python -m e2e.generate_fixtures` to create them (requires ANTHROPIC_API_KEY)"
        )
        print("    Continuing with empty corpus...")
        # Don't fail — allow testing without fixtures
        fixture_files = []
    else:
        print(f"    Loaded {len(fixture_files)} fixture files")

    # 4. Session Manager setup
    print()
    print("[4] Session Manager: Initializing")
    session_manager = SessionManager(state_store, clock=clock)
    print("    Ready")

    # 5. Simulate 2–3 sessions during a "day"
    print()
    print("[5] Day Simulation: Running 2–3 sessions")
    day_start = datetime.now(UTC)
    session_ids_day1 = []

    for i, fixture_path in enumerate(fixture_files[:3], start=1):
        print(f"  Session {i}/3:")
        session_id = run_session_from_fixture(fixture_path, session_manager, agent_id, clock)
        session_ids_day1.append(session_id)

    if not session_ids_day1:
        print("    No sessions run (no fixtures)")

    # 6. Run MicroReflectionService after each session
    print()
    print("[6] Micro Reflection: After-session checkpoint")
    experience_repo = StateStoreExperienceAdapter(state_store)
    identity_repo = StateStoreIdentityAdapter(state_store)
    narrative_repo = StateStoreNarrativeAdapter(state_store)
    event_store = InMemoryReflectionEventStore()

    reflection_model = DeterministicReflectionModel()
    narrative_audit = NoOpNarrativeWriteAudit()

    narrative_revision = NarrativeRevisionService(
        narrative_repo=narrative_repo,
        reflection_model=reflection_model,
        narrative_audit=narrative_audit,
        clock=clock,
    )

    micro_service = MicroReflectionService(
        experience_repo=experience_repo,
        narrative_revision=narrative_revision,
        event_store=event_store,
        clock=clock,
    )

    for session_id in session_ids_day1:
        print(f"  Micro reflect on session {session_id}...")
        reflection_event = micro_service.reflect(session_id)
        print(f"    Result: {reflection_event.key_insight}")

    # 7. Run DailyReflectionService
    print()
    print("[7] Daily Reflection: Pattern detection for day")
    pattern_store = InMemoryPatternStore()

    daily_service = DailyReflectionService(
        experience_repo=experience_repo,
        identity_repo=identity_repo,
        pattern_store=pattern_store,
        reflection_model=reflection_model,
        event_store=event_store,
        clock=clock,
    )

    daily_event = daily_service.reflect(day_start)
    print(f"    Key insight: {daily_event.key_insight}")
    print(f"    Patterns detected: {len(daily_event.patterns_detected)}")
    print(f"    Reframing notes added: {daily_event.reframing_notes_added}")

    # 8. Simulate "week" of sessions (add 2 more sessions with time offset)
    print()
    print("[8] Week Simulation: Running 2 more sessions (different days)")
    session_ids_week = list(session_ids_day1)

    # Advance clock by 2 days for next session
    for day_offset in [2, 4]:
        frozen_time = day_start + timedelta(days=day_offset)
        frozen_clock = FrozenClock(frozen_time)
        session_manager_frozen = SessionManager(state_store, clock=frozen_clock)

        if len(fixture_files) > (3 + (day_offset // 2) - 1):
            fixture_path = fixture_files[3 + (day_offset // 2) - 1]
            print(f"  Day +{day_offset}: session from {fixture_path.name}")
            session_id = run_session_from_fixture(
                fixture_path, session_manager_frozen, agent_id, frozen_clock
            )
            session_ids_week.append(session_id)
        else:
            print(f"  Day +{day_offset}: skipped (no fixture available)")

    # 9. Run DeepReflectionService for the week
    print()
    print("[9] Deep Reflection: Health assessment for week")
    health_store = InMemoryHealthAssessmentStore()

    deep_service = DeepReflectionService(
        experience_repo=experience_repo,
        identity_repo=identity_repo,
        narrative_repo=narrative_repo,
        pattern_store=pattern_store,
        health_store=health_store,
        reflection_model=reflection_model,
        event_store=event_store,
        clock=clock,
    )

    week_start = day_start
    week_end = day_start + timedelta(days=7)
    deep_event = deep_service.reflect(week_start, week_end)

    print(f"    Key insight: {deep_event.key_insight}")
    print(f"    Experiences analyzed: {len(deep_event.experiences_analyzed)}")
    print(f"    Patterns detected: {len(deep_event.patterns_detected)}")
    print(f"    Reframing notes added: {deep_event.reframing_notes_added}")
    if deep_event.health_assessment_id:
        health = health_store.get(deep_event.health_assessment_id)
        if health:
            print(f"    Health score: {health.overall_score:.2f}/1.0")

    # 10. Summary
    print()
    print("=" * 80)
    print("E2E-01 Complete")
    print("=" * 80)
    print(f"Total sessions run: {len(session_ids_week)}")
    print(f"Reflection events: {len(event_store.get_all())}")
    print(f"Workspace: {workspace_path}")
    print()
    print("SEAMS ENCOUNTERED:")
    print("  - Reflection model: using deterministic mock (real LLM via port)")
    print("  - StateStore adapters: minimal bridge to Reflection ports")
    print("  - Fixture dependency: graceful degradation if no JSON files")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
