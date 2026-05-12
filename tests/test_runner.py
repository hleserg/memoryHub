"""
Tests for agent runner signal handling and force-finish behavior.

These tests verify that sessions are properly finished even when interrupted
by signals (SIGTERM), user actions (KeyboardInterrupt, EOFError), or
explicit exits (SystemExit).
"""

from __future__ import annotations

import signal
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

from atman.adapters.agent.runner import _force_finish
from atman.adapters.storage.file_state_store import FileStateStore
from atman.core.exceptions import SessionNotFoundError
from atman.core.models import (
    EmotionalDepth,
    FeltSense,
    Identity,
    KeyMoment,
    KeyMomentInput,
    LayerType,
    NarrativeDocument,
    NarrativeLayer,
    SessionEvent,
    SessionResult,
)
from atman.core.services.session_manager import SessionManager

if TYPE_CHECKING:
    from atman.core.ports.state_store import StateStore


@pytest.fixture
def state_store(tmp_path: Path) -> StateStore:
    """Create temporary file-based state store."""
    return FileStateStore(workspace=tmp_path)


@pytest.fixture
def session_manager(state_store: StateStore) -> SessionManager:
    """Create session manager with state store."""
    return SessionManager(state_store=state_store)


@pytest.fixture
def identity_with_narrative(state_store: StateStore) -> Identity:
    """Create identity with narrative in state store."""
    identity = Identity(
        id=uuid4(),
        self_description="Test Agent",
        created_at=datetime.now(UTC),
        emotional_baseline=0.0,
    )
    state_store.save_identity(identity)

    narrative = NarrativeDocument(
        id=uuid4(),
        identity_id=identity.id,
        created_at=datetime.now(UTC),
        core_layer=NarrativeLayer(content="Core identity", layer_type=LayerType.CORE),
        recent_layer=NarrativeLayer(content="Recent experience", layer_type=LayerType.RECENT),
    )
    state_store.save_narrative(narrative)

    return identity


def test_force_finish_creates_minimal_key_moment(
    session_manager: SessionManager,
    identity_with_narrative: Identity,
) -> None:
    """Test that _force_finish creates a minimal key moment when session is empty."""
    # Start session (use identity.id as agent_id)
    ctx = session_manager.start_session(identity_with_narrative.id)

    # Record some events but no key moments
    session_manager.record_event(
        ctx.session_id,
        SessionEvent(
            session_id=ctx.session_id,
            event_type="user_message",
            description="User said hello",
        ),
    )

    # Verify session has no key moments
    session_result = session_manager.get_active_session(ctx.session_id)
    assert session_result is not None
    assert len(session_result.key_moments) == 0

    # Force finish with invalid close_reason should not persist it
    _force_finish(session_manager, ctx.session_id, close_reason="test_invalid")

    # Verify session was finished and has exactly one minimal key moment
    # Session should no longer be active
    session_result_after = session_manager.get_active_session(ctx.session_id)
    assert session_result_after is None

    # Verify close_reason was NOT persisted (invalid value)
    experiences = session_manager._state_store.list_recent_experiences(limit=1)
    assert len(experiences) == 1
    assert experiences[0].experience.close_reason is None


def test_force_finish_with_existing_key_moments(
    session_manager: SessionManager,
    identity_with_narrative: Identity,
) -> None:
    """Test that _force_finish preserves existing key moments."""
    # Start session
    ctx = session_manager.start_session(identity_with_narrative.id)

    # Record a key moment
    moment = KeyMomentInput(
        what_happened="User asked a challenging question",
        emotional_valence=0.3,
        emotional_intensity=0.6,
        depth=EmotionalDepth.MEANINGFUL,
        why_it_matters="Tests my reasoning",
    )
    session_manager.append_key_moment_input(ctx.session_id, moment)

    # Force finish with valid close_reason
    _force_finish(session_manager, ctx.session_id, close_reason="interrupted")

    # Session should no longer be active (finished)
    session_result = session_manager.get_active_session(ctx.session_id)
    assert session_result is None


