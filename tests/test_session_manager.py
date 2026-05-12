"""
Tests for Session Manager.

Tests session lifecycle, key moment recording, and experience creation.
"""

import json
import threading
from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest

from atman.adapters.storage.file_state_store import FileStateStore
from atman.adapters.storage.in_memory_state_store import InMemoryStateStore
from atman.core.clock_impl import FrozenClock
from atman.core.models import (
    ActiveSessionSummary,
    CoreValue,
    Eigenstate,
    EmotionalDepth,
    ExperienceRecord,
    Goal,
    GoalHorizon,
    Identity,
    KeyMomentInput,
    LayerType,
    NarrativeDocument,
    NarrativeLayer,
    SessionEvent,
    SessionExperience,
    SessionResult,
)
from atman.core.ports.state_store import SessionExperienceQuery
from atman.core.services import (
    SessionAlreadyFinishedError,
    SessionManager,
    SessionNotFoundError,
    TooManyActiveSessionsError,
)
from atman.core.services.session_manager import deterministic_session_experience_id


@pytest.fixture(params=["in_memory", "file_based"])
def temp_storage(request, tmp_path):
    """Create storage adapter (parametrized for unit + integration tests)."""
    if request.param == "in_memory":
        return InMemoryStateStore()
    else:  # file_based
        return FileStateStore(workspace=tmp_path / "session_test")


@pytest.fixture
def frozen_clock():
    """Frozen clock for deterministic timestamps."""
    return FrozenClock(datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC))


@pytest.fixture
def identity_fixture():
    """Create test identity."""
    return Identity(
        id=uuid4(),
        self_description="Test agent",
        core_values=[
            CoreValue(
                name="honesty",
                description="Being truthful",
                confidence=0.8,
            )
        ],
        goals=[
            Goal(
                content="Test goal",
                horizon=GoalHorizon.SHORT,
            )
        ],
        emotional_baseline=0.0,
    )


@pytest.fixture
def narrative_fixture(identity_fixture):
    """Create test narrative."""
    return NarrativeDocument(
        identity_id=identity_fixture.id,
        core_layer=NarrativeLayer(
            layer_type=LayerType.CORE,
            content="Core narrative",
        ),
        recent_layer=NarrativeLayer(
            layer_type=LayerType.RECENT,
            content="Recent narrative",
        ),
    )


@pytest.fixture
def session_manager(temp_storage, identity_fixture, narrative_fixture, frozen_clock):
    """Create session manager with test data and frozen clock."""
    temp_storage.save_identity(identity_fixture)
    temp_storage.save_narrative(narrative_fixture)
    return SessionManager(temp_storage, clock=frozen_clock), identity_fixture.id


def test_start_session_returns_context_with_identity_and_narrative(session_manager):
    """Test that start_session returns context with identity and narrative."""
    manager, agent_id = session_manager

    context = manager.start_session(agent_id)

    assert context is not None
    assert context.session_id is not None
    assert context.identity is not None
    assert context.identity.id == agent_id
    assert context.narrative is not None
    assert context.narrative.core_layer.content == "Core narrative"
    assert context.emotional_baseline == 0.0


def test_start_session_fails_without_identity(temp_storage):
    """Test that start_session fails if identity not found."""
    manager = SessionManager(temp_storage)
    fake_agent_id = uuid4()

    with pytest.raises(ValueError, match="Identity not found"):
        manager.start_session(fake_agent_id)


def test_start_session_fails_without_narrative(temp_storage, identity_fixture):
    """A session cannot start without the matching narrative context."""
    temp_storage.save_identity(identity_fixture)
    manager = SessionManager(temp_storage)

    with pytest.raises(ValueError, match="Narrative not found"):
        manager.start_session(identity_fixture.id)


def test_record_event_tracks_event(session_manager):
    """Test that record_event tracks events."""
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)

    event = SessionEvent(
        session_id=context.session_id,
        event_type="test_event",
        description="Test event description",
    )

    manager.record_event(context.session_id, event)

    active_session = manager.get_active_session(context.session_id)
    assert active_session is not None
    assert len(active_session.events) == 1
    assert active_session.events[0].description == "Test event description"


def test_record_key_moment_with_valid_coloring(session_manager):
    """Test that record_key_moment accepts valid emotional coloring."""
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)

    moment = KeyMomentInput(
        what_happened="Something significant happened",
        emotional_valence=0.5,
        emotional_intensity=0.7,
        depth=EmotionalDepth.MEANINGFUL,
        why_it_matters="It matters because...",
        values_touched=["honesty"],
    )

    manager.append_key_moment_input(context.session_id, moment)

    active_session = manager.get_active_session(context.session_id)
    assert active_session is not None
    assert len(active_session.key_moments) == 1
    assert active_session.key_moments[0].what_happened == "Something significant happened"
    assert active_session.key_moments[0].how_i_felt.emotional_valence == 0.5


def test_record_key_moment_without_coloring_requires_incomplete_flag(session_manager):
    """Test that key moment without coloring requires incomplete_coloring flag."""
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)

    # Zero valence and intensity without incomplete_coloring should fail
    moment_no_flag = KeyMomentInput(
        what_happened="Something happened",
        emotional_valence=0.0,
        emotional_intensity=0.0,
        depth=EmotionalDepth.SURFACE,
        why_it_matters="It matters",
        incomplete_coloring=False,  # Explicit False
    )

    with pytest.raises(ValueError, match="no emotional coloring"):
        manager.append_key_moment_input(context.session_id, moment_no_flag)


def test_record_key_moment_with_incomplete_coloring_flag_is_allowed(session_manager):
    """Test that key moment with incomplete_coloring flag is allowed."""
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)

    moment_with_flag = KeyMomentInput(
        what_happened="Something happened but couldn't capture feeling",
        emotional_valence=0.0,
        emotional_intensity=0.0,
        depth=EmotionalDepth.SURFACE,
        why_it_matters="It matters",
        incomplete_coloring=True,  # Explicitly marked as incomplete
    )

    manager.append_key_moment_input(context.session_id, moment_with_flag)

    active_session = manager.get_active_session(context.session_id)
    assert active_session is not None
    assert active_session.incomplete_coloring is True


def test_finish_session_creates_experience_and_eigenstate(session_manager, temp_storage):
    """Test that finish_session creates SessionExperience and Eigenstate."""
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)

    # Record a key moment
    moment = KeyMomentInput(
        what_happened="Session work",
        emotional_valence=0.3,
        emotional_intensity=0.6,
        depth=EmotionalDepth.MEANINGFUL,
        why_it_matters="Learning",
        values_touched=["honesty"],
    )
    manager.append_key_moment_input(context.session_id, moment)

    # Finish session
    result = manager.finish_session(
        session_id=context.session_id,
        overall_emotional_tone=0.3,
        key_insight="Test insight",
        alignment_check=True,
    )

    assert result is not None
    assert result.session_id == context.session_id
    assert len(result.key_moments) == 1
    assert result.overall_emotional_tone == 0.3
    assert result.key_insight == "Test insight"
    assert result.eigenstate is not None
    assert result.eigenstate.session_id == context.session_id

    # Verify experience was stored
    experiences = temp_storage.list_recent_experiences(limit=1)
    assert len(experiences) == 1
    stored_exp = experiences[0].experience
    assert stored_exp.session_id == context.session_id
    assert stored_exp.recorded_by == "session_manager"
    assert len(stored_exp.key_moment_ids) == 1


