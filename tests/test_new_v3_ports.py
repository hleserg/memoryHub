"""Unit tests for v3 port DTOs: linguistic and memory_reranker."""

from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from atman.core.models.entity import EntityType
from atman.core.ports.linguistic import (
    AgentMessageAnalysis,
    AmbientAnchor,
    DetectedEntity,
    KeyMomentAnalysis,
    UserMessageAnalysis,
)
from atman.core.ports.memory_reranker import SurfacedMemory

# ============================ AmbientAnchor ============================


def test_ambient_anchor_minimal():
    anchor = AmbientAnchor(
        anchor_type="topic",
        text="weather",
        confidence=0.8,
    )
    assert anchor.anchor_type == "topic"
    assert anchor.text == "weather"
    assert anchor.confidence == 0.8
    assert anchor.entity_type is None
    assert anchor.span is None


def test_ambient_anchor_full():
    anchor = AmbientAnchor(
        anchor_type="person_ref",
        text="Alice",
        entity_type=EntityType.person,
        confidence=0.95,
        span=(0, 5),
    )
    assert anchor.entity_type is EntityType.person
    assert anchor.span == (0, 5)


def test_ambient_anchor_confidence_bounds():
    with pytest.raises(ValidationError):
        AmbientAnchor(anchor_type="topic", text="x", confidence=1.5)
    with pytest.raises(ValidationError):
        AmbientAnchor(anchor_type="topic", text="x", confidence=-0.1)


def test_ambient_anchor_frozen():
    anchor = AmbientAnchor(anchor_type="topic", text="x", confidence=0.5)
    with pytest.raises(ValidationError):
        anchor.text = "y"


@pytest.mark.parametrize(
    "anchor_type",
    ["person_ref", "topic", "location", "time_ref", "action", "emotion_ref"],
)
def test_ambient_anchor_accepts_doc_anchor_types(anchor_type):
    anchor = AmbientAnchor(anchor_type=anchor_type, text="x", confidence=0.5)
    assert anchor.anchor_type == anchor_type


# ============================ DetectedEntity ============================


def test_detected_entity_minimal():
    de = DetectedEntity(
        text="Alice",
        entity_type=EntityType.person,
        confidence=0.9,
    )
    assert de.text == "Alice"
    assert de.entity_type is EntityType.person
    assert de.confidence == 0.9
    assert de.span is None


def test_detected_entity_full():
    de = DetectedEntity(
        text="Vermont",
        entity_type=EntityType.place,
        confidence=0.7,
        span=(10, 17),
    )
    assert de.span == (10, 17)


def test_detected_entity_confidence_bounds():
    with pytest.raises(ValidationError):
        DetectedEntity(text="x", entity_type=EntityType.person, confidence=1.1)
    with pytest.raises(ValidationError):
        DetectedEntity(text="x", entity_type=EntityType.person, confidence=-0.01)


def test_detected_entity_frozen():
    de = DetectedEntity(text="x", entity_type=EntityType.person, confidence=0.5)
    with pytest.raises(ValidationError):
        de.text = "y"


def test_detected_entity_entity_type_required():
    with pytest.raises(ValidationError):
        DetectedEntity(text="x", confidence=0.5)  # type: ignore[call-arg]


# ============================ UserMessageAnalysis ============================


def test_user_message_analysis_defaults():
    ana = UserMessageAnalysis(text="Hello there")
    assert ana.text == "Hello there"
    assert ana.entities == []
    assert ana.anchors == []
    assert ana.detected_language == "ru"


def test_user_message_analysis_full():
    de = DetectedEntity(text="Alice", entity_type=EntityType.person, confidence=0.9)
    anchor = AmbientAnchor(anchor_type="person_ref", text="Alice", confidence=0.8)
    ana = UserMessageAnalysis(
        text="Hello Alice",
        entities=[de],
        anchors=[anchor],
        detected_language="en",
    )
    assert ana.entities == [de]
    assert ana.anchors == [anchor]
    assert ana.detected_language == "en"


def test_user_message_analysis_frozen():
    ana = UserMessageAnalysis(text="x")
    with pytest.raises(ValidationError):
        ana.text = "y"


def test_user_message_analysis_text_required():
    with pytest.raises(ValidationError):
        UserMessageAnalysis()  # type: ignore[call-arg]


# ============================ AgentMessageAnalysis ============================


def test_agent_message_analysis_defaults():
    ana = AgentMessageAnalysis()
    assert ana.message_entities == []
    assert ana.thinking_entities == []
    assert ana.divergence_signals == []
    assert ana.boundary_markers == []
    assert ana.trust_signals == []
    assert ana.cognitive_load_high is False
    assert ana.detected_language == "ru"


