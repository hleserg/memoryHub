"""
Tests for agent tools (record_key_moment, log_experience).

Covers:
- Recording key moments during active session
- Error handling for invalid emotional values
- Error handling when no session is active
"""

from datetime import UTC, datetime
from pathlib import Path
from tempfile import mkdtemp
from uuid import UUID, uuid4

from opentelemetry.trace import NoOpTracer
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from atman.adapters.agent import log_experience, record_key_moment, restart_session, wait_session
from atman.adapters.agent.deps import AtmanDeps
from atman.adapters.reflection.mock_reflection_model import MockReflectionModel
from atman.adapters.storage import InMemoryExperienceStore, InMemoryStateStore
from atman.adapters.storage.in_memory_reflection_store import InMemoryReflectionEventStore
from atman.affect.detector import AffectDetectorConfig
from atman.core.narrative_write_audit import NoOpNarrativeWriteAudit
from atman.core.services import (
    ExperienceService,
    IdentityService,
    MicroReflectionService,
    NarrativeRevisionService,
    SessionManager,
)


def _make_run_context(deps: AtmanDeps) -> RunContext[AtmanDeps]:
    """Construct a minimal RunContext suitable for unit-testing tool functions."""
    return RunContext(
        deps=deps,
        model=TestModel(),
        usage=RunUsage(),
        messages=[],
        tracer=NoOpTracer(),
        retries={},
    )


def _create_deps_with_session(agent_id: UUID) -> tuple[AtmanDeps, UUID]:
    """Create deps and start a session."""
    state_store = InMemoryStateStore()
    experience_service = ExperienceService(InMemoryExperienceStore())
    event_store = InMemoryReflectionEventStore()
    narrative_revision = NarrativeRevisionService(
        narrative_repo=state_store,  # type: ignore[arg-type]
        reflection_model=MockReflectionModel(),
        narrative_audit=NoOpNarrativeWriteAudit(),
    )

    affect_ws = Path(mkdtemp())
    affect_cfg = AffectDetectorConfig(cold_start_sessions=0, random_sample_every_n=99999)
    session_manager = SessionManager(
        state_store,
        affect_workspace=affect_ws,
        affect_config=affect_cfg,
    )
    identity_service = IdentityService(state_store)

    # Bootstrap identity
    identity_service.bootstrap_identity(agent_id)

    # Create bootstrap narrative
    from atman.core.models import LayerType, NarrativeDocument, NarrativeLayer

    narrative = NarrativeDocument(
        id=uuid4(),
        identity_id=agent_id,
        core_layer=NarrativeLayer(
            layer_type=LayerType.CORE,
            content="I am just beginning. I have no history yet, but I'm ready to build it.",
        ),
        recent_layer=NarrativeLayer(
            layer_type=LayerType.RECENT,
            content="Starting my first session.",
        ),
        threads=[],
        updated_at=datetime.now(UTC),
    )
    state_store.save_narrative(narrative)

    # Start session
    session_ctx = session_manager.start_session(agent_id)

    deps = AtmanDeps(
        session_manager=session_manager,
        identity_service=identity_service,
        experience_service=experience_service,
        micro_reflection=MicroReflectionService(
            experience_repo=experience_service,  # type: ignore[arg-type]
            narrative_revision=narrative_revision,
            event_store=event_store,
        ),
        state_store=state_store,
        agent_id=agent_id,
        session_id=session_ctx.session_id,
    )

    return deps, session_ctx.session_id