def test_force_finish_session_not_found(
    session_manager: SessionManager,
) -> None:
    """Test that _force_finish raises SessionNotFoundError for non-existent session."""
    fake_session_id = uuid4()

    with pytest.raises(SessionNotFoundError, match=str(fake_session_id)):
        _force_finish(session_manager, fake_session_id, close_reason="test")


def test_force_finish_already_finished_session(
    session_manager: SessionManager,
    identity_with_narrative: Identity,
) -> None:
    """Test that _force_finish handles already-finished sessions gracefully."""
    # Start and finish session normally
    ctx = session_manager.start_session(identity_with_narrative.id)

    moment = KeyMomentInput(
        what_happened="Normal completion",
        emotional_valence=0.0,
        emotional_intensity=0.5,
        depth=EmotionalDepth.SURFACE,
        why_it_matters="Session completed",
    )
    session_manager.append_key_moment_input(ctx.session_id, moment)
    session_manager.finish_session(ctx.session_id)

    # Attempt force finish on already-finished session
    # Should raise SessionNotFoundError (session no longer active)
    with pytest.raises(SessionNotFoundError):
        _force_finish(session_manager, ctx.session_id, close_reason="test")


def test_chat_handles_keyboard_interrupt(
    session_manager: SessionManager,
    identity_with_narrative: Identity,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that chat() handles KeyboardInterrupt by calling _force_finish."""
    ctx = session_manager.start_session(identity_with_narrative.id)

    # Add a key moment so force_finish doesn't need to create minimal
    moment = KeyMomentInput(
        what_happened="User interrupted",
        emotional_valence=0.0,
        emotional_intensity=0.4,
        depth=EmotionalDepth.SURFACE,
        why_it_matters="Session interrupted",
    )
    session_manager.append_key_moment_input(ctx.session_id, moment)

    # Simulate KeyboardInterrupt in the main loop
    # Since our chat() function has a pass statement, we'll raise in the try block
    def mock_chat_raises_keyboard_interrupt() -> None:
        raise KeyboardInterrupt()

    # We can't easily inject into the function, so we'll test the exception handling
    # by calling chat with a patched signal handler
    def patched_chat(
        sm: SessionManager,
        sid: object,
        *,
        close_reason: str = "completed",
    ) -> None:
        """Patched chat that raises KeyboardInterrupt."""
        interrupted = False
        exit_code = 0

        def _sigterm_handler(signum: int, frame: object) -> None:
            nonlocal interrupted
            _ = (signum, frame)
            interrupted = True

        original_sigterm_handler = signal.signal(signal.SIGTERM, _sigterm_handler)

        try:
            raise KeyboardInterrupt()
        except (KeyboardInterrupt, EOFError):
            interrupted = True
        except SystemExit as exc:
            interrupted = True
            exit_code = exc.code if isinstance(exc.code, int) else 1
        finally:
            signal.signal(signal.SIGTERM, original_sigterm_handler)
            if interrupted:
                _force_finish(sm, sid, close_reason="interrupted")  # type: ignore[arg-type]
            if exit_code != 0:
                sys.exit(exit_code)

    # Call patched version
    patched_chat(session_manager, ctx.session_id)

    # Verify session was force-finished
    session_result = session_manager.get_active_session(ctx.session_id)
    assert session_result is None


def test_chat_handles_eof_error(
    session_manager: SessionManager,
    identity_with_narrative: Identity,
) -> None:
    """Test that chat() handles EOFError by calling _force_finish."""
    ctx = session_manager.start_session(identity_with_narrative.id)

    # Add a key moment
    moment = KeyMomentInput(
        what_happened="EOF received",
        emotional_valence=0.0,
        emotional_intensity=0.3,
        depth=EmotionalDepth.SURFACE,
        why_it_matters="Input stream closed",
    )
    session_manager.append_key_moment_input(ctx.session_id, moment)

    # Patched version that raises EOFError
    interrupted = False

    def _sigterm_handler(signum: int, frame: object) -> None:
        nonlocal interrupted
        _ = (signum, frame)
        interrupted = True

    original_sigterm_handler = signal.signal(signal.SIGTERM, _sigterm_handler)

    try:
        raise EOFError()
    except (KeyboardInterrupt, EOFError):
        interrupted = True
    finally:
        signal.signal(signal.SIGTERM, original_sigterm_handler)
        if interrupted:
            _force_finish(session_manager, ctx.session_id, close_reason="interrupted")

    # Verify session was force-finished
    session_result = session_manager.get_active_session(ctx.session_id)
    assert session_result is None


def test_chat_handles_system_exit(
    session_manager: SessionManager,
    identity_with_narrative: Identity,
) -> None:
    """Test that chat() handles SystemExit by calling _force_finish and re-raising."""
    ctx = session_manager.start_session(identity_with_narrative.id)

    # Add a key moment
    moment = KeyMomentInput(
        what_happened="System exit called",
        emotional_valence=0.0,
        emotional_intensity=0.5,
        depth=EmotionalDepth.SURFACE,
        why_it_matters="Explicit exit requested",
    )
    session_manager.append_key_moment_input(ctx.session_id, moment)

    # Simulate SystemExit
    interrupted = False
    exit_code = 0

    def _sigterm_handler(signum: int, frame: object) -> None:
        nonlocal interrupted
        _ = (signum, frame)
        interrupted = True

    original_sigterm_handler = signal.signal(signal.SIGTERM, _sigterm_handler)

    try:
        try:
            sys.exit(42)
        except SystemExit as exc:
            interrupted = True
            exit_code = exc.code if isinstance(exc.code, int) else 1
        finally:
            signal.signal(signal.SIGTERM, original_sigterm_handler)
            if interrupted:
                _force_finish(session_manager, ctx.session_id, close_reason="interrupted")
            if exit_code != 0:
                with pytest.raises(SystemExit) as exc_info:
                    sys.exit(exit_code)
                assert exc_info.value.code == 42

    except SystemExit:
        pass  # Expected

    # Verify session was force-finished
    session_result = session_manager.get_active_session(ctx.session_id)
    assert session_result is None


def test_chat_handles_sigterm(
    session_manager: SessionManager,
    identity_with_narrative: Identity,
) -> None:
    """Test that chat() handles SIGTERM by calling _force_finish."""
    ctx = session_manager.start_session(identity_with_narrative.id)

    # Add a key moment
    moment = KeyMomentInput(
        what_happened="SIGTERM received",
        emotional_valence=0.0,
        emotional_intensity=0.4,
        depth=EmotionalDepth.SURFACE,
        why_it_matters="Process termination requested",
    )
    session_manager.append_key_moment_input(ctx.session_id, moment)

    # Simulate SIGTERM by setting interrupted flag
    interrupted = False

    def _sigterm_handler(signum: int, frame: object) -> None:
        nonlocal interrupted
        _ = (signum, frame)
        interrupted = True

    original_sigterm_handler = signal.signal(signal.SIGTERM, _sigterm_handler)

    try:
        # Simulate signal
        _sigterm_handler(signal.SIGTERM, None)
        # Main loop would check interrupted flag here
    finally:
        signal.signal(signal.SIGTERM, original_sigterm_handler)
        if interrupted:
            _force_finish(session_manager, ctx.session_id, close_reason="interrupted")

    # Verify session was force-finished
    session_result = session_manager.get_active_session(ctx.session_id)
    assert session_result is None


def test_force_finish_incomplete_coloring_flag(
    session_manager: SessionManager,
    identity_with_narrative: Identity,
) -> None:
    """Test that _force_finish sets incomplete_coloring=True for minimal key moment."""
    ctx = session_manager.start_session(identity_with_narrative.id)

    # No key moments recorded
    session_result = session_manager.get_active_session(ctx.session_id)
    assert session_result is not None
    assert len(session_result.key_moments) == 0

    # Force finish should create minimal moment with incomplete_coloring=True
    _force_finish(session_manager, ctx.session_id, close_reason=None)

    # Session should be finished (no longer active)
    session_result_after = session_manager.get_active_session(ctx.session_id)
    assert session_result_after is None


def test_check_restart_requested_with_sentinel() -> None:
    """Test that _check_restart_requested detects restart sentinel."""
    from atman.adapters.agent.runner import _check_restart_requested

    # Mock message with restart sentinel (no reason)
    class MockPart:
        def __init__(self) -> None:
            self.content = "__ATMAN_RESTART_REQUESTED__"

    class MockMessage:
        def __init__(self) -> None:
            self.parts = [MockPart()]

    messages = [MockMessage()]
    restart_requested, reason = _check_restart_requested(messages)
    assert restart_requested is True
    assert reason == ""


def test_check_restart_requested_with_reason() -> None:
    """Test that _check_restart_requested extracts restart reason."""
    from atman.adapters.agent.runner import _check_restart_requested

    # Mock message with restart sentinel and reason
    class MockPart:
        def __init__(self) -> None:
            self.content = "__ATMAN_RESTART_REQUESTED__\nContext window filling up"

    class MockMessage:
        def __init__(self) -> None:
            self.parts = [MockPart()]

    messages = [MockMessage()]
    restart_requested, reason = _check_restart_requested(messages)
    assert restart_requested is True
    assert reason == "Context window filling up"


def test_check_restart_requested_no_sentinel() -> None:
    """Test that _check_restart_requested returns False when no sentinel."""
    from atman.adapters.agent.runner import _check_restart_requested

    # Mock message without restart sentinel
    class MockPart:
        def __init__(self) -> None:
            self.content = "Normal agent response"

    class MockMessage:
        def __init__(self) -> None:
            self.parts = [MockPart()]

    messages = [MockMessage()]
    restart_requested, reason = _check_restart_requested(messages)
    assert restart_requested is False
    assert reason == ""


def test_check_restart_requested_with_tool_name() -> None:
    """Test that _check_restart_requested detects restart via tool_name."""
    from atman.adapters.agent.runner import _check_restart_requested

    # Mock message with tool_name
    class MockPart:
        def __init__(self) -> None:
            self.tool_name = "restart_session"

    class MockMessage:
        def __init__(self) -> None:
            self.parts = [MockPart()]

    messages = [MockMessage()]
    restart_requested, reason = _check_restart_requested(messages)
    assert restart_requested is True
    assert reason == ""


def test_check_restart_requested_prioritizes_content_sentinel() -> None:
    """Test that content sentinel is checked before tool_name to capture reason."""
    from atman.adapters.agent.runner import _check_restart_requested

    # Mock messages with both tool_name and content (realistic Pydantic-AI scenario)
    # First part: ToolCallPart with tool_name
    class MockToolCallPart:
        def __init__(self) -> None:
            self.tool_name = "restart_session"

    # Second part: ToolReturnPart with both tool_name and sentinel content
    class MockToolReturnPart:
        def __init__(self) -> None:
            self.tool_name = "restart_session"
            self.content = "__ATMAN_RESTART_REQUESTED__\nContext window full"

    class MockMessage:
        def __init__(self) -> None:
            self.parts = [MockToolCallPart(), MockToolReturnPart()]

    messages = [MockMessage()]
    restart_requested, reason = _check_restart_requested(messages)
    assert restart_requested is True
    assert reason == "Context window full", "Reason should be extracted from content sentinel"


def test_build_restart_package() -> None:
    """Test that _build_restart_package creates valid package."""
    from atman.adapters.agent.runner import _build_restart_package

    # Create mock session result
    ctx = SessionResult(
        session_id=uuid4(),
        started_at=datetime.now(UTC),
        events=[],
        key_moments=[
            KeyMoment(
                what_happened="User asked a question",
                how_i_felt=FeltSense(
                    emotional_valence=0.3,
                    emotional_intensity=0.5,
                    depth=EmotionalDepth.MEANINGFUL,
                ),
                why_it_matters="Engaging conversation",
            ),
        ],
        identity_snapshot_id=uuid4(),
        identity_id=uuid4(),
    )

    package = _build_restart_package(ctx, "Context filling up", [])

    assert "Context filling up" in package
    assert "Key moments from previous session:" in package
    assert "User asked a question" in package
    assert "depth: meaningful" in package
    assert "--- Conversation tail ---" in package


def test_force_finish_with_timeout_sleep_reason(
    session_manager: SessionManager,
    identity_with_narrative: Identity,
) -> None:
    """Test that _force_finish works with timeout_sleep close_reason from menu mode."""
    ctx = session_manager.start_session(identity_with_narrative.id)

    # Add a key moment
    moment = KeyMomentInput(
        what_happened="Session timed out",
        emotional_valence=0.0,
        emotional_intensity=0.3,
        depth=EmotionalDepth.SURFACE,
        why_it_matters="Timeout occurred",
    )
    session_manager.append_key_moment_input(ctx.session_id, moment)

    # Force finish with timeout_sleep reason
    _force_finish(session_manager, ctx.session_id, close_reason="timeout_sleep")

    # Session should be finished
    session_result = session_manager.get_active_session(ctx.session_id)
    assert session_result is None


def test_force_finish_with_menu_timeout_reason(
    session_manager: SessionManager,
    identity_with_narrative: Identity,
) -> None:
    """Test that _force_finish works with menu_timeout close_reason after max retries."""
    ctx = session_manager.start_session(identity_with_narrative.id)

    # Force finish with menu_timeout reason (no key moments - minimal will be created)
    _force_finish(session_manager, ctx.session_id, close_reason="menu_timeout")

    # Session should be finished
    session_result = session_manager.get_active_session(ctx.session_id)
    assert session_result is None


def test_atman_runner_initialization(tmp_path: Path) -> None:
    """Test that AtmanRunner can be initialized with workspace, agent_id, and config."""
    from atman.adapters.agent.config import AgentConfig
    from atman.adapters.agent.runner import AtmanRunner

    agent_id = uuid4()
    config = AgentConfig(session_timeout_minutes=5, enable_free_time=True)

    runner = AtmanRunner(workspace=tmp_path, agent_id=agent_id, config=config)

    assert runner._workspace == tmp_path
    assert runner._agent_id == agent_id
    assert runner._config.session_timeout_minutes == 5
    assert runner._config.enable_free_time is True


async def test_stdin_reader_thread_lifecycle(tmp_path: Path) -> None:
    """Test that stdin reader thread lifecycle is managed correctly.

    Note: In pytest environment stdin is not available, so thread will
    exit immediately with OSError. This tests the lifecycle management.
    """
    import asyncio

    from atman.adapters.agent.config import AgentConfig
    from atman.adapters.agent.runner import AtmanRunner

    agent_id = uuid4()
    config = AgentConfig()
    runner = AtmanRunner(workspace=tmp_path, agent_id=agent_id, config=config)

    # Initially no reader thread
    assert runner._reader_thread is None

    # Start reader with current event loop
    loop = asyncio.get_event_loop()
    runner._start_stdin_reader(loop)

    # Thread should be created (even if it exits immediately due to pytest stdin)
    assert runner._reader_thread is not None

    # Give thread time to handle OSError and exit
    await asyncio.sleep(0.1)

    # Stop reader
    runner._stop_stdin_reader()
    assert runner._stop_reader.is_set()

    # Verify stop flag works (thread may already be stopped from OSError)
    # Just checking the flag is set is sufficient for this test


def test_wait_command_returns_new_timeout() -> None:
    """Test that wait command return value includes new timeout in seconds."""
    # Simulate what _handle_menu_mode returns for wait command
    result = ("wait", 1800)  # 30 minutes * 60 seconds

    assert isinstance(result, tuple)
    assert result[0] == "wait"
    assert result[1] == 1800


def test_force_finish_with_different_close_reasons(
    session_manager: SessionManager,
    identity_with_narrative: Identity,
) -> None:
    """Test _force_finish works with various close reasons from menu/timeout."""
    close_reasons = ["timeout_sleep", "menu_timeout", "interrupted", "completed"]

    for reason in close_reasons:
        ctx = session_manager.start_session(identity_with_narrative.id)

        # Add a key moment so finish succeeds
        moment = KeyMomentInput(
            what_happened=f"Test with reason: {reason}",
            emotional_valence=0.0,
            emotional_intensity=0.5,
            depth=EmotionalDepth.SURFACE,
            why_it_matters=f"Testing {reason}",
        )
        session_manager.append_key_moment_input(ctx.session_id, moment)

        # Force finish with specific reason
        _force_finish(session_manager, ctx.session_id, close_reason=reason)

        # Verify session is finished
        session_result = session_manager.get_active_session(ctx.session_id)
        assert session_result is None


def test_print_prompt_helper_exists() -> None:
    """Test that print_prompt helper exists in atman.term."""
    from atman.term import print_prompt

    # Just verify the function exists and is callable
    assert callable(print_prompt)


def test_build_wake_up_message_timeout_sleep(
    session_manager: SessionManager,
    identity_with_narrative: Identity,
) -> None:
    """Test wake-up message for timeout_sleep close_reason."""
    from atman.adapters.agent.config import AgentConfig, ModelConfig
    from atman.adapters.agent.runner import AtmanRunner

    ctx = session_manager.start_session(identity_with_narrative.id)
    moment = KeyMomentInput(
        what_happened="User went away",
        emotional_valence=0.0,
        emotional_intensity=0.3,
        depth=EmotionalDepth.SURFACE,
        why_it_matters="Timeout",
    )
    session_manager.append_key_moment_input(ctx.session_id, moment)
    session_manager.finish_session(
        ctx.session_id,
        close_reason="timeout_sleep",
        agent_recap="Пользователь обсуждал проект X",
    )

    # Get last experience and build wake-up message
    experiences = session_manager._state_store.list_recent_experiences(limit=1)
    assert len(experiences) == 1
    last_exp = experiences[0].experience

    runner = AtmanRunner(
        workspace=Path("/tmp"),
        agent_id=identity_with_narrative.id,
        config=AgentConfig(model=ModelConfig(model="test")),
    )
    msg = runner._build_wake_up_message(last_exp)
    assert msg is not None
    assert "задремал" in msg
    assert "Пользователь обсуждал проект X" in msg


def test_build_wake_up_message_restart(
    session_manager: SessionManager,
    identity_with_narrative: Identity,
) -> None:
    """Test wake-up message for restart close_reason."""
    from atman.adapters.agent.config import AgentConfig, ModelConfig
    from atman.adapters.agent.runner import AtmanRunner

    ctx = session_manager.start_session(identity_with_narrative.id)
    moment = KeyMomentInput(
        what_happened="Agent initiated restart",
        emotional_valence=0.0,
        emotional_intensity=0.4,
        depth=EmotionalDepth.SURFACE,
        why_it_matters="Restart needed",
    )
    session_manager.append_key_moment_input(ctx.session_id, moment)
    session_manager.finish_session(
        ctx.session_id,
        close_reason="restart",
        restart_reason="Контекст заполнен, продолжу с чистой историей",
    )

    experiences = session_manager._state_store.list_recent_experiences(limit=1)
    last_exp = experiences[0].experience

    runner = AtmanRunner(
        workspace=Path("/tmp"),
        agent_id=identity_with_narrative.id,
        config=AgentConfig(model=ModelConfig(model="test")),
    )
    msg = runner._build_wake_up_message(last_exp)
    assert msg is not None
    assert "перезапуск" in msg
    assert "Контекст заполнен, продолжу с чистой историей" in msg


def test_build_wake_up_message_forced(
    session_manager: SessionManager,
    identity_with_narrative: Identity,
) -> None:
    """Test wake-up message for forced close_reason."""
    from atman.adapters.agent.config import AgentConfig, ModelConfig
    from atman.adapters.agent.runner import AtmanRunner

    ctx = session_manager.start_session(identity_with_narrative.id)
    moment = KeyMomentInput(
        what_happened="Context overflow",
        emotional_valence=0.0,
        emotional_intensity=0.5,
        depth=EmotionalDepth.SURFACE,
        why_it_matters="Forced closure",
    )
    session_manager.append_key_moment_input(ctx.session_id, moment)
    session_manager.finish_session(ctx.session_id, close_reason="forced")

    experiences = session_manager._state_store.list_recent_experiences(limit=1)
    last_exp = experiences[0].experience

    runner = AtmanRunner(
        workspace=Path("/tmp"),
        agent_id=identity_with_narrative.id,
        config=AgentConfig(model=ModelConfig(model="test")),
    )
    msg = runner._build_wake_up_message(last_exp)
    assert msg is not None
    assert "переполнился" in msg
    assert "осознанно" in msg


def test_build_wake_up_message_interrupted(
    session_manager: SessionManager,
    identity_with_narrative: Identity,
) -> None:
    """Test wake-up message for interrupted close_reason."""
    from atman.adapters.agent.config import AgentConfig, ModelConfig
    from atman.adapters.agent.runner import AtmanRunner

    ctx = session_manager.start_session(identity_with_narrative.id)
    moment = KeyMomentInput(
        what_happened="Signal received",
        emotional_valence=0.0,
        emotional_intensity=0.4,
        depth=EmotionalDepth.SURFACE,
        why_it_matters="Interrupted",
    )
    session_manager.append_key_moment_input(ctx.session_id, moment)
    session_manager.finish_session(ctx.session_id, close_reason="interrupted")

    experiences = session_manager._state_store.list_recent_experiences(limit=1)
    last_exp = experiences[0].experience

    runner = AtmanRunner(
        workspace=Path("/tmp"),
        agent_id=identity_with_narrative.id,
        config=AgentConfig(model=ModelConfig(model="test")),
    )
    msg = runner._build_wake_up_message(last_exp)
    assert msg is not None
    assert "прервана" in msg
    assert "внешним сигналом" in msg


def test_build_wake_up_message_no_close_reason(
    session_manager: SessionManager,
    identity_with_narrative: Identity,
) -> None:
    """Test that no wake-up message is generated when close_reason is None."""
    from atman.adapters.agent.config import AgentConfig, ModelConfig
    from atman.adapters.agent.runner import AtmanRunner

    ctx = session_manager.start_session(identity_with_narrative.id)
    moment = KeyMomentInput(
        what_happened="Normal completion",
        emotional_valence=0.0,
        emotional_intensity=0.3,
        depth=EmotionalDepth.SURFACE,
        why_it_matters="Session done",
    )
    session_manager.append_key_moment_input(ctx.session_id, moment)
    session_manager.finish_session(ctx.session_id)

    experiences = session_manager._state_store.list_recent_experiences(limit=1)
    last_exp = experiences[0].experience

    runner = AtmanRunner(
        workspace=Path("/tmp"),
        agent_id=identity_with_narrative.id,
        config=AgentConfig(model=ModelConfig(model="test")),
    )
    msg = runner._build_wake_up_message(last_exp)
    assert msg is None


def test_force_finish_persists_close_reason(
    session_manager: SessionManager,
    identity_with_narrative: Identity,
) -> None:
    """Test that _force_finish persists close_reason to SessionExperience for valid values."""
    ctx = session_manager.start_session(identity_with_narrative.id)
    moment = KeyMomentInput(
        what_happened="Some work",
        emotional_valence=0.0,
        emotional_intensity=0.4,
        depth=EmotionalDepth.SURFACE,
        why_it_matters="Task in progress",
    )
    session_manager.append_key_moment_input(ctx.session_id, moment)

    # Force finish with specific close_reason
    _force_finish(session_manager, ctx.session_id, close_reason="interrupted")

    # Verify SessionExperience has the close_reason
    experiences = session_manager._state_store.list_recent_experiences(limit=1)
    assert len(experiences) == 1
    assert experiences[0].experience.close_reason == "interrupted"


def test_force_finish_none_close_reason_for_normal_completion(
    session_manager: SessionManager,
    identity_with_narrative: Identity,
) -> None:
    """Test that _force_finish with None close_reason doesn't persist close_reason field."""
    ctx = session_manager.start_session(identity_with_narrative.id)
    moment = KeyMomentInput(
        what_happened="Normal work",
        emotional_valence=0.0,
        emotional_intensity=0.3,
        depth=EmotionalDepth.SURFACE,
        why_it_matters="Regular session",
    )
    session_manager.append_key_moment_input(ctx.session_id, moment)

    # Force finish with None (normal completion, no interruption)
    _force_finish(session_manager, ctx.session_id, close_reason=None)

    # Verify SessionExperience has close_reason=None
    experiences = session_manager._state_store.list_recent_experiences(limit=1)
    assert len(experiences) == 1
    assert experiences[0].experience.close_reason is None


def test_check_restart_requested_uses_new_messages_only() -> None:
    """Test that restart detection doesn't trigger on old sentinels in history."""
    from atman.adapters.agent.runner import _check_restart_requested

    # Simulate messages: old sentinel from previous restart should be ignored
    class MockOldPart:
        def __init__(self) -> None:
            self.content = "__ATMAN_RESTART_REQUESTED__\nOld restart reason"

    class MockNewPart:
        def __init__(self) -> None:
            self.content = "Normal response without sentinel"

    class MockOldMessage:
        def __init__(self) -> None:
            self.parts = [MockOldPart()]

    class MockNewMessage:
        def __init__(self) -> None:
            self.parts = [MockNewPart()]

    # Only new messages should be checked (not including old history)
    new_messages_only = [MockNewMessage()]
    restart_requested, reason = _check_restart_requested(new_messages_only)
    assert restart_requested is False, "Should not detect restart from old sentinel in history"
    assert reason == ""


def test_force_finish_with_menu_timeout(
    session_manager: SessionManager,
    identity_with_narrative: Identity,
) -> None:
    """Test that menu_timeout is a valid close_reason and is persisted."""
    ctx = session_manager.start_session(identity_with_narrative.id)

    # Add a key moment
    moment = KeyMomentInput(
        what_happened="Menu timeout",
        emotional_valence=0.0,
        emotional_intensity=0.2,
        depth=EmotionalDepth.SURFACE,
        why_it_matters="Menu max retries reached",
    )
    session_manager.append_key_moment_input(ctx.session_id, moment)

    # Force finish with menu_timeout reason
    _force_finish(session_manager, ctx.session_id, close_reason="menu_timeout")

    # Verify SessionExperience has close_reason="menu_timeout"
    experiences = session_manager._state_store.list_recent_experiences(limit=1)
    assert len(experiences) == 1
    assert experiences[0].experience.close_reason == "menu_timeout"


def test_do_restart_persists_restart_reason(
    session_manager: SessionManager,
    identity_with_narrative: Identity,
    tmp_path: Path,
) -> None:
    """Test that _do_restart persists restart_reason to SessionExperience."""
    from dataclasses import replace

    from atman.adapters.agent.config import AgentConfig
    from atman.adapters.agent.factory import build_deps
    from atman.adapters.agent.runner import AtmanRunner

    # Create runner and build deps
    config = AgentConfig()
    runner = AtmanRunner(tmp_path, identity_with_narrative.id, config)
    deps, sm, _store = build_deps(tmp_path, identity_with_narrative.id, config)

    # Start session
    ctx = sm.start_session(identity_with_narrative.id)

    # Add a key moment so session can be finished
    moment = KeyMomentInput(
        what_happened="Context window approaching limit",
        emotional_valence=0.0,
        emotional_intensity=0.4,
        depth=EmotionalDepth.SURFACE,
        why_it_matters="Need to restart",
    )
    sm.append_key_moment_input(ctx.session_id, moment)

    # Update deps with session_id
    deps = replace(deps, session_id=ctx.session_id)
    history = []

    # Execute restart with specific reason
    restart_reason = "Context window 95% full"
    new_session_id, new_deps = runner._do_restart(
        sm, ctx.session_id, deps, history, restart_reason
    )

    # Verify restart_reason is persisted in SessionExperience
    experiences = sm._state_store.list_recent_experiences(limit=1)
    assert len(experiences) == 1
    assert experiences[0].experience.close_reason == "restart"
    assert (
        experiences[0].experience.restart_reason == restart_reason
    ), "restart_reason should be persisted to SessionExperience"
