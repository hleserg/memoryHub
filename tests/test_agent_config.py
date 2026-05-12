"""
Tests for AtmanDeps and agent configuration models.

Covers:
- AtmanDeps dataclass instantiation and immutability
- AgentConfig validation and defaults
- ModelConfig validation and defaults
"""

from uuid import uuid4

import pytest

from atman.adapters.agent import AgentConfig, AtmanDeps, ModelConfig
from atman.adapters.reflection.mock_reflection_model import MockReflectionModel
from atman.adapters.storage import (
    InMemoryExperienceStore,
    InMemoryStateStore,
)
from atman.adapters.storage.in_memory_reflection_store import (
    InMemoryReflectionEventStore,
)
from atman.core.narrative_write_audit import NoOpNarrativeWriteAudit
from atman.core.services import (
    ExperienceService,
    IdentityService,
    MicroReflectionService,
    NarrativeRevisionService,
    SessionManager,
)


class TestAtmanDeps:
    """Tests for AtmanDeps dataclass."""

    def test_create_deps(self):
        """Test creating AtmanDeps with all required services."""
        state_store = InMemoryStateStore()
        experience_service = ExperienceService(InMemoryExperienceStore())
        event_store = InMemoryReflectionEventStore()
        narrative_revision = NarrativeRevisionService(
            narrative_repo=state_store,  # type: ignore
            reflection_model=MockReflectionModel(),
            narrative_audit=NoOpNarrativeWriteAudit(),
        )
        agent_id = uuid4()

        deps = AtmanDeps(
            session_manager=SessionManager(state_store),
            identity_service=IdentityService(state_store),
            experience_service=experience_service,
            micro_reflection=MicroReflectionService(
                experience_repo=experience_service,  # type: ignore
                narrative_revision=narrative_revision,
                event_store=event_store,
            ),
            state_store=state_store,
            agent_id=agent_id,
        )

        assert deps.agent_id == agent_id
        assert deps.session_id is None
        assert deps.max_tool_calls == 20
        assert deps.truncate_narrative_recent == 2000
        assert deps.truncate_narrative_core == 1000

    def test_deps_immutability(self):
        """Test that AtmanDeps is immutable (frozen dataclass)."""
        state_store = InMemoryStateStore()
        experience_service = ExperienceService(InMemoryExperienceStore())
        event_store = InMemoryReflectionEventStore()
        narrative_revision = NarrativeRevisionService(
            narrative_repo=state_store,  # type: ignore
            reflection_model=MockReflectionModel(),
            narrative_audit=NoOpNarrativeWriteAudit(),
        )
        agent_id = uuid4()

        deps = AtmanDeps(
            session_manager=SessionManager(state_store),
            identity_service=IdentityService(state_store),
            experience_service=experience_service,
            micro_reflection=MicroReflectionService(
                experience_repo=experience_service,  # type: ignore
                narrative_revision=narrative_revision,
                event_store=event_store,
            ),
            state_store=state_store,
            agent_id=agent_id,
        )

        with pytest.raises(AttributeError):
            deps.agent_id = uuid4()  # type: ignore

    def test_deps_with_custom_limits(self):
        """Test creating AtmanDeps with custom configuration."""
        state_store = InMemoryStateStore()
        experience_service = ExperienceService(InMemoryExperienceStore())
        event_store = InMemoryReflectionEventStore()
        narrative_revision = NarrativeRevisionService(
            narrative_repo=state_store,  # type: ignore
            reflection_model=MockReflectionModel(),
            narrative_audit=NoOpNarrativeWriteAudit(),
        )

        deps = AtmanDeps(
            session_manager=SessionManager(state_store),
            identity_service=IdentityService(state_store),
            experience_service=experience_service,
            micro_reflection=MicroReflectionService(
                experience_repo=experience_service,  # type: ignore
                narrative_revision=narrative_revision,
                event_store=event_store,
            ),
            state_store=state_store,
            agent_id=uuid4(),
            max_tool_calls=50,
            truncate_narrative_recent=3000,
            truncate_narrative_core=1500,
        )

        assert deps.max_tool_calls == 50
        assert deps.truncate_narrative_recent == 3000
        assert deps.truncate_narrative_core == 1500

    def test_from_config_transfers_validated_limits(self):
        """AtmanDeps.from_config copies validated limits from AgentConfig."""
        state_store = InMemoryStateStore()
        experience_service = ExperienceService(InMemoryExperienceStore())
        event_store = InMemoryReflectionEventStore()
        narrative_revision = NarrativeRevisionService(
            narrative_repo=state_store,  # type: ignore[arg-type]
            reflection_model=MockReflectionModel(),
            narrative_audit=NoOpNarrativeWriteAudit(),
        )
        config = AgentConfig(
            max_tool_calls=42,
            truncate_narrative_recent=2500,
            truncate_narrative_core=1250,
        )

        deps = AtmanDeps.from_config(
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
            agent_id=uuid4(),
        )

        assert deps.max_tool_calls == 42
        assert deps.truncate_narrative_recent == 2500
        assert deps.truncate_narrative_core == 1250
        assert deps.session_id is None