def test_finish_session_without_key_moments_fails(session_manager):
    """Test that finish_session fails if no key moments recorded."""
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)

    # Try to finish without key moments
    with pytest.raises(ValueError, match="without key moments"):
        manager.finish_session(context.session_id)


def test_stored_experience_matches_recorded_key_moment(session_manager, temp_storage):
    """Stored SessionExperience preserves key moment text and provenance."""
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)

    original_what = "Original event"
    moment = KeyMomentInput(
        what_happened=original_what,
        emotional_valence=0.5,
        emotional_intensity=0.7,
        depth=EmotionalDepth.MEANINGFUL,
        why_it_matters="Testing storage round-trip",
        values_touched=["honesty"],
    )
    manager.append_key_moment_input(context.session_id, moment)

    result = manager.finish_session(
        session_id=context.session_id,
        overall_emotional_tone=0.5,
    )

    experiences = temp_storage.list_recent_experiences(limit=1)
    stored_exp = experiences[0].experience
    stored_moment = temp_storage.get_key_moment(stored_exp.key_moment_ids[0])
    assert stored_moment is not None

    assert result.key_moments[0].what_happened == original_what
    assert stored_moment.what_happened == original_what
    assert stored_exp.recorded_by == "session_manager"


def test_record_event_does_not_mutate_caller_event(session_manager):
    """record_event appends a copy; caller's SessionEvent.session_id is unchanged."""
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)
    wrong_id = uuid4()
    event = SessionEvent(
        session_id=wrong_id,
        event_type="test_event",
        description="Desc",
    )
    manager.record_event(context.session_id, event)
    assert event.session_id == wrong_id
    active = manager.get_active_session(context.session_id)
    assert active is not None
    assert active.events[0].session_id == context.session_id


def test_key_moment_when_uses_recorded_at_before_finish(
    temp_storage, identity_fixture, narrative_fixture
):
    """KeyMoment.when follows Clock time when recorded (temporal consistency)."""
    temp_storage.save_identity(identity_fixture)
    temp_storage.save_narrative(narrative_fixture)

    # Start session with clock at T0
    clock_t0 = FrozenClock(datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC))
    manager_t0 = SessionManager(temp_storage, clock=clock_t0)
    context = manager_t0.start_session(identity_fixture.id)

    # Record key moment at T0
    moment = KeyMomentInput(
        what_happened="Earlier moment",
        emotional_valence=0.1,
        emotional_intensity=0.5,
        depth=EmotionalDepth.SURFACE,
        why_it_matters="Order matters",
    )
    manager_t0.append_key_moment_input(context.session_id, moment)

    # Finish session at T1 (later time) using new clock
    clock_t1 = FrozenClock(datetime(2024, 1, 15, 13, 0, 0, tzinfo=UTC))
    # Transfer active session to new manager with advanced clock
    manager_t1 = SessionManager(temp_storage, clock=clock_t1)
    manager_t1._active_sessions = manager_t0._active_sessions

    result = manager_t1.finish_session(context.session_id)

    # Key moment timestamp should be from T0 (when recorded)
    assert result.key_moments[0].when == clock_t0.now()
    # Finish timestamp should be from T1 (later)
    assert result.finished_at == clock_t1.now()
    assert result.key_moments[0].when < result.finished_at


def test_finish_session_twice_second_raises_not_found(session_manager):
    """After successful finish, session is removed; second finish is SessionNotFoundError."""
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)
    manager.append_key_moment_input(
        context.session_id,
        KeyMomentInput(
            what_happened="x",
            emotional_valence=0.1,
            emotional_intensity=0.2,
            depth=EmotionalDepth.SURFACE,
            why_it_matters="y",
        ),
    )
    manager.finish_session(context.session_id)
    with pytest.raises(SessionNotFoundError):
        manager.finish_session(context.session_id)


def test_concurrent_finish_second_raises_already_finished(session_manager):
    """While first finish holds persistence, second finish sees is_finished and raises."""
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)
    manager.append_key_moment_input(
        context.session_id,
        KeyMomentInput(
            what_happened="x",
            emotional_valence=0.1,
            emotional_intensity=0.2,
            depth=EmotionalDepth.SURFACE,
            why_it_matters="y",
        ),
    )

    started = threading.Event()
    unblock = threading.Event()
    real_create = manager._state_store.create_experience

    def slow_create(rec):  # type: ignore[no-untyped-def]
        started.set()
        assert unblock.wait(timeout=10)
        return real_create(rec)

    errors: list[BaseException] = []

    def run_finish() -> None:
        try:
            manager.finish_session(context.session_id)
        except BaseException as e:
            errors.append(e)

    with patch.object(manager._state_store, "create_experience", side_effect=slow_create):
        t = threading.Thread(target=run_finish)
        t.start()
        assert started.wait(timeout=2)
        with pytest.raises(SessionAlreadyFinishedError):
            manager.finish_session(context.session_id)
        unblock.set()
        t.join(timeout=5)
    assert not errors


def test_alignment_check_false_requires_notes(session_manager):
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)
    manager.append_key_moment_input(
        context.session_id,
        KeyMomentInput(
            what_happened="x",
            emotional_valence=0.1,
            emotional_intensity=0.2,
            depth=EmotionalDepth.SURFACE,
            why_it_matters="y",
        ),
    )
    with pytest.raises(ValueError, match="alignment_notes"):
        manager.finish_session(
            context.session_id,
            alignment_check=False,
            alignment_notes="",
        )
    manager.finish_session(
        context.session_id,
        alignment_check=False,
        alignment_notes="Drift: user pushed beyond stated values.",
    )


def test_max_active_sessions_limit(temp_storage, identity_fixture, narrative_fixture):
    temp_storage.save_identity(identity_fixture)
    temp_storage.save_narrative(narrative_fixture)
    manager = SessionManager(temp_storage, max_active_sessions=1)
    manager.start_session(identity_fixture.id)
    # Check snapshot count (file-based specific check)
    if hasattr(temp_storage, "identity_snapshots_dir"):
        snap_before = len(list(temp_storage.identity_snapshots_dir.glob("*.json")))
    else:
        snap_before = len(temp_storage.list_identity_snapshots(identity_fixture.id))
    with pytest.raises(TooManyActiveSessionsError):
        manager.start_session(identity_fixture.id)
    if hasattr(temp_storage, "identity_snapshots_dir"):
        assert len(list(temp_storage.identity_snapshots_dir.glob("*.json"))) == snap_before
    else:
        assert len(temp_storage.list_identity_snapshots(identity_fixture.id)) == snap_before


def test_overall_emotional_tone_out_of_range_raises(session_manager):
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)
    manager.append_key_moment_input(
        context.session_id,
        KeyMomentInput(
            what_happened="x",
            emotional_valence=0.1,
            emotional_intensity=0.2,
            depth=EmotionalDepth.SURFACE,
            why_it_matters="y",
        ),
    )
    with pytest.raises(ValueError, match="overall_emotional_tone"):
        manager.finish_session(context.session_id, overall_emotional_tone=1.5)


