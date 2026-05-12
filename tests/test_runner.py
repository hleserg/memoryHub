"""
Tests for AgentRunner with token monitoring.

Covers:
- 70/80/90/95% threshold warnings
- Forced close at 95%
- Reset triggers on restart
- Context limit enforcement
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from pydantic_ai.usage import RunUsage

from atman.adapters.agent import (
    AgentConfig,
    AgentRunner,
    AtmanDeps,
    ContextLimitExceeded,
    ModelConfig,
)
from atman.adapters.reflection.mock_reflection_model import MockReflectionModel
from atman.adapters.storage import InMemoryExperienceStore, InMemoryStateStore
from atman.adapters.storage.in_memory_reflection_store import InMemoryReflectionEventStore
from atman.core.narrative_write_audit import NoOpNarrativeWriteAudit
from atman.core.services import (
    ExperienceService,
    IdentityService,
    MicroReflectionService,
    NarrativeRevisionService,
    SessionManager,
)


def _create_deps(
    agent_id: UUID,
    context_limit: int = 1000,
    model: str = "test",
) -> AtmanDeps:
    """Create AtmanDeps for testing with custom context limit."""
    state_store = InMemoryStateStore()
    experience_service = ExperienceService(InMemoryExperienceStore())
    event_store = InMemoryReflectionEventStore()
    narrative_revision = NarrativeRevisionService(
        narrative_repo=state_store,  # type: ignore[arg-type]
        reflection_model=MockReflectionModel(),
        narrative_audit=NoOpNarrativeWriteAudit(),
    )

    model_config = ModelConfig(
        model=model,
        context_limit=context_limit,
    )

    config = AgentConfig(model=model_config)

    return AtmanDeps.from_config(
        config=config,
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
    )


class TestAgentRunner:
    """Tests for AgentRunner token monitoring."""

    def test_runner_initialization(self):
        """Test AgentRunner initializes correctly."""
        agent_id = uuid4()
        deps = _create_deps(agent_id)

        runner = AgentRunner(deps=deps)

        assert runner._deps == deps
        assert runner._triggered == set()
        assert runner._agent is not None

    @pytest.mark.asyncio
    async def test_no_threshold_warning_below_70(self):
        """Test no warnings when usage is below 70%."""
        agent_id = uuid4()
        deps = _create_deps(agent_id, context_limit=1000)

        runner = AgentRunner(deps=deps)

        # Mock agent.run to return 600 input tokens (60%)
        mock_result = MagicMock()
        mock_result.usage.return_value = RunUsage(
            input_tokens=600,
            output_tokens=100,
        )
        mock_result.response = "Response"

        runner._agent.run = AsyncMock(return_value=mock_result)

        result = await runner.run("Test message")

        assert result.response == "Response"
        assert runner._triggered == set()

    @pytest.mark.asyncio
    async def test_70_threshold_warning(self):
        """Test warning at 70% threshold."""
        agent_id = uuid4()
        deps = _create_deps(agent_id, context_limit=1000)

        runner = AgentRunner(deps=deps)

        # Mock agent.run to return 720 input tokens (72%)
        mock_result = MagicMock()
        mock_result.usage.return_value = RunUsage(
            input_tokens=720,
            output_tokens=50,
        )
        mock_result.response = "Response"

        runner._agent.run = AsyncMock(return_value=mock_result)

        result = await runner.run("Test message")

        assert result.response == "Response"
        assert 70 in runner._triggered
        assert 80 not in runner._triggered

    @pytest.mark.asyncio
    async def test_80_threshold_warning(self):
        """Test warning at 80% threshold."""
        agent_id = uuid4()
        deps = _create_deps(agent_id, context_limit=1000)

        runner = AgentRunner(deps=deps)

        # Mock agent.run to return 820 input tokens (82%)
        mock_result = MagicMock()
        mock_result.usage.return_value = RunUsage(
            input_tokens=820,
            output_tokens=50,
        )
        mock_result.response = "Response"

        runner._agent.run = AsyncMock(return_value=mock_result)

        result = await runner.run("Test message")

        assert result.response == "Response"
        assert 70 in runner._triggered
        assert 80 in runner._triggered
        assert 90 not in runner._triggered

    @pytest.mark.asyncio
    async def test_90_threshold_warning(self):
        """Test warning at 90% threshold."""
        agent_id = uuid4()
        deps = _create_deps(agent_id, context_limit=1000)

        runner = AgentRunner(deps=deps)

        # Mock agent.run to return 920 input tokens (92%)
        mock_result = MagicMock()
        mock_result.usage.return_value = RunUsage(
            input_tokens=920,
            output_tokens=50,
        )
        mock_result.response = "Response"

        runner._agent.run = AsyncMock(return_value=mock_result)

        result = await runner.run("Test message")

        assert result.response == "Response"
        assert 70 in runner._triggered
        assert 80 in runner._triggered
        assert 90 in runner._triggered
        assert 95 not in runner._triggered

    @pytest.mark.asyncio
    async def test_95_threshold_forced_close(self):
        """Test forced close at 95% threshold."""
        agent_id = uuid4()
        deps = _create_deps(agent_id, context_limit=1000)

        runner = AgentRunner(deps=deps)

        # Mock agent.run to return 960 input tokens (96%)
        mock_result = MagicMock()
        mock_result.usage.return_value = RunUsage(
            input_tokens=960,
            output_tokens=20,
        )
        mock_result.response = "Response"

        runner._agent.run = AsyncMock(return_value=mock_result)

        with pytest.raises(ContextLimitExceeded) as exc_info:
            await runner.run("Test message")

        assert "95%" in str(exc_info.value)
        assert 95 in runner._triggered

    @pytest.mark.asyncio
    async def test_threshold_triggered_only_once(self):
        """Test each threshold triggers warning only once."""
        agent_id = uuid4()
        deps = _create_deps(agent_id, context_limit=1000)

        runner = AgentRunner(deps=deps)

        # First run at 75%
        mock_result_1 = MagicMock()
        mock_result_1.usage.return_value = RunUsage(
            input_tokens=750,
            output_tokens=50,
        )
        mock_result_1.data = "Response 1"

        runner._agent.run = AsyncMock(return_value=mock_result_1)
        await runner.run("Message 1")

        assert 70 in runner._triggered
        triggered_after_first = runner._triggered.copy()

        # Second run still at 75% - should not trigger again
        mock_result_2 = MagicMock()
        mock_result_2.usage.return_value = RunUsage(
            input_tokens=750,
            output_tokens=50,
        )
        mock_result_2.data = "Response 2"

        runner._agent.run = AsyncMock(return_value=mock_result_2)
        await runner.run("Message 2")

        assert runner._triggered == triggered_after_first

    def test_reset_triggers(self):
        """Test reset_triggers clears all thresholds."""
        agent_id = uuid4()
        deps = _create_deps(agent_id)

        runner = AgentRunner(deps=deps)
        runner._triggered = {70, 80, 90}

        runner.reset_triggers()

        assert runner._triggered == set()

    @pytest.mark.asyncio
    async def test_no_usage_data(self):
        """Test runner handles missing usage data gracefully."""
        agent_id = uuid4()
        deps = _create_deps(agent_id)

        runner = AgentRunner(deps=deps)

        # Mock agent.run with no usage data
        mock_result = MagicMock()
        mock_result.usage.return_value = None
        mock_result.response = "Response"

        runner._agent.run = AsyncMock(return_value=mock_result)

        result = await runner.run("Test message")

        assert result.response == "Response"
        assert runner._triggered == set()

    @pytest.mark.asyncio
    async def test_default_context_limit_when_model_config_missing(self):
        """Test default context limit when model_config is None."""
        agent_id = uuid4()
        state_store = InMemoryStateStore()
        experience_service = ExperienceService(InMemoryExperienceStore())
        event_store = InMemoryReflectionEventStore()
        narrative_revision = NarrativeRevisionService(
            narrative_repo=state_store,  # type: ignore[arg-type]
            reflection_model=MockReflectionModel(),
            narrative_audit=NoOpNarrativeWriteAudit(),
        )

        # Create deps without model_config
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
            model_config=None,
        )

        runner = AgentRunner(deps=deps)

        # Mock agent.run with 6000 tokens (73% of default 8192)
        mock_result = MagicMock()
        mock_result.usage.return_value = RunUsage(
            input_tokens=6000,
            output_tokens=200,
        )
        mock_result.response = "Response"

        runner._agent.run = AsyncMock(return_value=mock_result)

        result = await runner.run("Test message")

        assert result.response == "Response"
        assert 70 in runner._triggered