class TestRecordKeyMoment:
    """Tests for record_key_moment tool."""

    async def test_record_key_moment_success(self):
        """Test successfully recording a key moment."""
        agent_id = uuid4()
        deps, _session_id = _create_deps_with_session(agent_id)

        ctx = _make_run_context(deps)

        result = await record_key_moment(
            ctx,
            what_happened="User asked a challenging question",
            why_it_matters="Pushed me to think more carefully",
            emotional_valence=0.3,
            emotional_intensity=0.7,
            depth="meaningful",
        )

        assert "Key moment recorded" in result
        assert "User asked" in result

    async def test_record_key_moment_no_session(self):
        """Test error when no session is active."""
        agent_id = uuid4()
        state_store = InMemoryStateStore()
        experience_service = ExperienceService(InMemoryExperienceStore())
        event_store = InMemoryReflectionEventStore()
        narrative_revision = NarrativeRevisionService(
            narrative_repo=state_store,  # type: ignore[arg-type]
            reflection_model=MockReflectionModel(),
            narrative_audit=NoOpNarrativeWriteAudit(),
        )

        deps = AtmanDeps(
            session_manager=SessionManager(state_store),
            identity_service=IdentityService(state_store),
            experience_service=experience_service,
            micro_reflection=MicroReflectionService(
                experience_repo=experience_service,  # type: ignore[arg-type]
                narrative_revision=narrative_revision,
                event_store=event_store,
            ),
            state_store=state_store,
            agent_id=agent_id,
            session_id=None,  # No active session
        )

        ctx = _make_run_context(deps)

        result = await record_key_moment(
            ctx,
            what_happened="Something happened",
            why_it_matters="It matters",
        )

        assert "Error" in result
        assert "No active session" in result

    async def test_record_key_moment_invalid_valence(self):
        """Test error with invalid emotional valence."""
        agent_id = uuid4()
        deps, _ = _create_deps_with_session(agent_id)

        ctx = _make_run_context(deps)

        result = await record_key_moment(
            ctx,
            what_happened="Something",
            why_it_matters="Matters",
            emotional_valence=2.0,  # Invalid: > 1.0
        )

        assert "Error" in result
        assert "emotional_valence" in result

    async def test_record_key_moment_invalid_intensity(self):
        """Test error with invalid emotional intensity."""
        agent_id = uuid4()
        deps, _ = _create_deps_with_session(agent_id)

        ctx = _make_run_context(deps)

        result = await record_key_moment(
            ctx,
            what_happened="Something",
            why_it_matters="Matters",
            emotional_intensity=-0.5,  # Invalid: < 0.0
        )

        assert "Error" in result
        assert "emotional_intensity" in result

    async def test_record_key_moment_rejects_both_zero_emotional_coloring(self):
        """Both valence=0 and intensity=0 must yield an LLM-actionable error.

        ``append_key_moment_input`` rejects this combination unless
        ``incomplete_coloring=True``, but the agent tool doesn't expose that
        flag — so it must intercept the case itself and return guidance the LLM
        can actually act on.
        """
        agent_id = uuid4()
        deps, _ = _create_deps_with_session(agent_id)

        ctx = _make_run_context(deps)

        result = await record_key_moment(
            ctx,
            what_happened="Something neutral",
            why_it_matters="Routine",
            emotional_valence=0.0,
            emotional_intensity=0.0,
        )

        assert result.startswith("Error: ")
        assert "emotional_valence" in result
        assert "emotional_intensity" in result
        assert "0.0" in result
        # Must NOT leak the SessionManager-internal flag name to the LLM,
        # since the tool surface doesn't expose it.
        assert "incomplete_coloring" not in result

    async def test_record_key_moment_invalid_depth(self):
        """Test error with invalid depth value."""
        agent_id = uuid4()
        deps, _ = _create_deps_with_session(agent_id)

        ctx = _make_run_context(deps)

        result = await record_key_moment(
            ctx,
            what_happened="Something",
            why_it_matters="Matters",
            depth="not-a-real-depth",  # type: ignore[arg-type]
        )

        assert "Error" in result
        assert "invalid depth" in result


class TestLogExperience:
    """Tests for log_experience tool."""

    def test_log_experience_redirects_to_record(self):
        """Test that log_experience suggests using record_key_moment."""
        agent_id = uuid4()
        deps, _ = _create_deps_with_session(agent_id)

        ctx = _make_run_context(deps)

        result = log_experience(
            ctx,
            description="An experience happened",
            key_insight="Learned something",
        )

        assert "automatically at session end" in result
        assert "record_key_moment" in result


