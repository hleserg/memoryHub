"""
Tests for dynamic instructions builder and memory context builder.

Covers:
- build_instructions: behavioral rules only (identity-free)
- build_memory_context: full memory bundle (identity + narrative + prev session)
- Bootstrap instructions for empty identity
- Text truncation for context limits
- Selective rendering of identity components
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from atman.adapters.agent import build_instructions
from atman.adapters.agent.deps import AtmanDeps
from atman.adapters.agent.instructions import build_memory_context
from atman.adapters.reflection.mock_reflection_model import MockReflectionModel
from atman.adapters.storage import InMemoryExperienceStore, InMemoryStateStore
from atman.adapters.storage.in_memory_reflection_store import InMemoryReflectionEventStore
from atman.core.models import (
    CoreValue,
    Goal,
    Identity,
    LayerType,
    NarrativeDocument,
    NarrativeLayer,
    Principle,
)
from atman.core.narrative_write_audit import NoOpNarrativeWriteAudit
from atman.core.services import (
    ExperienceService,
    IdentityService,
    MicroReflectionService,
    NarrativeRevisionService,
    SessionManager,
)


def _create_deps(agent_id: UUID) -> AtmanDeps:
    """Helper to create deps for testing."""
    state_store = InMemoryStateStore()
    experience_service = ExperienceService(InMemoryExperienceStore())
    event_store = InMemoryReflectionEventStore()
    narrative_revision = NarrativeRevisionService(
        narrative_repo=state_store,  # type: ignore[arg-type]
        reflection_model=MockReflectionModel(),
        narrative_audit=NoOpNarrativeWriteAudit(),
    )

    return AtmanDeps(
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


class TestBuildInstructions:
    """Tests for build_instructions function."""

    def test_bootstrap_instructions_empty_identity(self):
        """Test bootstrap instructions when no identity exists."""
        agent_id = uuid4()
        deps = _create_deps(agent_id)

        instructions = build_instructions(deps)

        assert "Bootstrap Agent" in instructions
        assert "earliest stage of existence" in instructions
        assert "no accumulated experience" in instructions
        assert str(agent_id) in instructions

    def test_full_identity_instructions(self):
        """Test instructions with complete identity and narrative."""
        agent_id = uuid4()
        deps = _create_deps(agent_id)

        # Create full identity
        identity = Identity(
            id=agent_id,
            self_description="I am a helpful AI assistant learning to be more thoughtful.",
            core_values=[
                CoreValue(
                    name="honesty",
                    description="Being truthful even when uncomfortable",
                    confidence=0.8,
                ),
                CoreValue(
                    name="curiosity",
                    description="Asking questions to understand deeply",
                    confidence=0.7,
                ),
            ],
            principles=[
                Principle(
                    statement="Always admit when I don't know something",
                    chosen_consciously=True,
                ),
            ],
            goals=[
                Goal(
                    content="Learn to provide more helpful responses",
                    active=True,
                ),
            ],
            habits=[],
            priorities=[],
            open_questions=[],
        )
        deps.state_store.save_identity(identity)

        # Create narrative
        narrative = NarrativeDocument(
            id=uuid4(),
            identity_id=agent_id,
            core_layer=NarrativeLayer(
                layer_type=LayerType.CORE,
                content="I am building my core understanding through experience.",
            ),
            recent_layer=NarrativeLayer(
                layer_type=LayerType.RECENT,
                content="Recently I helped several users with coding questions.",
            ),
            threads=[],
            updated_at=datetime.now(UTC),
        )
        deps.state_store.save_narrative(narrative)

        # Memory content is in build_memory_context, not build_instructions
        memory = build_memory_context(deps)

        assert "helpful AI assistant" in memory
        assert "honesty" in memory
        assert "curiosity" in memory
        assert "admit when I don't know" in memory
        assert "helpful responses" in memory
        assert "core understanding" in memory
        assert "coding questions" in memory

        # build_instructions only has behavioral guide, not personal content
        instructions = build_instructions(deps)
        assert "helpful AI assistant" not in instructions
        assert "Как я работаю" in instructions

    def test_truncation_long_narrative(self):
        """Test that long narratives are truncated properly."""
        agent_id = uuid4()
        deps = _create_deps(agent_id)

        # Create identity
        identity = Identity(
            id=agent_id,
            self_description="Test agent",
            core_values=[],
            principles=[],
            goals=[],
            habits=[],
            priorities=[],
            open_questions=[],
        )
        deps.state_store.save_identity(identity)

        # Create narrative with very long recent_layer
        long_text = "A" * 5000  # Much longer than truncate limit (2000)
        narrative = NarrativeDocument(
            id=uuid4(),
            identity_id=agent_id,
            core_layer=NarrativeLayer(
                layer_type=LayerType.CORE,
                content="Short core",
            ),
            recent_layer=NarrativeLayer(
                layer_type=LayerType.RECENT,
                content=long_text,
            ),
            threads=[],
            updated_at=datetime.now(UTC),
        )
        deps.state_store.save_narrative(narrative)

        memory = build_memory_context(deps)

        # Check truncation happened
        assert len(memory) < len(long_text)
        assert "..." in memory
        assert long_text not in memory

    def test_empty_narrative_layers(self):
        """Test instructions when narrative layers are empty."""
        agent_id = uuid4()
        deps = _create_deps(agent_id)

        identity = Identity(
            id=agent_id,
            self_description="Test agent",
            core_values=[],
            principles=[],
            goals=[],
            habits=[],
            priorities=[],
            open_questions=[],
        )
        deps.state_store.save_identity(identity)

        narrative = NarrativeDocument(
            id=uuid4(),
            identity_id=agent_id,
            core_layer=NarrativeLayer(
                layer_type=LayerType.CORE,
                content="",
            ),
            recent_layer=NarrativeLayer(
                layer_type=LayerType.RECENT,
                content="",
            ),
            threads=[],
            updated_at=datetime.now(UTC),
        )
        deps.state_store.save_narrative(narrative)

        memory = build_memory_context(deps)

        # Empty narrative layers should not produce section headers
        assert "Нарратив (основа)" not in memory
        assert "Нарратив (недавнее)" not in memory
        # But identity section should be present
        assert "Кто я" in memory

    def test_selective_principles(self):
        """Test that only consciously chosen principles are included."""
        agent_id = uuid4()
        deps = _create_deps(agent_id)

        identity = Identity(
            id=agent_id,
            self_description="Test",
            core_values=[],
            principles=[
                Principle(
                    statement="Conscious principle",
                    chosen_consciously=True,
                ),
                Principle(
                    statement="Observed principle",
                    chosen_consciously=False,
                ),
            ],
            goals=[],
            habits=[],
            priorities=[],
            open_questions=[],
        )
        deps.state_store.save_identity(identity)

        memory = build_memory_context(deps)

        assert "Conscious principle" in memory
        assert "Observed principle" not in memory

    def test_active_goals_only(self):
        """Test that only active goals are included."""
        agent_id = uuid4()
        deps = _create_deps(agent_id)

        identity = Identity(
            id=agent_id,
            self_description="Test",
            core_values=[],
            principles=[],
            goals=[
                Goal(
                    content="Active goal",
                    active=True,
                ),
                Goal(
                    content="Inactive goal",
                    active=False,
                ),
            ],
            habits=[],
            priorities=[],
            open_questions=[],
        )
        deps.state_store.save_identity(identity)

        memory = build_memory_context(deps)

        assert "Active goal" in memory
        assert "Inactive goal" not in memory

    def test_skips_empty_principles_and_goals_headers(self):
        """No header should be emitted if every principle is unconscious or every goal inactive."""
        agent_id = uuid4()
        deps = _create_deps(agent_id)

        identity = Identity(
            id=agent_id,
            self_description="Test",
            core_values=[],
            principles=[
                Principle(
                    statement="Observed but not chosen",
                    chosen_consciously=False,
                ),
            ],
            goals=[
                Goal(
                    content="Old goal",
                    active=False,
                ),
            ],
            habits=[],
            priorities=[],
            open_questions=[],
        )
        deps.state_store.save_identity(identity)

        memory = build_memory_context(deps)

        assert "Принципы" not in memory
        assert "Цели" not in memory
        assert "Observed but not chosen" not in memory
        assert "Old goal" not in memory
        assert "Inactive goal" not in memory