def test_agent_message_analysis_full():
    de1 = DetectedEntity(text="A", entity_type=EntityType.person, confidence=0.6)
    de2 = DetectedEntity(text="B", entity_type=EntityType.topic, confidence=0.7)
    ana = AgentMessageAnalysis(
        message_entities=[de1],
        thinking_entities=[de2],
        divergence_signals=["hedging_in_thinking"],
        boundary_markers=["refusal"],
        trust_signals=["positive"],
        cognitive_load_high=True,
        detected_language="en",
    )
    assert ana.message_entities == [de1]
    assert ana.thinking_entities == [de2]
    assert ana.divergence_signals == ["hedging_in_thinking"]
    assert ana.boundary_markers == ["refusal"]
    assert ana.trust_signals == ["positive"]
    assert ana.cognitive_load_high is True
    assert ana.detected_language == "en"


def test_agent_message_analysis_frozen():
    ana = AgentMessageAnalysis()
    with pytest.raises(ValidationError):
        ana.cognitive_load_high = True


# ============================ KeyMomentAnalysis ============================


def test_key_moment_analysis_defaults():
    ana = KeyMomentAnalysis()
    assert ana.entities == []
    assert ana.topic_labels == []
    assert ana.cognitive_load == 0.0
    assert ana.boundary_event is False
    assert ana.trust_signal is None
    assert ana.principle_invocations == []


def test_key_moment_analysis_full():
    de = DetectedEntity(text="Bob", entity_type=EntityType.person, confidence=0.5)
    ana = KeyMomentAnalysis(
        entities=[de],
        topic_labels=["work", "stress"],
        cognitive_load=0.6,
        boundary_event=True,
        trust_signal="positive",
        principle_invocations=["honesty"],
    )
    assert ana.entities == [de]
    assert ana.topic_labels == ["work", "stress"]
    assert ana.cognitive_load == 0.6
    assert ana.boundary_event is True
    assert ana.trust_signal == "positive"
    assert ana.principle_invocations == ["honesty"]


def test_key_moment_analysis_cognitive_load_bounds():
    with pytest.raises(ValidationError):
        KeyMomentAnalysis(cognitive_load=1.5)
    with pytest.raises(ValidationError):
        KeyMomentAnalysis(cognitive_load=-0.01)


def test_key_moment_analysis_frozen():
    ana = KeyMomentAnalysis()
    with pytest.raises(ValidationError):
        ana.boundary_event = True


@pytest.mark.parametrize("signal", ["positive", "negative", None])
def test_key_moment_analysis_trust_signal_variants(signal):
    ana = KeyMomentAnalysis(trust_signal=signal)
    assert ana.trust_signal == signal


# ============================ SurfacedMemory ============================


def test_surfaced_memory_minimal():
    kmid = uuid4()
    mem = SurfacedMemory(
        key_moment_id=kmid,
        text="what happened",
        score=0.5,
        source="dense",
    )
    assert isinstance(mem.key_moment_id, UUID)
    assert mem.key_moment_id == kmid
    assert mem.text == "what happened"
    assert mem.score == 0.5
    assert mem.final_score is None
    assert mem.source == "dense"


def test_surfaced_memory_with_final_score():
    mem = SurfacedMemory(
        key_moment_id=uuid4(),
        text="x",
        score=0.3,
        final_score=0.9,
        source="entity_join",
    )
    assert mem.final_score == 0.9


def test_surfaced_memory_score_bounds():
    with pytest.raises(ValidationError):
        SurfacedMemory(
            key_moment_id=uuid4(),
            text="x",
            score=1.1,
            source="dense",
        )
    with pytest.raises(ValidationError):
        SurfacedMemory(
            key_moment_id=uuid4(),
            text="x",
            score=-0.1,
            source="dense",
        )


def test_surfaced_memory_score_boundaries_inclusive():
    m0 = SurfacedMemory(key_moment_id=uuid4(), text="x", score=0.0, source="dense")
    m1 = SurfacedMemory(key_moment_id=uuid4(), text="x", score=1.0, source="dense")
    assert m0.score == 0.0
    assert m1.score == 1.0


def test_surfaced_memory_frozen():
    mem = SurfacedMemory(
        key_moment_id=uuid4(),
        text="x",
        score=0.5,
        source="dense",
    )
    with pytest.raises(ValidationError):
        mem.text = "y"
    with pytest.raises(ValidationError):
        mem.final_score = 0.7


@pytest.mark.parametrize("source", ["dense", "entity_join", "time_ref", "alias_match", "fallback"])
def test_surfaced_memory_accepts_doc_sources(source):
    mem = SurfacedMemory(
        key_moment_id=uuid4(),
        text="x",
        score=0.5,
        source=source,
    )
    assert mem.source == source


def test_surfaced_memory_required_fields():
    with pytest.raises(ValidationError):
        SurfacedMemory(text="x", score=0.5, source="dense")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        SurfacedMemory(key_moment_id=uuid4(), score=0.5, source="dense")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        SurfacedMemory(key_moment_id=uuid4(), text="x", source="dense")  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        SurfacedMemory(key_moment_id=uuid4(), text="x", score=0.5)  # type: ignore[call-arg]