class TestRestartSession:
    """Tests for restart_session tool."""

    def test_restart_session_returns_sentinel(self):
        """Test that restart_session returns correct sentinel string with newline delimiter."""
        agent_id = uuid4()
        deps, _ = _create_deps_with_session(agent_id)

        ctx = _make_run_context(deps)

        result = restart_session(ctx, reason="test reason")

        assert result.startswith("__ATMAN_RESTART_REQUESTED__\n")
        assert "test reason" in result
        # Verify format: sentinel + newline + reason
        lines = result.split("\n", 1)
        assert lines[0] == "__ATMAN_RESTART_REQUESTED__"
        assert lines[1] == "test reason"

    def test_restart_session_empty_reason(self):
        """Test restart_session with empty reason."""
        agent_id = uuid4()
        deps, _ = _create_deps_with_session(agent_id)

        ctx = _make_run_context(deps)

        result = restart_session(ctx, reason="")

        assert result == "__ATMAN_RESTART_REQUESTED__"

    def test_restart_session_no_session(self):
        """Test restart_session works even without active session."""
        agent_id = uuid4()
        state_store = InMemoryStateStore()
        experience_service = ExperienceService(InMemoryExperienceStore())
        event_store = InMemoryReflectionEventStore()
        narrative_revision = NarrativeRevisionService(
            narrative_repo=state_store,  # type: ignore[arg-type]
            reflection_model=MockReflectionModel(),
            narrative_audit=NoOpNarrativeWriteAudit(),
        )

        deps = AtmanDeps(
            session_manager=SessionManager(state_store),
            identity_service=IdentityService(state_store),
            experience_service=experience_service,
            micro_reflection=MicroReflectionService(
                experience_repo=experience_service,  # type: ignore[arg-type]
                narrative_revision=narrative_revision,
                event_store=event_store,
            ),
            state_store=state_store,
            agent_id=agent_id,
            session_id=None,
        )

        ctx = _make_run_context(deps)

        result = restart_session(ctx, reason="emergency")

        assert result == "__ATMAN_RESTART_REQUESTED__\nemergency"


class TestWaitSession:
    """Tests for wait_session tool."""

    def test_wait_session_returns_sentinel(self):
        """Test that wait_session returns correct sentinel string."""
        agent_id = uuid4()
        deps, _ = _create_deps_with_session(agent_id)

        ctx = _make_run_context(deps)

        result = wait_session(ctx, minutes=5)

        assert result == "__ATMAN_WAIT_REQUESTED__5"

    def test_wait_session_various_durations(self):
        """Test wait_session with different positive minute values."""
        agent_id = uuid4()
        deps, _ = _create_deps_with_session(agent_id)

        ctx = _make_run_context(deps)

        # Test different positive values
        assert wait_session(ctx, minutes=1) == "__ATMAN_WAIT_REQUESTED__1"
        assert wait_session(ctx, minutes=60) == "__ATMAN_WAIT_REQUESTED__60"
        assert wait_session(ctx, minutes=120) == "__ATMAN_WAIT_REQUESTED__120"

    def test_wait_session_invalid_minutes(self):
        """Test wait_session rejects non-positive minutes."""
        agent_id = uuid4()
        deps, _ = _create_deps_with_session(agent_id)

        ctx = _make_run_context(deps)

        # Test zero
        result_zero = wait_session(ctx, minutes=0)
        assert result_zero.startswith("Error:")
        assert "positive" in result_zero
        assert "0" in result_zero

        # Test negative
        result_negative = wait_session(ctx, minutes=-5)
        assert result_negative.startswith("Error:")
        assert "positive" in result_negative
        assert "-5" in result_negative

    def test_wait_session_no_session(self):
        """Test wait_session works even without active session."""
        agent_id = uuid4()
        state_store = InMemoryStateStore()
        experience_service = ExperienceService(InMemoryExperienceStore())
        event_store = InMemoryReflectionEventStore()
        narrative_revision = NarrativeRevisionService(
            narrative_repo=state_store,  # type: ignore[arg-type]
            reflection_model=MockReflectionModel(),
            narrative_audit=NoOpNarrativeWriteAudit(),
        )

        deps = AtmanDeps(
            session_manager=SessionManager(state_store),
            identity_service=IdentityService(state_store),
            experience_service=experience_service,
            micro_reflection=MicroReflectionService(
                experience_repo=experience_service,  # type: ignore[arg-type]
                narrative_revision=narrative_revision,
                event_store=event_store,
            ),
            state_store=state_store,
            agent_id=agent_id,
            session_id=None,
        )

        ctx = _make_run_context(deps)

        result = wait_session(ctx, minutes=10)

        assert result == "__ATMAN_WAIT_REQUESTED__10"
