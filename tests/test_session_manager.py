"""
Tests for Session Manager.

Tests session lifecycle, key moment recording, and experience creation.
"""

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
    Goal,
    GoalHorizon,
    Identity,
    KeyMomentInput,
    LayerType,
    NarrativeDocument,
    NarrativeLayer,
    SessionEvent,
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
def test_identity():
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
def test_narrative(test_identity):
    """Create test narrative."""
    return NarrativeDocument(
        identity_id=test_identity.id,
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
def session_manager(temp_storage, test_identity, test_narrative, frozen_clock):
    """Create session manager with test data and frozen clock."""
    temp_storage.save_identity(test_identity)
    temp_storage.save_narrative(test_narrative)
    return SessionManager(temp_storage, clock=frozen_clock), test_identity.id


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

    manager.record_key_moment(context.session_id, moment)

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
        manager.record_key_moment(context.session_id, moment_no_flag)


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

    manager.record_key_moment(context.session_id, moment_with_flag)

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
    manager.record_key_moment(context.session_id, moment)

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
    assert len(stored_exp.key_moments) == 1


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
    manager.record_key_moment(context.session_id, moment)

    result = manager.finish_session(
        session_id=context.session_id,
        overall_emotional_tone=0.5,
    )

    experiences = temp_storage.list_recent_experiences(limit=1)
    stored_exp = experiences[0].experience

    assert result.key_moments[0].what_happened == original_what
    assert stored_exp.key_moments[0].what_happened == original_what
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
    temp_storage, test_identity, test_narrative
):
    """KeyMoment.when follows Clock time when recorded (temporal consistency)."""
    temp_storage.save_identity(test_identity)
    temp_storage.save_narrative(test_narrative)

    # Start session with clock at T0
    clock_t0 = FrozenClock(datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC))
    manager_t0 = SessionManager(temp_storage, clock=clock_t0)
    context = manager_t0.start_session(test_identity.id)

    # Record key moment at T0
    moment = KeyMomentInput(
        what_happened="Earlier moment",
        emotional_valence=0.1,
        emotional_intensity=0.5,
        depth=EmotionalDepth.SURFACE,
        why_it_matters="Order matters",
    )
    manager_t0.record_key_moment(context.session_id, moment)

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
    manager.record_key_moment(
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
    manager.record_key_moment(
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
    manager.record_key_moment(
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


def test_max_active_sessions_limit(temp_storage, test_identity, test_narrative):
    temp_storage.save_identity(test_identity)
    temp_storage.save_narrative(test_narrative)
    manager = SessionManager(temp_storage, max_active_sessions=1)
    manager.start_session(test_identity.id)
    # Check snapshot count (file-based specific check)
    if hasattr(temp_storage, "identity_snapshots_dir"):
        snap_before = len(list(temp_storage.identity_snapshots_dir.glob("*.json")))
    else:
        snap_before = len(temp_storage.list_identity_snapshots(test_identity.id))
    with pytest.raises(TooManyActiveSessionsError):
        manager.start_session(test_identity.id)
    if hasattr(temp_storage, "identity_snapshots_dir"):
        assert len(list(temp_storage.identity_snapshots_dir.glob("*.json"))) == snap_before
    else:
        assert len(temp_storage.list_identity_snapshots(test_identity.id)) == snap_before


def test_overall_emotional_tone_out_of_range_raises(session_manager):
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)
    manager.record_key_moment(
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
    manager.record_key_moment(
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
    manager.record_key_moment(
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
    manager.record_key_moment(
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

    manager.record_key_moment(context.session_id, warning_moment)

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
        manager.record_key_moment(fake_session_id, moment)

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
        manager.record_key_moment(context.session_id, moment)

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
    manager.record_key_moment(context.session_id, moment)

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
    manager.record_key_moment(context.session_id, moment)

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
    manager.record_key_moment(context.session_id, moment)

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
    manager.record_key_moment(context1.session_id, moment)

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
    assert "Successfully delivered complex work" in recent_content_after
    assert "competence" in recent_content_after or "growth" in recent_content_after
    assert "positive" in recent_content_after  # Overall tone was 0.6

    # Start second session - should load updated narrative
    context2 = manager.start_session(agent_id)
    assert context2.narrative.recent_layer.content == recent_content_after
    assert "Successfully delivered complex work" in context2.narrative.recent_layer.content


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
    manager.record_key_moment(
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


def test_finish_session_retry_after_eigenstate_failure_does_not_duplicate_experience(
    session_manager, temp_storage
):
    manager, agent_id = session_manager
    context = manager.start_session(agent_id)
    manager.record_key_moment(
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
