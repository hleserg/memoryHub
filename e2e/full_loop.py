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
import shutil
import sys
import tempfile
import warnings
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from atman.adapters.reflection.state_store_session_repository import (
    StateStoreSessionRepository,
)
from atman.adapters.storage.file_state_store import FileStateStore
from atman.adapters.storage.in_memory_reflection_store import (
    InMemoryHealthAssessmentStore,
    InMemoryPatternStore,
    InMemoryReflectionEventStore,
)
from atman.core.clock_impl import FrozenClock, SystemClock
from atman.core.models import (
    CoreValue,
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
    SessionResult,
)
from atman.core.models.reflection import (
    HealthCriterionOutput,
    NarrativeUpdateOutput,
    PatternDetectionOutput,
    ReframingNoteOutput,
)
from atman.core.narrative_write_audit import NoOpNarrativeWriteAudit
from atman.core.ports.reflection import (
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

# Repository adapter limits for E2E testing
_EXPERIENCE_SESSION_LIMIT = 100
_EXPERIENCE_RANGE_LIMIT = 1000
_EXPERIENCE_ALL_LIMIT = 10000
_SNAPSHOT_SEARCH_LIMIT = 1000


def _load_fixture_sessions(locale: str = "en", max_count: int = 5) -> list[Path]:
    """Load session fixture JSON files from e2e/fixtures/sessions/{locale}/."""
    all_sorted = load_all_fixture_sessions_sorted(locale)
    return all_sorted[:max_count]


def load_all_fixture_sessions_sorted(locale: str = "en") -> list[Path]:
    """
    All ``session_*.json`` fixtures under ``e2e/fixtures/sessions/{locale}/``,
    ordered by ``metadata.session_number`` (ascending).
    """
    repo_root = Path(__file__).resolve().parent.parent
    fixtures_dir = repo_root / "e2e" / "fixtures" / "sessions" / locale
    if not fixtures_dir.exists():
        return []
    numbered: list[tuple[int, Path]] = []
    for path in fixtures_dir.glob("session_*.json"):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            meta = data.get("metadata") or {}
            sn = meta.get("session_number")
            if sn is None:
                continue
            numbered.append((int(sn), path))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
    numbered.sort(key=lambda x: x[0])
    return [p for _, p in numbered]


def _parse_fixture(fixture_path: Path) -> tuple[list[SessionEvent], list[KeyMomentInput], dict]:
    """
    Parse fixture JSON into SessionEvent, KeyMomentInput, and expected outcome.

    Uses Pydantic validation via e2e.models to ensure type safety.

    Args:
        fixture_path: Path to the session fixture JSON file

    Returns:
        Tuple of (events, key_moments, expected_outcome)

    Raises:
        ValueError: If file not found, invalid JSON, or validation fails
    """
    try:
        with open(fixture_path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError as e:
        raise ValueError(f"Fixture file not found: {fixture_path}") from e
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in fixture {fixture_path}: {e}") from e
    except Exception as e:
        raise ValueError(f"Failed to load fixture {fixture_path}: {e}") from e

    # Validate via Pydantic
    from e2e.models import (
        SessionFixtureDocument,
        fixture_events_to_session_events,
        fixture_moments_to_key_moment_inputs,
    )

    try:
        fixture_doc = SessionFixtureDocument.model_validate(data)
    except Exception as e:
        raise ValueError(f"Fixture validation failed for {fixture_path}: {e}") from e

    # Convert using helper functions
    session_id = UUID(int=0)  # placeholder; replaced at call site
    events = fixture_events_to_session_events(fixture_doc.events, session_id)
    moments = fixture_moments_to_key_moment_inputs(fixture_doc.key_moments)
    outcome = fixture_doc.expected_session_outcome.model_dump()

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
        *,
        key_moments_by_session=None,
    ) -> PatternDetectionOutput:
        _ = context
        _ = key_moments_by_session
        if len(experiences) < 2:
            return PatternDetectionOutput()
        return PatternDetectionOutput(
            description=(
                f"Pattern detected: recurring theme across {len(experiences)} experiences"
            ),
            confidence=0.75,
        )

    def generate_reframing_note(
        self,
        experience,
        context: dict,
        *,
        key_moments_by_session=None,
    ) -> ReframingNoteOutput:
        _ = key_moments_by_session
        return ReframingNoteOutput(
            reflection=f"Reframing: deeper perspective on experience {experience.id}",
            reflection_type="e2e",
        )

    def propose_narrative_update(
        self,
        current_narrative,
        recent_experiences: list,
        reflection_level,
        *,
        key_moments_by_session=None,
    ) -> NarrativeUpdateOutput:
        _ = key_moments_by_session
        return NarrativeUpdateOutput(
            body=f"Narrative update proposal at {reflection_level.value} level"
        )

    def assess_health_criterion(
        self,
        identity,
        experiences: list,
        criterion,
        *,
        key_moments_by_session=None,
    ) -> HealthCriterionOutput:
        _ = key_moments_by_session
        return HealthCriterionOutput(
            score=0.7,
            evidence=[f"Criterion {criterion.value} assessed"],
            concerns=["No major concerns"],
        )


class StateStoreIdentityAdapter(IdentityRepository):
    """
    Adapter: StateStore → IdentityRepository port.

    Bridges FileStateStore to Reflection Engine's IdentityRepository protocol.

    SEAMS:
    - Assumes single identity per workspace (no multi-agent support)
    - get_history() returns empty list (FileStateStore needs identity_id)
    - get_snapshot() uses inefficient linear search
    """

    def __init__(self, state_store: FileStateStore):
        self._state_store = state_store

    def get_current(self) -> Identity | None:
        # SEAM: assumes single identity in workspace; real system would track agent_id
        identity_path = self._state_store.identity_path
        if not identity_path.exists():
            return None
        try:
            with open(identity_path, encoding="utf-8") as f:
                data = json.load(f)
            return Identity.model_validate(data)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            warnings.warn(f"Failed to load identity: {e}", stacklevel=2)
            return None

    def get_history(self) -> list[IdentitySnapshot]:
        # SEAM: FileStateStore doesn't expose all snapshots without identity_id
        # Return empty list is acceptable for E2E demo, but log warning for transparency
        warnings.warn(
            "StateStoreIdentityAdapter.get_history() returns empty list; "
            "FileStateStore requires identity_id for snapshot queries",
            stacklevel=2,
        )
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
    ) -> IdentitySnapshot:
        from atman.core.models.identity import IdentitySnapshot

        snap = IdentitySnapshot(
            id=snapshot_id or uuid4(),
            identity_id=identity.id,
            description=description,
            identity_snapshot=identity,
            change_summary=change_summary,
        )
        return self._state_store.create_identity_snapshot(snap)

    def get_snapshot(self, snapshot_id: UUID) -> IdentitySnapshot | None:
        # SEAM: FileStateStore doesn't have get_snapshot by ID; we search
        snapshots = self._state_store.list_identity_snapshots(
            identity_id=UUID(int=0), limit=_SNAPSHOT_SEARCH_LIMIT
        )
        for snap in snapshots:
            if snap.id == snapshot_id:
                return snap
        return None


