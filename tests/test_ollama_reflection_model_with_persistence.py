"""Regression tests for OllamaReflectionModelWithPersistence resource cleanup.

Devin Review on PR #414 flagged that the ``__enter__`` / ``__exit__`` /
``close`` methods could leak the PostgreSQL ``ReflectionStore`` connection
or the base model's HTTP client when the other side raised. These tests
exercise both happy-path and failure-path cleanup.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from atman.adapters.reflection.ollama_reflection_model_with_persistence import (
    OllamaReflectionModelWithPersistence,
)

if TYPE_CHECKING:
    from uuid import UUID

    from atman.core.models.experience import SessionExperience
    from atman.core.models.identity import Identity
    from atman.core.models.narrative import NarrativeDocument


def _build_model(
    base_model: MagicMock, store: MagicMock | None
) -> OllamaReflectionModelWithPersistence:
    """Create the wrapper without invoking the real Ollama / DB constructors."""
    model = OllamaReflectionModelWithPersistence.__new__(OllamaReflectionModelWithPersistence)
    model.base_model = base_model
    model.reflection_store = store
    return model


class TestEnterExitCleanup:
    """Context-manager protocol must not leak resources on partial failures."""

    def test_enter_exit_happy_path_calls_both_sides(self) -> None:
        base_model = MagicMock()
        store = MagicMock()

        model = _build_model(base_model, store)
        with model:
            base_model.__enter__.assert_called_once()
            store.connect.assert_called_once()

        base_model.__exit__.assert_called_once()
        store.close.assert_called_once()

    def test_enter_unwinds_base_model_when_store_connect_fails(self) -> None:
        """If store.connect() raises, the already-entered base_model is closed."""
        base_model = MagicMock()
        store = MagicMock()
        store.connect.side_effect = RuntimeError("db unavailable")

        model = _build_model(base_model, store)

        with pytest.raises(RuntimeError, match="db unavailable"):
            model.__enter__()

        base_model.__enter__.assert_called_once()
        # The wrapper must have unwound the base model on the failed entry.
        base_model.__exit__.assert_called_once_with(None, None, None)

    def test_exit_closes_store_even_if_base_model_exit_raises(self) -> None:
        """``ReflectionStore.close()`` must run even when base_model.__exit__ raises."""
        base_model = MagicMock()
        base_model.__exit__.side_effect = RuntimeError("ollama exit failed")
        store = MagicMock()

        model = _build_model(base_model, store)

        with pytest.raises(RuntimeError, match="ollama exit failed"):
            model.__exit__(None, None, None)

        store.close.assert_called_once()


class TestCloseCleanup:
    """Explicit ``close()`` mirrors __exit__'s guarantees."""

    def test_close_releases_store_when_base_close_raises(self) -> None:
        base_model = MagicMock()
        base_model.close.side_effect = RuntimeError("ollama close failed")
        store = MagicMock()

        model = _build_model(base_model, store)

        with pytest.raises(RuntimeError, match="ollama close failed"):
            model.close()

        store.close.assert_called_once()

    def test_close_without_store_only_closes_base(self) -> None:
        base_model = MagicMock()

        model = _build_model(base_model, store=None)
        model.close()

        base_model.close.assert_called_once()