def test_create_eigenstate_empty_key_moments(session_manager):
    manager, _agent_id = session_manager
    sid = uuid4()
    sr = SessionResult(
        session_id=sid,
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        events=[],
        key_moments=[],
        overall_emotional_tone=0.0,
    )
    es = manager._create_eigenstate(sr)
    assert es.emotional_intensity == 0.5
    assert es.cognitive_load == 0.0


def test_valence_zero_with_intensity_allowed_without_incomplete_flag(session_manager):
    """High intensity with neutral valence is allowed (arousal without hedonic tone)."""
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)
    manager.append_key_moment_input(
        context.session_id,
        KeyMomentInput(
            what_happened="Ambiguous affect",
            emotional_valence=0.0,
            emotional_intensity=0.6,
            depth=EmotionalDepth.SURFACE,
            why_it_matters="Still a felt moment",
        ),
    )
    active = manager.get_active_session(context.session_id)
    assert active is not None
    assert active.key_moments[0].how_i_felt.emotional_valence == 0.0
    assert active.key_moments[0].how_i_felt.emotional_intensity == 0.6


def test_list_active_sessions_returns_summaries(session_manager):
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)
    manager.record_event(
        context.session_id,
        SessionEvent(
            session_id=context.session_id,
            event_type="t",
            description="e",
        ),
    )
    summaries = manager.list_active_sessions()
    assert len(summaries) == 1
    s = summaries[0]
    assert isinstance(s, ActiveSessionSummary)
    assert s.session_id == context.session_id
    assert s.events_count == 1
    assert s.key_moments_count == 0


def test_eigenstate_cognitive_load_from_event_count(session_manager):
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)
    for i in range(10):
        manager.record_event(
            context.session_id,
            SessionEvent(
                session_id=context.session_id,
                event_type="user_message",
                description=f"e{i}",
            ),
        )
    manager.append_key_moment_input(
        context.session_id,
        KeyMomentInput(
            what_happened="k",
            emotional_valence=0.2,
            emotional_intensity=0.5,
            depth=EmotionalDepth.SURFACE,
            why_it_matters="r",
        ),
    )
    result = manager.finish_session(context.session_id)
    assert result.eigenstate is not None
    assert result.eigenstate.cognitive_load == 1.0


def test_record_after_finish_raises(session_manager):
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)
    manager.append_key_moment_input(
        context.session_id,
        KeyMomentInput(
            what_happened="x",
            emotional_valence=0.1,
            emotional_intensity=0.2,
            depth=EmotionalDepth.SURFACE,
            why_it_matters="y",
        ),
    )
    real_create = manager._state_store.create_experience
    started = threading.Event()
    unblock = threading.Event()

    def slow_create(rec):  # type: ignore[no-untyped-def]
        started.set()
        assert unblock.wait(timeout=10)
        return real_create(rec)

    with patch.object(manager._state_store, "create_experience", side_effect=slow_create):
        t = threading.Thread(
            target=lambda: manager.finish_session(context.session_id),
        )
        t.start()
        assert started.wait(timeout=2)
        with pytest.raises(SessionAlreadyFinishedError):
            manager.record_event(
                context.session_id,
                SessionEvent(
                    session_id=context.session_id,
                    event_type="t",
                    description="late",
                ),
            )
        unblock.set()
        t.join(timeout=5)


def test_record_key_moment_during_finish_raises(session_manager):
    """Key moments cannot be appended while finish_session is persisting."""
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)
    manager.append_key_moment_input(
        context.session_id,
        KeyMomentInput(
            what_happened="x",
            emotional_valence=0.1,
            emotional_intensity=0.2,
            depth=EmotionalDepth.SURFACE,
            why_it_matters="y",
        ),
    )
    real_create = manager._state_store.create_experience
    started = threading.Event()
    unblock = threading.Event()

    def slow_create(record: ExperienceRecord) -> ExperienceRecord:
        started.set()
        assert unblock.wait(timeout=10)
        return real_create(record)

    late_moment = KeyMomentInput(
        what_happened="late",
        emotional_valence=0.2,
        emotional_intensity=0.3,
        depth=EmotionalDepth.SURFACE,
        why_it_matters="should be rejected",
    )

    with patch.object(manager._state_store, "create_experience", side_effect=slow_create):
        t = threading.Thread(target=lambda: manager.finish_session(context.session_id))
        t.start()
        assert started.wait(timeout=2)
        with pytest.raises(SessionAlreadyFinishedError):
            manager.append_key_moment_input(context.session_id, late_moment)
        unblock.set()
        t.join(timeout=5)


def test_resource_warning_can_be_recorded_as_key_moment(session_manager):
    """Test that resource/token warnings can be recorded as key moments."""
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)

    # Record resource warning as key moment
    warning_moment = KeyMomentInput(
        what_happened="Approaching token limit - need to wrap up session",
        emotional_valence=-0.2,
        emotional_intensity=0.4,
        depth=EmotionalDepth.SURFACE,
        why_it_matters="Resource constraints affect quality of work",
        values_touched=["competence"],
        what_changed="Learned to monitor resources during session",
    )

    manager.append_key_moment_input(context.session_id, warning_moment)

    active_session = manager.get_active_session(context.session_id)
    assert active_session is not None
    assert len(active_session.key_moments) == 1
    assert "token limit" in active_session.key_moments[0].what_happened


def test_session_not_found_errors(session_manager):
    """Test that operations on non-existent session raise SessionNotFoundError."""
    manager, _ = session_manager
    fake_session_id = uuid4()

    event = SessionEvent(
        session_id=fake_session_id,
        event_type="test",
        description="test",
    )

    with pytest.raises(SessionNotFoundError):
        manager.record_event(fake_session_id, event)

    moment = KeyMomentInput(
        what_happened="test",
        emotional_valence=0.5,
        emotional_intensity=0.5,
        depth=EmotionalDepth.SURFACE,
        why_it_matters="test",
    )

    with pytest.raises(SessionNotFoundError):
        manager.append_key_moment_input(fake_session_id, moment)

    with pytest.raises(SessionNotFoundError):
        manager.finish_session(fake_session_id)


def test_multiple_key_moments_in_session(session_manager):
    """Test recording multiple key moments in one session."""
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)

    moments = [
        KeyMomentInput(
            what_happened=f"Event {i}",
            emotional_valence=0.1 * i,
            emotional_intensity=0.5,
            depth=EmotionalDepth.SURFACE,
            why_it_matters=f"Reason {i}",
        )
        for i in range(1, 4)
    ]

    for moment in moments:
        manager.append_key_moment_input(context.session_id, moment)

    result = manager.finish_session(context.session_id)

    assert len(result.key_moments) == 3
    assert result.key_moments[0].what_happened == "Event 1"
    assert result.key_moments[1].what_happened == "Event 2"
    assert result.key_moments[2].what_happened == "Event 3"