class StateStoreNarrativeAdapter(NarrativeRepository):
    """
    Adapter: StateStore → NarrativeRepository port.

    Bridges FileStateStore to Reflection Engine's NarrativeRepository protocol.

    SEAMS:
    - get_history() returns empty list (FileStateStore doesn't track narrative versions)
    """

    def __init__(self, state_store: FileStateStore):
        self._state_store = state_store

    def get_current(self) -> NarrativeDocument | None:
        narrative_path = self._state_store.narrative_path
        if not narrative_path.exists():
            return None
        try:
            with open(narrative_path, encoding="utf-8") as f:
                data = json.load(f)
            return NarrativeDocument.model_validate(data)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            warnings.warn(f"Failed to load narrative: {e}", stacklevel=2)
            return None

    def get_history(self) -> list[NarrativeDocument]:
        # SEAM: FileStateStore doesn't have comprehensive narrative history API
        warnings.warn(
            "StateStoreNarrativeAdapter.get_history() returns empty list; "
            "FileStateStore doesn't track narrative version history",
            stacklevel=2,
        )
        return []

    def update(
        self, narrative: NarrativeDocument, *, expected_updated_at: datetime | None = None
    ) -> None:
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
    *,
    verbose: bool = True,
) -> tuple[UUID, SessionResult]:
    """
    Run a single session using fixture data.

    Returns ``(session_id, session_result)``.
    """
    events, moments, outcome = _parse_fixture(fixture_path)

    if verbose:
        print(f"  Starting session from {fixture_path.name}...")
    context = session_manager.start_session(agent_id)
    session_id = context.session_id

    # Record events
    for event in events:
        event_with_sid = event.model_copy(update={"session_id": session_id})
        session_manager.record_event(session_id, event_with_sid)

    # Record key moments
    for moment in moments:
        session_manager.append_key_moment_input(session_id, moment)

    # Finish session
    session_result = session_manager.finish_session(
        session_id,
        overall_emotional_tone=outcome.get("overall_emotional_tone", 0.0),
        key_insight=outcome.get("key_insight", "Session completed"),
        alignment_check=outcome.get("alignment_check", True),
    )

    if verbose:
        print(f"  Session {session_id} finished")
        print(f"    Events: {len(events)}, Key moments: {len(moments)}")
        if session_result.eigenstate:
            print(f"    Eigenstate emotional_tone: {session_result.eigenstate.emotional_tone:+.2f}")

    return session_id, session_result


@contextmanager
def temp_workspace():
    """
    Context manager for temporary workspace with automatic cleanup.

    Ensures workspace is removed even if script fails, preventing /tmp pollution.
    """
    workspace_path = Path(tempfile.mkdtemp(prefix="atman-e2e-full-loop-"))
    try:
        yield workspace_path
    finally:
        shutil.rmtree(workspace_path, ignore_errors=True)


def main() -> int:
    print("=" * 80)
    print("E2E-01: Full Integration Loop")
    print("=" * 80)
    print()

    # 1. Setup temp workspace with automatic cleanup
    print("[1] Setup: Creating temporary workspace")
    with temp_workspace() as workspace_path:
        return _run_e2e_loop(workspace_path)


def _run_e2e_loop(workspace_path: Path) -> int:
    """Run the full E2E loop in the given workspace."""
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
        session_id, _ = run_session_from_fixture(fixture_path, session_manager, agent_id, clock)
        session_ids_day1.append(session_id)

    if not session_ids_day1:
        print("    No sessions run (no fixtures)")

    # 6. Run MicroReflectionService after each session
    print()
    print("[6] Micro Reflection: After-session checkpoint")
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

    session_repo = StateStoreSessionRepository(state_store, agent_id=agent_id)

    micro_service = MicroReflectionService(
        session_repo=session_repo,
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
        session_repo=session_repo,
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
            session_id, _ = run_session_from_fixture(
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
        session_repo=session_repo,
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