class TestPersistedReflectionMethods:
    """Each high-level reflection method must persist its output (best-effort)."""

    def _identity(self) -> Identity:
        from atman.core.models.identity import CoreValue, Identity

        return Identity(
            self_description="x",
            core_values=[CoreValue(name="v", description="d", confidence=0.5)],
            emotional_baseline=0.0,
        )

    def _narrative(self, identity_id: UUID) -> NarrativeDocument:
        from atman.core.models.narrative import (
            LayerType,
            NarrativeDocument,
            NarrativeLayer,
        )

        return NarrativeDocument(
            identity_id=identity_id,
            core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="core"),
            recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="recent"),
        )

    def _experience(self) -> SessionExperience:
        from uuid import uuid4

        from atman.core.models.experience import (
            EmotionalDepth,
            FeltSense,
            KeyMoment,
            SessionExperience,
        )

        felt = FeltSense(
            emotional_valence=0.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
        )
        moment = KeyMoment(
            what_happened="thing happened",
            how_i_felt=felt,
            why_it_matters="for testing",
        )
        return SessionExperience(session_id=uuid4(), key_moments=[moment])

    def test_generate_reframing_note_persists_with_valid_agent_id(self) -> None:
        from uuid import uuid4

        from atman.core.models.reflection import ReflectionLevel, ReframingNoteOutput

        agent_id = uuid4()
        base_model = MagicMock()
        base_model.model = "qwen3.5:9b"
        base_model.generate_reframing_note.return_value = ReframingNoteOutput(
            reflection="reframed", reflection_type="growth"
        )
        store = MagicMock()
        wrapper = _build_model(base_model, store)
        wrapper._persistence_enabled = True

        exp = self._experience()
        out = wrapper.generate_reframing_note(exp, {"agent_id": str(agent_id)})

        assert out.reflection == "reframed"
        store.add.assert_called_once()
        event = store.add.call_args.args[0]
        assert event.agent_id == agent_id
        assert event.level == ReflectionLevel.MICRO.value
        assert event.session_id == exp.session_id

    def test_generate_reframing_note_silent_with_invalid_agent_id(self) -> None:
        from atman.core.models.reflection import ReframingNoteOutput

        base_model = MagicMock()
        base_model.model = "qwen3.5:9b"
        base_model.generate_reframing_note.return_value = ReframingNoteOutput(reflection="reframed")
        store = MagicMock()
        wrapper = _build_model(base_model, store)
        wrapper._persistence_enabled = True

        out = wrapper.generate_reframing_note(self._experience(), {"agent_id": "not-a-uuid"})

        assert out.reflection == "reframed"
        store.add.assert_not_called()

    def test_generate_reframing_note_skips_persist_when_empty(self) -> None:
        from atman.core.models.reflection import ReframingNoteOutput

        base_model = MagicMock()
        base_model.model = "qwen3.5:9b"
        base_model.generate_reframing_note.return_value = ReframingNoteOutput(reflection="")
        store = MagicMock()
        wrapper = _build_model(base_model, store)
        wrapper._persistence_enabled = True

        wrapper.generate_reframing_note(self._experience(), {"agent_id": "irrelevant"})

        store.add.assert_not_called()

    def test_detect_pattern_persists_with_valid_agent_id(self) -> None:
        from uuid import uuid4

        from atman.core.models.reflection import (
            PatternDetectionOutput,
            ReflectionLevel,
        )

        agent_id = uuid4()
        base_model = MagicMock()
        base_model.model = "qwen3.5:9b"
        base_model.detect_pattern.return_value = PatternDetectionOutput(
            description="d" * 250,  # >100 chars triggers summary truncation
        )
        store = MagicMock()
        wrapper = _build_model(base_model, store)
        wrapper._persistence_enabled = True

        wrapper.detect_pattern([self._experience()], {"agent_id": str(agent_id)})

        store.add.assert_called_once()
        event = store.add.call_args.args[0]
        assert event.level == ReflectionLevel.DAILY.value
        assert event.summary is not None
        assert len(event.summary) <= 100

    def test_detect_pattern_no_agent_id_skips_persist(self) -> None:
        from atman.core.models.reflection import PatternDetectionOutput

        base_model = MagicMock()
        base_model.model = "qwen3.5:9b"
        base_model.detect_pattern.return_value = PatternDetectionOutput(description="x")
        store = MagicMock()
        wrapper = _build_model(base_model, store)
        wrapper._persistence_enabled = True

        wrapper.detect_pattern([self._experience()], {})

        store.add.assert_not_called()

    def test_propose_narrative_update_uses_identity_id(self) -> None:
        from atman.core.models.reflection import NarrativeUpdateOutput, ReflectionLevel

        ident = self._identity()
        narrative = self._narrative(ident.id)

        base_model = MagicMock()
        base_model.model = "qwen3.5:9b"
        base_model.propose_narrative_update.return_value = NarrativeUpdateOutput(body="upd")
        store = MagicMock()
        wrapper = _build_model(base_model, store)
        wrapper._persistence_enabled = True

        wrapper.propose_narrative_update(narrative, [self._experience()], ReflectionLevel.DAILY)

        store.add.assert_called_once()
        event = store.add.call_args.args[0]
        # Persistence uses identity_id as agent_id (not narrative.id).
        assert event.agent_id == ident.id
        assert event.level == ReflectionLevel.DAILY.value

    def test_propose_narrative_update_skips_when_body_empty(self) -> None:
        from atman.core.models.reflection import NarrativeUpdateOutput, ReflectionLevel

        ident = self._identity()
        narrative = self._narrative(ident.id)

        base_model = MagicMock()
        base_model.model = "qwen3.5:9b"
        base_model.propose_narrative_update.return_value = NarrativeUpdateOutput(body="")
        store = MagicMock()
        wrapper = _build_model(base_model, store)
        wrapper._persistence_enabled = True

        wrapper.propose_narrative_update(narrative, [], ReflectionLevel.DAILY)
        store.add.assert_not_called()

    def test_assess_health_criterion_uses_identity_id_and_assembles_content(self) -> None:
        from atman.core.models.reflection import (
            HealthCriterionOutput,
            JahodaCriterion,
            ReflectionLevel,
        )

        base_model = MagicMock()
        base_model.model = "qwen3.5:9b"
        base_model.assess_health_criterion.return_value = HealthCriterionOutput(
            score=0.7, evidence=["e1", "e2"], concerns=["c1"]
        )
        store = MagicMock()
        ident = self._identity()
        wrapper = _build_model(base_model, store)
        wrapper._persistence_enabled = True

        wrapper.assess_health_criterion(ident, [self._experience()], JahodaCriterion.AUTONOMY)

        store.add.assert_called_once()
        event = store.add.call_args.args[0]
        assert event.level == ReflectionLevel.DEEP.value
        assert event.agent_id == ident.id
        # Evidence and concerns are folded into the persisted content.
        assert "Evidence: e1, e2" in event.content
        assert "Concerns: c1" in event.content


class TestPersistReflectionGuards:
    """The persistence helper must respect the disabled flag and swallow errors."""

    def test_persist_reflection_noop_when_disabled(self) -> None:
        from uuid import uuid4

        from atman.core.models.reflection import ReflectionLevel

        base_model = MagicMock()
        base_model.model = "qwen3.5:9b"
        store = MagicMock()
        wrapper = _build_model(base_model, store)
        wrapper._persistence_enabled = False

        wrapper._persist_reflection(agent_id=uuid4(), level=ReflectionLevel.MICRO, content="x")
        store.add.assert_not_called()

    def test_persist_reflection_swallows_store_failures(self) -> None:
        from uuid import uuid4

        from atman.core.models.reflection import ReflectionLevel

        base_model = MagicMock()
        base_model.model = "qwen3.5:9b"
        store = MagicMock()
        store.add.side_effect = RuntimeError("boom")
        wrapper = _build_model(base_model, store)
        wrapper._persistence_enabled = True

        # Must NOT propagate — persistence is best-effort.
        wrapper._persist_reflection(agent_id=uuid4(), level=ReflectionLevel.MICRO, content="x")
        store.add.assert_called_once()