def test_eigenstate_captures_session_state(session_manager):
    """Test that eigenstate captures key session information."""
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)

    # Record moment with values
    moment = KeyMomentInput(
        what_happened="Complex work",
        emotional_valence=0.4,
        emotional_intensity=0.8,
        depth=EmotionalDepth.PROFOUND,
        why_it_matters="Deep learning",
        values_touched=["honesty", "competence"],
        principles_questioned=["always_be_certain"],
    )
    manager.append_key_moment_input(context.session_id, moment)

    result = manager.finish_session(
        session_id=context.session_id,
        overall_emotional_tone=0.4,
        key_insight="Deep insight",
    )

    eigenstate = result.eigenstate
    assert eigenstate is not None
    assert eigenstate.emotional_tone == 0.4
    assert eigenstate.emotional_intensity == 0.8  # From key moment
    assert eigenstate.session_summary == "Deep insight"
    assert "honesty" in eigenstate.dominant_themes or "competence" in eigenstate.dominant_themes
    assert "always_be_certain" in eigenstate.unresolved_tensions


def test_finish_session_storage_failure_allows_retry(session_manager, temp_storage):
    """Test that storage failure leaves session in retryable state."""
    manager, agent_id = session_manager

    context = manager.start_session(agent_id)

    # Record a key moment
    moment = KeyMomentInput(
        what_happened="Test event",
        emotional_valence=0.5,
        emotional_intensity=0.5,
        depth=EmotionalDepth.SURFACE,
        why_it_matters="Testing persistence order",
    )
    manager.append_key_moment_input(context.session_id, moment)

    # Mock create_experience to fail
    def failing_create_experience(record):
        raise RuntimeError("Storage failure simulation")

    with (
        patch.object(temp_storage, "create_experience", side_effect=failing_create_experience),
        pytest.raises(RuntimeError, match="Storage failure"),
    ):
        # Try to finish session - should fail during persistence
        manager.finish_session(context.session_id)

    # Session should still be active and NOT marked as finished
    active_session = manager.get_active_session(context.session_id)
    assert active_session is not None
    assert active_session.is_finished is False

    # Restore original method and retry - should succeed
    result = manager.finish_session(context.session_id)
    assert result.is_finished is True

    # Session should be removed from active sessions
    assert manager.get_active_session(context.session_id) is None

    # Verify experience was stored
    experiences = temp_storage.list_recent_experiences(limit=1)
    assert len(experiences) == 1
    assert experiences[0].experience.session_id == context.session_id


def test_session_experience_has_identity_snapshot_provenance(session_manager, temp_storage):
    """Test that SessionExperience is linked to identity snapshot for provenance."""
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)

    # Context should have identity_snapshot_id
    assert context.identity_snapshot_id is not None

    # Record a key moment
    moment = KeyMomentInput(
        what_happened="Test provenance",
        emotional_valence=0.5,
        emotional_intensity=0.5,
        depth=EmotionalDepth.SURFACE,
        why_it_matters="Testing identity snapshot linkage",
    )
    manager.append_key_moment_input(context.session_id, moment)

    # Finish session
    result = manager.finish_session(context.session_id)

    # Result should have identity_snapshot_id
    assert result.identity_snapshot_id is not None
    assert result.identity_snapshot_id == context.identity_snapshot_id

    # Stored experience should have identity_snapshot_id
    experiences = temp_storage.list_recent_experiences(limit=1)
    assert len(experiences) == 1
    stored_exp = experiences[0].experience
    assert stored_exp.identity_snapshot_id is not None
    assert stored_exp.identity_snapshot_id == context.identity_snapshot_id

    # Verify snapshot exists in storage
    snapshots = temp_storage.list_identity_snapshots(agent_id, limit=1)
    assert len(snapshots) == 1
    assert snapshots[0].id == context.identity_snapshot_id
    assert snapshots[0].identity_snapshot.id == agent_id


def test_finish_session_updates_recent_narrative(session_manager, temp_storage):
    """Test that finish_session updates recent narrative layer."""
    manager, agent_id = session_manager

    # Start first session
    context1 = manager.start_session(agent_id)

    # Record key moment with specific values
    moment = KeyMomentInput(
        what_happened="Implemented a complex feature",
        emotional_valence=0.7,
        emotional_intensity=0.8,
        depth=EmotionalDepth.MEANINGFUL,
        why_it_matters="Demonstrated technical competence",
        values_touched=["competence", "growth"],
    )
    manager.append_key_moment_input(context1.session_id, moment)

    # Get narrative before finish
    narrative_before = temp_storage.load_narrative(agent_id)
    assert narrative_before is not None
    recent_content_before = narrative_before.recent_layer.content

    # Finish session with key insight
    manager.finish_session(
        session_id=context1.session_id,
        overall_emotional_tone=0.6,
        key_insight="Successfully delivered complex work through careful planning",
    )

    # Get narrative after finish
    narrative_after = temp_storage.load_narrative(agent_id)
    assert narrative_after is not None
    recent_content_after = narrative_after.recent_layer.content

    # Recent layer should be updated
    assert recent_content_after != recent_content_before
    assert recent_content_before in recent_content_after
    assert "Successfully delivered complex work" in recent_content_after
    assert "competence" in recent_content_after or "growth" in recent_content_after
    assert "positive" in recent_content_after  # Overall tone was 0.6

    # Start second session - should load updated narrative
    context2 = manager.start_session(agent_id)
    assert context2.narrative.recent_layer.content == recent_content_after
    assert "Successfully delivered complex work" in context2.narrative.recent_layer.content


def test_finish_session_appends_to_recent_narrative_without_erasing_existing_context(
    session_manager, temp_storage
):
    """Session finish must not discard recent narrative context from earlier lifecycle steps."""
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)
    existing_context = "Recent narrative"

    manager.append_key_moment_input(
        context.session_id,
        KeyMomentInput(
            what_happened="Preserve narrative context",
            emotional_valence=0.4,
            emotional_intensity=0.5,
            depth=EmotionalDepth.MEANINGFUL,
            why_it_matters="Losing this layer loses continuity",
            values_touched=["continuity"],
        ),
    )

    manager.finish_session(
        session_id=context.session_id,
        overall_emotional_tone=0.4,
        key_insight="Added new session summary",
    )

    narrative_after = temp_storage.load_narrative(agent_id)
    assert narrative_after is not None
    recent_content_after = narrative_after.recent_layer.content

    assert existing_context in recent_content_after
    assert "Added new session summary" in recent_content_after
    assert recent_content_after.index(existing_context) < recent_content_after.index(
        "Added new session summary"
    )


def test_get_active_session_returns_detached_snapshot(session_manager):
    """Mutations on the returned SessionResult must not affect the live registry."""
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)
    active1 = manager.get_active_session(context.session_id)
    assert active1 is not None
    manager.record_event(
        context.session_id,
        SessionEvent(
            session_id=context.session_id,
            event_type="t",
            description="after snapshot",
        ),
    )
    active2 = manager.get_active_session(context.session_id)
    assert len(active2.events) == 1
    assert len(active1.events) == 0


def test_finish_session_retry_skips_duplicate_narrative_after_post_narrative_failure(
    session_manager, temp_storage
):
    """If narrative persisted then a simulated failure fires, retry must not append twice."""
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)
    manager.append_key_moment_input(
        context.session_id,
        KeyMomentInput(
            what_happened="narrative idempotency",
            emotional_valence=0.2,
            emotional_intensity=0.3,
            depth=EmotionalDepth.SURFACE,
            why_it_matters="x",
            values_touched=["honesty"],
        ),
    )
    insight = "Unique insight for idempotent narrative retry"
    real_save = manager._save_session_narrative_update
    first = {"done": False}

    def flaky_save(sr: SessionResult) -> None:
        real_save(sr)
        if not first["done"]:
            first["done"] = True
            raise RuntimeError("post-narrative failure")

    with (
        patch.object(manager, "_save_session_narrative_update", side_effect=flaky_save),
        pytest.raises(RuntimeError, match="post-narrative"),
    ):
        manager.finish_session(context.session_id, key_insight=insight)

    assert manager.get_active_session(context.session_id) is not None
    manager.finish_session(context.session_id, key_insight=insight)

    narrative = temp_storage.load_narrative(agent_id)
    assert narrative is not None
    assert narrative.recent_layer.content.count(insight) == 1


