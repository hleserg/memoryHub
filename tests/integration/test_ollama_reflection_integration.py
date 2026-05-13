"""
Integration tests for OllamaReflectionModel against a live Ollama instance.

All tests are marked ``requires_ollama`` and auto-skip when Ollama is
unreachable or the default chat model is not listed in ``/api/tags``
(see ``tests/conftest.py``; override with ``ATMAN_OLLAMA_MODEL``).

Tests are also marked ``slow`` so ``pytest -m "not slow"`` (CI quick gate)
does not depend on live inference; run this module explicitly for smoke checks.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from atman.adapters.reflection.ollama_reflection_model import OllamaReflectionModel
from atman.core.models.experience import (
    EmotionalDepth,
    FeltSense,
    KeyMoment,
    SessionExperience,
)
from atman.core.models.identity import CoreValue, Identity, Principle
from atman.core.models.narrative import LayerType, NarrativeDocument, NarrativeLayer
from atman.core.models.reflection import (
    HealthCriterionOutput,
    JahodaCriterion,
    NarrativeUpdateOutput,
    PatternDetectionOutput,
    ReflectionLevel,
    ReframingNoteOutput,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_experience(summary: str = "Test event") -> SessionExperience:
    """Create a minimal valid SessionExperience for integration probes."""
    km = KeyMoment(
        what_happened=summary,
        how_i_felt=FeltSense(
            emotional_valence=0.4,
            emotional_intensity=0.5,
            depth=EmotionalDepth.MEANINGFUL,
        ),
        why_it_matters="Integration test significance",
        values_touched=["curiosity"],
    )
    return SessionExperience(
        session_id=uuid4(),
        timestamp=datetime.now(UTC),
        key_moment_ids=[km.id],
        avg_emotional_intensity=km.how_i_felt.emotional_intensity,
        has_profound_moment=km.how_i_felt.depth == EmotionalDepth.PROFOUND,
    )


def _make_identity() -> Identity:
    """Create a minimal valid Identity."""
    return Identity(
        self_description="A curious AI agent exploring its own reflection capabilities.",
        core_values=[
            CoreValue(name="curiosity", description="Desire to learn and understand"),
        ],
        principles=[
            Principle(statement="Always seek understanding before action"),
        ],
    )


def _make_narrative() -> NarrativeDocument:
    """Create a minimal valid NarrativeDocument."""
    return NarrativeDocument(
        identity_id=uuid4(),
        core_layer=NarrativeLayer(
            layer_type=LayerType.CORE,
            content="I am an AI exploring self-awareness.",
        ),
        recent_layer=NarrativeLayer(
            layer_type=LayerType.RECENT,
            content="Today I began integration testing.",
        ),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.requires_ollama
class TestOllamaReflectionIntegration:
    """Smoke tests against a live Ollama instance with qwen3.5:9b."""

    def test_generate_reframing_note_live(self) -> None:
        """Live: generate_reframing_note returns a valid ReframingNoteOutput."""
        experience = _make_experience("Helped a user debug a complex issue")

        with OllamaReflectionModel() as model:
            result = model.generate_reframing_note(experience, {})

        assert isinstance(result, ReframingNoteOutput)
        assert isinstance(result.reflection, str)
        assert isinstance(result.reflection_type, str)

    def test_detect_patterns_live(self) -> None:
        """Live: detect_pattern returns a valid PatternDetectionOutput."""
        experiences = [
            _make_experience("Helped user debug issue A"),
            _make_experience("Helped user debug issue B"),
            _make_experience("Helped user debug issue C"),
        ]

        with OllamaReflectionModel() as model:
            result = model.detect_pattern(experiences, {})

        assert isinstance(result, PatternDetectionOutput)
        assert isinstance(result.description, str)

    def test_update_narrative_live(self) -> None:
        """Live: propose_narrative_update returns a valid NarrativeUpdateOutput."""
        narrative = _make_narrative()
        experiences = [_make_experience("Learned about reflection capabilities")]

        with OllamaReflectionModel() as model:
            result = model.propose_narrative_update(
                narrative,
                experiences,
                ReflectionLevel.MICRO,
            )

        assert isinstance(result, NarrativeUpdateOutput)
        assert isinstance(result.body, str)

    def test_assess_health_criterion_live(self) -> None:
        """Live: assess_health_criterion returns a valid HealthCriterionOutput."""
        identity = _make_identity()
        experiences = [_make_experience("Demonstrated autonomy in decision-making")]

        with OllamaReflectionModel() as model:
            result = model.assess_health_criterion(
                identity,
                experiences,
                JahodaCriterion.AUTONOMY,
            )

        assert isinstance(result, HealthCriterionOutput)
        assert 0.0 <= result.score <= 1.0
        assert isinstance(result.evidence, list)
        assert isinstance(result.concerns, list)
