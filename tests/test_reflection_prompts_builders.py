"""Exercise reflection prompt builders for coverage (schema + experience summaries)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from atman.adapters.reflection.prompts import (
    SYSTEM_PROMPT_STANCE,
    build_health_messages,
    build_narrative_messages,
    build_pattern_messages,
    build_reframing_messages,
    build_stance_formulation_messages,
)
from atman.core.models.entity import Entity, EntityType
from atman.core.models.experience import (
    EmotionalDepth,
    FeltSense,
    KeyMoment,
    SessionExperience,
)
from atman.core.models.identity import CoreValue, Identity, Principle
from atman.core.models.narrative import LayerType, NarrativeDocument, NarrativeLayer
from atman.core.models.reflection import JahodaCriterion, ReflectionLevel


def _km(values_touched: list[str] | None = None) -> KeyMoment:
    return KeyMoment(
        what_happened="User asked for a difficult refactor.",
        how_i_felt=FeltSense(
            emotional_valence=-0.1,
            emotional_intensity=0.6,
            depth=EmotionalDepth.MEANINGFUL,
        ),
        why_it_matters="Technical honesty under pressure.",
        values_touched=list(values_touched or []),
    )


def _session(km: KeyMoment) -> SessionExperience:
    return SessionExperience(
        session_id=uuid4(),
        timestamp=datetime(2025, 3, 1, 12, 0, tzinfo=UTC),
        key_moment_ids=[km.id],
        avg_emotional_intensity=km.how_i_felt.emotional_intensity,
        has_profound_moment=km.how_i_felt.depth == EmotionalDepth.PROFOUND,
    )


def test_build_reframing_messages_includes_context_and_values() -> None:
    exp = _session(_km(["honesty"]))
    msgs = build_reframing_messages(exp, {"note": "extra"})
    assert msgs[0]["role"] == "system"
    assert "Experience" in msgs[1]["content"]
    assert "key moments" in msgs[1]["content"].lower()
    assert "extra" in msgs[1]["content"]


def test_build_pattern_messages_multi_experience_and_context() -> None:
    exps = [_session(_km()), _session(_km(["care"]))]
    msgs = build_pattern_messages(exps, {"scope": "week"})
    body = msgs[1]["content"]
    assert body.count("Session ") >= 2
    assert "scope" in body


def test_build_narrative_messages_lists_experiences() -> None:
    narrative = NarrativeDocument(
        identity_id=uuid4(),
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="core c"),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="recent r"),
    )
    exp = _session(_km())
    msgs = build_narrative_messages(
        narrative,
        [exp],
        ReflectionLevel.MICRO,
    )
    assert "Core layer: core c" in msgs[1]["content"]
    assert "Recent Experiences" in msgs[1]["content"]


def test_build_health_messages_minimal_identity_no_lists() -> None:
    ident = Identity(
        id=uuid4(),
        self_description="Bare minimum identity for prompt smoke.",
        core_values=[],
        goals=[],
        emotional_baseline=0.0,
        principles=[],
    )
    msgs = build_health_messages(ident, [], JahodaCriterion.AUTONOMY)
    assert "Bare minimum" in msgs[1]["content"]
    assert "## Recent Experiences" in msgs[1]["content"]


def test_build_health_messages_identity_fields_and_experiences() -> None:
    ident = Identity(
        id=uuid4(),
        self_description="I value clarity.",
        core_values=[CoreValue(name="truth", description="say true things", confidence=0.7)],
        goals=[],
        emotional_baseline=0.0,
        principles=[Principle(statement="Be direct.")],
    )
    exp = _session(_km())
    msgs = build_health_messages(
        ident,
        [exp],
        JahodaCriterion.REALITY_PERCEPTION,
    )
    body = msgs[1]["content"]
    assert "truth" in body
    assert "Be direct" in body
    assert "Session " in body


# ---------------------------------------------------------------------------
# R7 — stance formulation prompt
# ---------------------------------------------------------------------------


def test_build_stance_formulation_messages_includes_entity_moments_and_markers() -> None:
    entity = Entity(
        agent_id=uuid4(),
        canonical_name="Vermont",
        entity_type=EntityType.place,
        description="A US state I keep coming back to.",
    )
    km1 = _km(["honesty"])
    km1.structured_markers = {"cognitive_load": "low", "trust_signal": "warm"}
    km2 = _km(["care"])
    msgs = build_stance_formulation_messages(
        entity,
        [km1, km2],
        structured_markers={"cognitive_load": 1, "trust_signal": 1},
    )
    assert msgs[0]["role"] == "system"
    # System prompt enforces interpretation, not aggregation (§9).
    assert "interpretation" in msgs[0]["content"].lower()
    assert "aggregation" in msgs[0]["content"].lower()
    user = msgs[1]["content"]
    assert "Vermont" in user
    assert "place" in user
    assert "A US state I keep coming back to." in user
    assert "Moments (2 involving this entity)" in user
    assert "cognitive_load=low" in user  # per-moment markers
    assert "Rolled-up structured_markers" in user
    assert "trust_signal: 1" in user


def test_build_stance_formulation_messages_optional_markers_omitted_when_none() -> None:
    entity = Entity(agent_id=uuid4(), canonical_name="Bob", entity_type=EntityType.person)
    msgs = build_stance_formulation_messages(entity, [_km()])
    assert "Rolled-up structured_markers" not in msgs[1]["content"]


def test_system_prompt_stance_module_constant_exposed() -> None:
    # The constant exists, has a schema placeholder, and references the entity contract.
    assert "{schema}" in SYSTEM_PROMPT_STANCE
    assert "stance" in SYSTEM_PROMPT_STANCE.lower()