def test_finish_session_retries_narrative_updated_at_conflict(session_manager, temp_storage):
    """A transient optimistic-lock conflict should be retried before failing the finish."""
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)
    manager.append_key_moment_input(
        context.session_id,
        KeyMomentInput(
            what_happened="optimistic lock retry",
            emotional_valence=0.2,
            emotional_intensity=0.3,
            depth=EmotionalDepth.SURFACE,
            why_it_matters="narrative retry",
            values_touched=["continuity"],
        ),
    )
    real_save_narrative = temp_storage.save_narrative
    fail_once = {"value": True}

    def flaky_save_narrative(
        narrative: NarrativeDocument,
        expected_updated_at: datetime | None = None,
    ) -> NarrativeDocument:
        if fail_once["value"]:
            fail_once["value"] = False
            raise ValueError(
                "Narrative updated_at mismatch: expected old, got new (concurrent update detected)"
            )
        return real_save_narrative(narrative, expected_updated_at=expected_updated_at)

    insight = "Retry narrative after optimistic lock conflict"
    with patch.object(temp_storage, "save_narrative", side_effect=flaky_save_narrative) as save:
        result = manager.finish_session(context.session_id, key_insight=insight)

    assert result.is_finished is True
    assert save.call_count == 2
    narrative = temp_storage.load_narrative(agent_id)
    assert narrative is not None
    assert narrative.recent_layer.content.count(insight) == 1


def test_finish_session_missing_narrative_rolls_back_for_retry(session_manager, temp_storage):
    """If narrative disappears after partial persistence, the live session stays retryable."""
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)
    manager.append_key_moment_input(
        context.session_id,
        KeyMomentInput(
            what_happened="missing narrative",
            emotional_valence=0.2,
            emotional_intensity=0.3,
            depth=EmotionalDepth.SURFACE,
            why_it_matters="partial persistence must be retryable",
        ),
    )

    with (
        patch.object(temp_storage, "load_narrative", return_value=None),
        pytest.raises(RuntimeError, match="Narrative disappeared"),
    ):
        manager.finish_session(context.session_id)

    active = manager.get_active_session(context.session_id)
    assert active is not None
    assert active.is_finished is False


def test_finish_session_retry_after_eigenstate_failure_does_not_duplicate_experience(
    session_manager, temp_storage
):
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)
    manager.append_key_moment_input(
        context.session_id,
        KeyMomentInput(
            what_happened="partial persist",
            emotional_valence=0.2,
            emotional_intensity=0.3,
            depth=EmotionalDepth.SURFACE,
            why_it_matters="idempotency",
        ),
    )
    real_save = temp_storage.save_eigenstate
    fail = {"once": True}

    def flaky_save(es):  # type: ignore[no-untyped-def]
        if fail["once"]:
            fail["once"] = False
            raise RuntimeError("eigenstate failed")
        return real_save(es)

    with (
        patch.object(temp_storage, "save_eigenstate", side_effect=flaky_save),
        pytest.raises(RuntimeError, match="eigenstate failed"),
    ):
        manager.finish_session(context.session_id)

    assert manager.get_active_session(context.session_id) is not None
    manager.finish_session(context.session_id)

    rows = temp_storage.search_experiences(SessionExperienceQuery(context.session_id), limit=10)
    assert len(rows) == 1
    assert rows[0].experience.id == deterministic_session_experience_id(context.session_id)


def test_finish_session_rejects_conflicting_deterministic_experience_id(
    session_manager, temp_storage, frozen_clock
):
    """The deterministic retry id must never attach a session to another session's record."""
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)
    moment = KeyMomentInput(
        what_happened="id conflict",
        emotional_valence=0.2,
        emotional_intensity=0.3,
        depth=EmotionalDepth.SURFACE,
        why_it_matters="stored experience identity must match",
    )
    manager.append_key_moment_input(context.session_id, moment)

    km_conflict = moment.to_key_moment()
    conflicting_record = ExperienceRecord(
        experience=SessionExperience(
            id=deterministic_session_experience_id(context.session_id),
            session_id=uuid4(),
            timestamp=frozen_clock.now(),
            key_moment_ids=[km_conflict.id],
            avg_emotional_intensity=km_conflict.how_i_felt.emotional_intensity,
            has_profound_moment=km_conflict.how_i_felt.depth == EmotionalDepth.PROFOUND,
        )
    )
    temp_storage.create_experience(conflicting_record)
    temp_storage.store_key_moments(conflicting_record.experience.session_id, [km_conflict])

    with pytest.raises(ValueError, match="belongs to another session"):
        manager.finish_session(context.session_id)

    active = manager.get_active_session(context.session_id)
    assert active is not None
    assert active.is_finished is False


def test_start_session_ignores_eigenstate_from_different_identity(tmp_path):
    """Same workspace file layout after switching identity must not leak prior eigenstate."""
    from atman.adapters.storage.file_state_store import FileStateStore

    store = FileStateStore(tmp_path / "st")
    id_a = uuid4()
    id_b = uuid4()
    id_a_obj = Identity(
        id=id_a,
        self_description="A",
        core_values=[
            CoreValue(name="v", description="d", confidence=0.5),
        ],
        goals=[Goal(content="g", horizon=GoalHorizon.SHORT)],
        emotional_baseline=0.0,
    )
    na = NarrativeDocument(
        identity_id=id_a,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="ca"),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="ra"),
    )
    store.save_identity(id_a_obj)
    store.save_narrative(na)
    es = Eigenstate(
        session_id=uuid4(),
        identity_id=id_a,
        emotional_tone=0.1,
        emotional_intensity=0.2,
        cognitive_load=0.1,
        open_threads=[],
        dominant_themes=["t"],
        unresolved_tensions=[],
        session_summary="s",
        key_insight="k",
    )
    store.save_eigenstate(es)

    id_b_obj = Identity(
        id=id_b,
        self_description="B",
        core_values=[
            CoreValue(name="v", description="d", confidence=0.5),
        ],
        goals=[Goal(content="g", horizon=GoalHorizon.SHORT)],
        emotional_baseline=0.0,
    )
    nb = NarrativeDocument(
        identity_id=id_b,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="cb"),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="rb"),
    )
    store.save_identity(id_b_obj)
    store.save_narrative(nb)

    mgr = SessionManager(store)
    ctx = mgr.start_session(id_b)
    assert ctx.last_eigenstate is None


# NOTE: Domain invariant tests (test_unexamined_invariant_*) moved to test_domain_invariants.py
# per AGENTS.md convention for cross-cutting invariants (§26.5).


# Key moment separation tests