class TestAgentConfig:
    """Tests for AgentConfig model."""

    def test_default_config(self):
        """Test AgentConfig with all defaults."""
        config = AgentConfig()

        assert config.max_tool_calls == 20
        assert config.truncate_narrative_recent == 2000
        assert config.truncate_narrative_core == 1000
        assert config.enable_experience_search is True
        assert config.enable_key_moments is True
        assert config.model.model == "test"
        assert config.model.temperature == 0.7
        assert config.model.max_tokens == 2000

    def test_custom_config(self):
        """Test AgentConfig with custom values."""
        config = AgentConfig(
            max_tool_calls=30,
            truncate_narrative_recent=1500,
            truncate_narrative_core=800,
            enable_experience_search=False,
        )

        assert config.max_tool_calls == 30
        assert config.truncate_narrative_recent == 1500
        assert config.truncate_narrative_core == 800
        assert config.enable_experience_search is False

    def test_config_validation_max_tool_calls(self):
        """Test that max_tool_calls must be positive."""
        with pytest.raises(ValueError):
            AgentConfig(max_tool_calls=0)

        with pytest.raises(ValueError):
            AgentConfig(max_tool_calls=-5)


class TestModelConfig:
    """Tests for ModelConfig model."""

    def test_default_model_config(self):
        """Test ModelConfig defaults."""
        config = ModelConfig()

        assert config.model == "test"
        assert config.temperature == 0.7
        assert config.max_tokens == 2000

    def test_openai_model(self):
        """Test configuring OpenAI model."""
        config = ModelConfig(model="openai:gpt-4o", temperature=0.5, max_tokens=1000)

        assert config.model == "openai:gpt-4o"
        assert config.temperature == 0.5
        assert config.max_tokens == 1000

    def test_anthropic_model(self):
        """Test configuring Anthropic model."""
        config = ModelConfig(
            model="anthropic:claude-3-5-sonnet-20241022",
            temperature=0.8,
        )

        assert config.model == "anthropic:claude-3-5-sonnet-20241022"
        assert config.temperature == 0.8

    def test_ollama_model(self):
        """Test configuring Ollama model."""
        config = ModelConfig(model="ollama:llama3.2")

        assert config.model == "ollama:llama3.2"

    def test_temperature_validation(self):
        """Test that temperature is validated."""
        with pytest.raises(ValueError):
            ModelConfig(temperature=-0.1)

        with pytest.raises(ValueError):
            ModelConfig(temperature=2.5)

    def test_max_tokens_validation(self):
        """Test that max_tokens must be positive."""
        with pytest.raises(ValueError):
            ModelConfig(max_tokens=0)

        with pytest.raises(ValueError):
            ModelConfig(max_tokens=-100)


def test_agent_factory_experience_adapter_duplicate_reframing_maps_correctly() -> None:
    """_ExperienceAdapter must not report STORED when FileStateStore skips a duplicate."""
    from datetime import UTC, datetime
    from pathlib import Path
    from tempfile import TemporaryDirectory

    from atman.adapters.agent.factory import _ExperienceAdapter
    from atman.adapters.storage import FileStateStore
    from atman.core.models import (
        EmotionalDepth,
        ExperienceRecord,
        FeltSense,
        KeyMoment,
        ReframingNote,
        SessionExperience,
    )
    from atman.core.models.experience import ReframingNoteAppendResult

    with TemporaryDirectory() as tmp:
        store = FileStateStore(Path(tmp))
        sid = uuid4()
        felt = FeltSense(
            emotional_valence=0.1,
            emotional_intensity=0.5,
            depth=EmotionalDepth.SURFACE,
        )
        moment = KeyMoment(what_happened="ev", how_i_felt=felt, why_it_matters="y")
        exp = SessionExperience(
            session_id=sid,
            key_moments=[moment],
            importance=0.5,
            salience=0.5,
            timestamp=datetime.now(UTC),
        )
        rec = ExperienceRecord(experience=exp)
        store.create_experience(rec)
        adapter = _ExperienceAdapter(store)
        eid = rec.experience.id
        note = ReframingNote(
            reflection="first",
            reflection_type="growth",
            triggered_by="run-dup-test",
        )
        assert adapter.add_reframing_note(eid, note) == ReframingNoteAppendResult.STORED
        dup = ReframingNote(
            reflection="second body",
            reflection_type="growth",
            triggered_by="run-dup-test",
        )
        assert (
            adapter.add_reframing_note(eid, dup) == ReframingNoteAppendResult.DUPLICATE_TRIGGERED_BY
        )