def test_key_moment_separation_distinct_from_events(session_manager):
    """Key moments are a separate dimension from events - not derived from events."""
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)

    # Record event with similar content
    manager.record_event(
        context.session_id,
        SessionEvent(
            session_id=context.session_id,
            event_type="task",
            description="Task completed successfully",
        ),
    )

    # Record key moment with similar content
    manager.append_key_moment_input(
        context.session_id,
        KeyMomentInput(
            what_happened="Task completed successfully",
            emotional_valence=0.7,
            emotional_intensity=0.6,
            depth=EmotionalDepth.MEANINGFUL,
            why_it_matters="First successful task",
        ),
    )

    active = manager.get_active_session(context.session_id)
    assert active is not None
    # Both structures coexist independently
    assert len(active.events) == 1
    assert len(active.key_moments) == 1
    # But they're distinct objects
    assert active.events[0].description == "Task completed successfully"
    assert active.key_moments[0].what_happened == "Task completed successfully"


# Immutability tests


def test_key_moment_immutability_after_append(session_manager):
    """Once appended, key moments cannot be modified via external references."""
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)

    original_what = "Original content"
    moment_input = KeyMomentInput(
        what_happened=original_what,
        emotional_valence=0.5,
        emotional_intensity=0.5,
        depth=EmotionalDepth.SURFACE,
        why_it_matters="Immutability test",
    )

    manager.append_key_moment_input(context.session_id, moment_input)

    # Mutate the input after appending
    moment_input.what_happened = "Modified content"

    # Stored moment should be unchanged
    active = manager.get_active_session(context.session_id)
    assert active is not None
    assert active.key_moments[0].what_happened == original_what


# Journal lifecycle tests


def test_journal_lifecycle_events_survive_session_completion(session_manager, temp_storage):
    """Events recorded during session are preserved through finish_session."""
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)

    # Record events
    event_descriptions = ["Event A", "Event B", "Event C"]
    for desc in event_descriptions:
        manager.record_event(
            context.session_id,
            SessionEvent(
                session_id=context.session_id,
                event_type="journal_entry",
                description=desc,
            ),
        )

    # Add key moment (required for finish)
    manager.append_key_moment_input(
        context.session_id,
        KeyMomentInput(
            what_happened="Key event",
            emotional_valence=0.5,
            emotional_intensity=0.5,
            depth=EmotionalDepth.SURFACE,
            why_it_matters="Required for finish",
        ),
    )

    result = manager.finish_session(context.session_id)

    # Events should be preserved in result
    assert len(result.events) == 3
    assert [e.description for e in result.events] == event_descriptions


def test_journal_lifecycle_event_timestamps_are_immutable(
    temp_storage, identity_fixture, narrative_fixture
):
    """Event timestamps must not change when recorded at different clock times."""
    temp_storage.save_identity(identity_fixture)
    temp_storage.save_narrative(narrative_fixture)

    clock_t0 = FrozenClock(datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC))
    manager = SessionManager(temp_storage, clock=clock_t0)
    context = manager.start_session(identity_fixture.id)

    # Record event at T0
    event_t0 = SessionEvent(
        session_id=context.session_id,
        event_type="test",
        description="Event at T0",
        timestamp=clock_t0.now(),
    )
    manager.record_event(context.session_id, event_t0)

    # Record another event - timestamp from event should be preserved
    active = manager.get_active_session(context.session_id)
    assert active is not None
    assert active.events[0].timestamp == datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)


# Orphan recovery tests


def test_orphan_recovery_finish_idempotent_after_experience_persisted(
    session_manager, temp_storage
):
    """If experience persisted but eigenstate failed, retry must skip experience creation."""
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)

    manager.append_key_moment_input(
        context.session_id,
        KeyMomentInput(
            what_happened="orphan recovery test",
            emotional_valence=0.3,
            emotional_intensity=0.4,
            depth=EmotionalDepth.SURFACE,
            why_it_matters="idempotency",
        ),
    )

    # First finish attempt fails after experience creation
    real_save_eigenstate = temp_storage.save_eigenstate
    first_call = {"done": False}

    def fail_eigenstate_once(es: Eigenstate) -> Eigenstate:
        if not first_call["done"]:
            first_call["done"] = True
            # Experience is already created at this point
            raise RuntimeError("Simulated eigenstate failure")
        return real_save_eigenstate(es)

    with (
        patch.object(temp_storage, "save_eigenstate", side_effect=fail_eigenstate_once),
        pytest.raises(RuntimeError, match="Simulated eigenstate failure"),
    ):
        manager.finish_session(context.session_id)

    # Session should still be active for retry
    assert manager.get_active_session(context.session_id) is not None

    # Retry should succeed without duplicating experience
    result = manager.finish_session(context.session_id)
    assert result.eigenstate is not None

    # Only one experience should exist
    from atman.core.ports.state_store import SessionExperienceQuery

    rows = temp_storage.search_experiences(SessionExperienceQuery(context.session_id), limit=10)
    assert len(rows) == 1


def test_orphan_recovery_deterministic_id_prevents_cross_session_pollution(
    temp_storage, identity_fixture, narrative_fixture, frozen_clock
):
    """Deterministic experience ID must prevent one session from hijacking another's record."""
    temp_storage.save_identity(identity_fixture)
    temp_storage.save_narrative(narrative_fixture)
    manager = SessionManager(temp_storage, clock=frozen_clock)

    # Start first session and create orphaned experience record
    context1 = manager.start_session(identity_fixture.id)
    moment1 = KeyMomentInput(
        what_happened="Session 1 event",
        emotional_valence=0.3,
        emotional_intensity=0.4,
        depth=EmotionalDepth.SURFACE,
        why_it_matters="Session 1",
    )
    km1 = moment1.to_key_moment()

    # Manually create orphaned experience for session 1
    orphaned_exp_id = deterministic_session_experience_id(context1.session_id)
    orphan_record = ExperienceRecord(
        experience=SessionExperience(
            id=orphaned_exp_id,
            session_id=context1.session_id,
            timestamp=frozen_clock.now(),
            key_moment_ids=[km1.id],
            avg_emotional_intensity=0.4,
            has_profound_moment=False,
        )
    )
    temp_storage.create_experience(orphan_record)

    # Start second session
    context2 = manager.start_session(identity_fixture.id)
    manager.append_key_moment_input(
        context2.session_id,
        KeyMomentInput(
            what_happened="Session 2 event",
            emotional_valence=0.5,
            emotional_intensity=0.6,
            depth=EmotionalDepth.SURFACE,
            why_it_matters="Session 2",
        ),
    )

    # Session 2 finish should succeed with its own unique ID
    manager.finish_session(context2.session_id)
    exp_id_2 = deterministic_session_experience_id(context2.session_id)

    # IDs must be different
    assert exp_id_2 != orphaned_exp_id

    # Both experiences should exist independently
    from atman.core.ports.state_store import SessionExperienceQuery

    exp1_records = temp_storage.search_experiences(
        SessionExperienceQuery(context1.session_id), limit=10
    )
    exp2_records = temp_storage.search_experiences(
        SessionExperienceQuery(context2.session_id), limit=10
    )

    assert len(exp1_records) == 1
    assert len(exp2_records) == 1
    assert exp1_records[0].experience.session_id == context1.session_id
    assert exp2_records[0].experience.session_id == context2.session_id

def test_journal_created_on_key_moment(tmp_path, identity_fixture, narrative_fixture, frozen_clock):
    """Test that journal is created when key moment is appended."""
    store = InMemoryStateStore()
    store.save_identity(identity_fixture)
    store.save_narrative(narrative_fixture)

    workspace = tmp_path / "journal_workspace"
    manager = SessionManager(store, clock=frozen_clock, workspace=workspace)
    context = manager.start_session(identity_fixture.id)

    moment = KeyMomentInput(
        what_happened="Test event",
        emotional_valence=0.5,
        emotional_intensity=0.7,
        depth=EmotionalDepth.MEANINGFUL,
        why_it_matters="Testing journal",
    )
    manager.append_key_moment_input(context.session_id, moment)

    # Check journal exists
    journal_path = (
        workspace / str(identity_fixture.id) / "sessions" / f"active_{context.session_id}.jsonl"
    )
    assert journal_path.exists()

    # Parse journal and verify entry
    with journal_path.open("r") as f:
        lines = f.readlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["type"] == "key_moment"
        assert entry["what_happened"] == "Test event"


def test_journal_records_facts_read(tmp_path, identity_fixture, narrative_fixture, frozen_clock):
    """Test that journal records facts read during session."""
    store = InMemoryStateStore()
    store.save_identity(identity_fixture)
    store.save_narrative(narrative_fixture)

    workspace = tmp_path / "journal_workspace"
    manager = SessionManager(store, clock=frozen_clock, workspace=workspace)
    context = manager.start_session(identity_fixture.id)

    fact_ids = [uuid4(), uuid4()]
    manager._note_facts_read(context.session_id, fact_ids)

    # Check journal exists
    journal_path = (
        workspace / str(identity_fixture.id) / "sessions" / f"active_{context.session_id}.jsonl"
    )
    assert journal_path.exists()

    # Parse journal and verify entry
    with journal_path.open("r") as f:
        lines = f.readlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["type"] == "facts_read"
        assert len(entry["fact_ids"]) == 2


def test_journal_deleted_on_finish(tmp_path, identity_fixture, narrative_fixture, frozen_clock):
    """Test that journal is deleted after successful finish_session."""
    store = InMemoryStateStore()
    store.save_identity(identity_fixture)
    store.save_narrative(narrative_fixture)

    workspace = tmp_path / "journal_workspace"
    manager = SessionManager(store, clock=frozen_clock, workspace=workspace)
    context = manager.start_session(identity_fixture.id)

    moment = KeyMomentInput(
        what_happened="Test event",
        emotional_valence=0.5,
        emotional_intensity=0.7,
        depth=EmotionalDepth.MEANINGFUL,
        why_it_matters="Testing journal deletion",
    )
    manager.append_key_moment_input(context.session_id, moment)

    journal_path = (
        workspace / str(identity_fixture.id) / "sessions" / f"active_{context.session_id}.jsonl"
    )
    assert journal_path.exists()

    # Finish session
    manager.finish_session(context.session_id)

    # Journal should be deleted
    assert not journal_path.exists()


def test_orphan_recovery_on_start_session(
    tmp_path, identity_fixture, narrative_fixture, frozen_clock
):
    """Test that orphaned journals are recovered on start_session."""
    store = InMemoryStateStore()
    store.save_identity(identity_fixture)
    store.save_narrative(narrative_fixture)

    workspace = tmp_path / "orphan_workspace"
    manager = SessionManager(store, clock=frozen_clock, workspace=workspace)

    # Create an orphaned journal manually
    orphan_session_id = uuid4()
    sessions_dir = workspace / str(identity_fixture.id) / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    orphan_journal = sessions_dir / f"active_{orphan_session_id}.jsonl"

    # Write key moments to orphan journal
    moment_id = uuid4()
    with orphan_journal.open("w") as f:
        json.dump(
            {
                "type": "key_moment",
                "moment_id": str(moment_id),
                "timestamp": frozen_clock.now().isoformat(),
                "what_happened": "Orphaned moment",
                "fact_refs": [],
            },
            f,
        )
        f.write("\n")

    # Store the key moment in storage so recovery can find it
    from atman.core.models.experience import FeltSense, KeyMoment

    key_moment = KeyMoment(
        id=moment_id,
        what_happened="Orphaned moment",
        how_i_felt=FeltSense(
            emotional_valence=0.5,
            emotional_intensity=0.5,
            depth=EmotionalDepth.SURFACE,
        ),
        why_it_matters="Orphaned",
        when=frozen_clock.now(),
        values_touched=[],
        principles_questioned=[],
        fact_refs=[],
    )
    store.store_key_moments(orphan_session_id, [key_moment])

    assert orphan_journal.exists()

    # Start a new session - should trigger orphan recovery
    manager.start_session(identity_fixture.id)

    # Orphan journal should be deleted
    assert not orphan_journal.exists()

    # SessionExperience should be created
    experience_id = deterministic_session_experience_id(orphan_session_id)
    recovered_exp = store.get_experience(experience_id)
    assert recovered_exp is not None
    assert recovered_exp.experience.session_id == orphan_session_id
    assert recovered_exp.experience.close_reason == "interrupted"
    assert recovered_exp.experience.incomplete_coloring is True
    assert len(recovered_exp.experience.key_moment_ids) == 1


def test_orphan_recovery_skips_existing_experiences(
    tmp_path, identity_fixture, narrative_fixture, frozen_clock
):
    """Test that orphan recovery skips sessions that already have stored experiences."""
    store = InMemoryStateStore()
    store.save_identity(identity_fixture)
    store.save_narrative(narrative_fixture)

    workspace = tmp_path / "orphan_skip_workspace"
    manager = SessionManager(store, clock=frozen_clock, workspace=workspace)

    # Create orphaned journal
    orphan_session_id = uuid4()
    sessions_dir = workspace / str(identity_fixture.id) / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    orphan_journal = sessions_dir / f"active_{orphan_session_id}.jsonl"

    moment_id = uuid4()
    with orphan_journal.open("w") as f:
        json.dump(
            {
                "type": "key_moment",
                "moment_id": str(moment_id),
                "timestamp": frozen_clock.now().isoformat(),
                "what_happened": "Already saved",
                "fact_refs": [],
            },
            f,
        )
        f.write("\n")

    # Pre-create the experience in storage
    experience_id = deterministic_session_experience_id(orphan_session_id)
    experience = SessionExperience(
        id=experience_id,
        session_id=orphan_session_id,
        timestamp=frozen_clock.now(),
        key_moment_ids=[moment_id],
        recorded_by="test",
        importance=0.5,
        salience=0.5,
    )
    store.create_experience(ExperienceRecord(experience=experience))

    # Start new session - should skip recovery and just delete journal
    manager.start_session(identity_fixture.id)

    # Journal should be deleted
    assert not orphan_journal.exists()

    # Experience should still exist (not duplicated)
    recovered_exp = store.get_experience(experience_id)
    assert recovered_exp is not None
    assert recovered_exp.experience.recorded_by == "test"  # Original, not recovered


def test_orphan_recovery_handles_malformed_journal(
    tmp_path, identity_fixture, narrative_fixture, frozen_clock
):
    """Test that orphan recovery handles malformed JSON lines gracefully."""
    store = InMemoryStateStore()
    store.save_identity(identity_fixture)
    store.save_narrative(narrative_fixture)

    workspace = tmp_path / "malformed_workspace"
    manager = SessionManager(store, clock=frozen_clock, workspace=workspace)

    orphan_session_id = uuid4()
    sessions_dir = workspace / str(identity_fixture.id) / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    orphan_journal = sessions_dir / f"active_{orphan_session_id}.jsonl"

    # Write mix of valid and invalid lines
    with orphan_journal.open("w") as f:
        f.write("invalid json\n")
        f.write("{}\n")  # Missing required fields
        json.dump(
            {
                "type": "key_moment",
                "moment_id": str(uuid4()),
                "timestamp": frozen_clock.now().isoformat(),
                "what_happened": "Valid moment",
                "fact_refs": [],
            },
            f,
        )
        f.write("\n")

    # Should not raise - just skip bad lines
    manager.start_session(identity_fixture.id)

    # Journal should still be deleted
    assert not orphan_journal.exists()


def test_journal_not_created_without_workspace(identity_fixture, narrative_fixture, frozen_clock):
    """Test that journal is not created when workspace is not configured."""
    store = InMemoryStateStore()
    store.save_identity(identity_fixture)
    store.save_narrative(narrative_fixture)

    # No workspace parameter
    manager = SessionManager(store, clock=frozen_clock)
    context = manager.start_session(identity_fixture.id)

    moment = KeyMomentInput(
        what_happened="Test event",
        emotional_valence=0.5,
        emotional_intensity=0.7,
        depth=EmotionalDepth.MEANINGFUL,
        why_it_matters="No journal",
    )
    manager.append_key_moment_input(context.session_id, moment)

    # Should not raise - journal operations should be no-op
    manager.finish_session(context.session_id)


def test_orphan_recovery_skips_currently_active_sessions(
    tmp_path, identity_fixture, narrative_fixture, frozen_clock
):
    """Test that orphan recovery skips journals for currently active sessions."""
    store = InMemoryStateStore()
    store.save_identity(identity_fixture)
    store.save_narrative(narrative_fixture)

    workspace = tmp_path / "active_skip_workspace"
    manager = SessionManager(store, clock=frozen_clock, workspace=workspace)

    # Start session A
    context_a = manager.start_session(identity_fixture.id)

    # Record key moment for session A
    moment = KeyMomentInput(
        what_happened="Active session moment",
        emotional_valence=0.5,
        emotional_intensity=0.7,
        depth=EmotionalDepth.MEANINGFUL,
        why_it_matters="Testing active skip",
    )
    manager.append_key_moment_input(context_a.session_id, moment)

    # Journal should exist for session A
    journal_path_a = (
        workspace / str(identity_fixture.id) / "sessions" / f"active_{context_a.session_id}.jsonl"
    )
    assert journal_path_a.exists()

    # Start session B - recovery should skip session A's journal (it's active)
    _ = manager.start_session(identity_fixture.id)

    # Session A's journal should still exist (not treated as orphan)
    assert journal_path_a.exists()

    # SessionExperience should NOT exist yet for session A
    experience_id_a = deterministic_session_experience_id(context_a.session_id)
    recovered_exp = store.get_experience(experience_id_a)
    assert recovered_exp is None

    # Finish session A properly
    manager.finish_session(context_a.session_id, close_reason="timeout_sleep")

    # Now experience should exist with correct close_reason
    final_exp = store.get_experience(experience_id_a)
    assert final_exp is not None
    assert final_exp.experience.close_reason == "timeout_sleep"  # Not "interrupted"
    assert final_exp.experience.recorded_by == "session_manager"  # Not "session_manager_recovery"


def test_append_key_moment_writes_journal_for_affect_detector(
    tmp_path, identity_fixture, narrative_fixture, frozen_clock
):
    """Test that append_key_moment (used by AffectDetector) writes journal entries."""
    store = InMemoryStateStore()
    store.save_identity(identity_fixture)
    store.save_narrative(narrative_fixture)

    workspace = tmp_path / "affect_journal_workspace"
    manager = SessionManager(store, clock=frozen_clock, workspace=workspace)
    context = manager.start_session(identity_fixture.id)

    # Create a KeyMoment directly (as AffectDetector would)
    from atman.core.models.experience import FeltSense, KeyMoment

    moment = KeyMoment(
        what_happened="Affect-detected moment",
        how_i_felt=FeltSense(
            emotional_valence=0.6,
            emotional_intensity=0.8,
            depth=EmotionalDepth.MEANINGFUL,
        ),
        why_it_matters="Detected by affect system",
        when=frozen_clock.now(),
        values_touched=["curiosity"],
        principles_questioned=[],
        fact_refs=[],
    )

    # Use append_key_moment (AffectDetector path)
    manager.append_key_moment(context.session_id, moment)

    # Check journal exists and has entry
    journal_path = (
        workspace / str(identity_fixture.id) / "sessions" / f"active_{context.session_id}.jsonl"
    )
    assert journal_path.exists()

    with journal_path.open("r") as f:
        lines = f.readlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["type"] == "key_moment"
        assert entry["what_happened"] == "Affect-detected moment"


def test_orphan_recovery_loads_key_moments_from_storage(
    tmp_path, identity_fixture, narrative_fixture, frozen_clock
):
    """Test that orphan recovery loads KeyMoment objects from storage for better metadata."""
    store = InMemoryStateStore()
    store.save_identity(identity_fixture)
    store.save_narrative(narrative_fixture)

    workspace = tmp_path / "recovery_metadata_workspace"
    manager = SessionManager(store, clock=frozen_clock, workspace=workspace)

    # Create orphaned journal
    orphan_session_id = uuid4()
    sessions_dir = workspace / str(identity_fixture.id) / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    orphan_journal = sessions_dir / f"active_{orphan_session_id}.jsonl"

    # Create a key moment with profound depth
    from atman.core.models.experience import FeltSense, KeyMoment

    moment_id = uuid4()
    key_moment = KeyMoment(
        id=moment_id,
        what_happened="Profound moment",
        how_i_felt=FeltSense(
            emotional_valence=0.8,
            emotional_intensity=0.9,
            depth=EmotionalDepth.PROFOUND,
        ),
        why_it_matters="Deep insight",
        when=frozen_clock.now(),
        values_touched=["wisdom"],
        principles_questioned=[],
        fact_refs=[],
    )

    # Store the key moment in storage
    store.store_key_moments(orphan_session_id, [key_moment])

    # Write journal entry
    with orphan_journal.open("w") as f:
        json.dump(
            {
                "type": "key_moment",
                "moment_id": str(moment_id),
                "timestamp": frozen_clock.now().isoformat(),
                "what_happened": "Profound moment",
                "fact_refs": [],
            },
            f,
        )
        f.write("\n")

    # Start new session - should trigger recovery with loaded metadata
    manager.start_session(identity_fixture.id)

    # Check recovered experience has better metadata
    experience_id = deterministic_session_experience_id(orphan_session_id)
    recovered_exp = store.get_experience(experience_id)
    assert recovered_exp is not None
    assert recovered_exp.experience.has_profound_moment is True  # Loaded from storage
    assert recovered_exp.experience.avg_emotional_intensity == 0.9  # Loaded from storage
