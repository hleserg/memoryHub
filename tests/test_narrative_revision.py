"""Tests for NarrativeRevisionService."""

from __future__ import annotations

from uuid import uuid4

import pytest

from atman.adapters.reflection.mock_reflection_model import MockReflectionModel
from atman.core.models.experience import (
    EmotionalDepth,
    FeltSense,
    KeyMoment,
    SessionExperience,
)
from atman.core.models.identity import CoreValue, Identity
from atman.core.models.narrative import (
    LayerType,
    NarrativeDocument,
    NarrativeLayer,
)
from atman.core.models.reflection import PatternCandidate, PatternType, ReflectionLevel
from atman.core.services.narrative_revision import NarrativeRevisionService


class _StubNarrativeRepo:
    """Minimal NarrativeRepository for tests."""

    def __init__(self, initial: NarrativeDocument | None) -> None:
        self._current = initial

    def get_current(self) -> NarrativeDocument | None:
        return self._current

    def update(self, narrative: NarrativeDocument) -> None:
        self._current = narrative

    def get_history(self) -> list[NarrativeDocument]:
        return []


def _minimal_narrative() -> NarrativeDocument:
    iid = uuid4()
    return NarrativeDocument(
        identity_id=iid,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="I am core."),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="I am recent."),
        threads=[],
    )


def _sample_experience() -> SessionExperience:
    return SessionExperience(
        session_id=uuid4(),
        key_moments=[
            KeyMoment(
                what_happened="Happened",
                how_i_felt=FeltSense(
                    emotional_valence=0.2,
                    emotional_intensity=0.5,
                    depth=EmotionalDepth.MEANINGFUL,
                ),
                why_it_matters="Matters",
            )
        ],
    )


def test_update_recent_layer_no_narrative() -> None:
    svc = NarrativeRevisionService(_StubNarrativeRepo(None), MockReflectionModel())
    assert svc.update_recent_layer([], ReflectionLevel.MICRO) == "No narrative to update"


def test_update_recent_layer_updates_repo() -> None:
    doc = _minimal_narrative()
    repo = _StubNarrativeRepo(doc)
    svc = NarrativeRevisionService(repo, MockReflectionModel())
    out = svc.update_recent_layer([_sample_experience()], ReflectionLevel.MICRO)
    assert len(out) > 0
    cur = repo.get_current()
    assert cur is not None
    assert cur.recent_layer.content == out


def test_update_core_layer_no_narrative() -> None:
    svc = NarrativeRevisionService(_StubNarrativeRepo(None), MockReflectionModel())
    ident = Identity(self_description="Me")
    assert svc.update_core_layer(ident, [], "reason") == "No narrative to update"


def test_update_core_layer_minimal_identity_low_confidence_patterns() -> None:
    doc = _minimal_narrative()
    repo = _StubNarrativeRepo(doc)
    svc = NarrativeRevisionService(repo, MockReflectionModel())
    ident = Identity()
    pat = PatternCandidate(
        pattern_type=PatternType.COGNITIVE,
        description="Low confidence",
        detected_by=ReflectionLevel.DAILY,
        confidence=0.2,
    )
    text = svc.update_core_layer(ident, [pat], "only reason")
    assert "only reason" in text


def test_update_core_layer_with_identity_and_patterns() -> None:
    doc = _minimal_narrative()
    repo = _StubNarrativeRepo(doc)
    svc = NarrativeRevisionService(repo, MockReflectionModel())
    ident = Identity(
        self_description="I grow.",
        core_values=[CoreValue(name="honesty", description="truth", confidence=0.9)],
    )
    pat = PatternCandidate(
        pattern_type=PatternType.EMOTIONAL,
        description="High confidence pattern text.",
        detected_by=ReflectionLevel.DAILY,
        confidence=0.9,
    )
    text = svc.update_core_layer(ident, [pat], "deep review")
    assert "honesty" in text
    assert "deep review" in text
    cur = repo.get_current()
    assert cur is not None
    assert cur.core_layer.content == text
    assert "High confidence" in text


def test_open_thread_raises_without_narrative() -> None:
    svc = NarrativeRevisionService(_StubNarrativeRepo(None), MockReflectionModel())
    with pytest.raises(ValueError, match="No narrative document"):
        svc.open_thread("t", "d")


def test_update_thread_and_close_without_narrative() -> None:
    svc = NarrativeRevisionService(_StubNarrativeRepo(None), MockReflectionModel())
    assert svc.update_thread(str(uuid4()), "x") is None
    assert svc.close_thread(str(uuid4()), "reason") is False


def test_open_update_close_thread_flow() -> None:
    doc = _minimal_narrative()
    repo = _StubNarrativeRepo(doc)
    svc = NarrativeRevisionService(repo, MockReflectionModel())

    thread = svc.open_thread("Topic", "About topic", context="Started")
    assert thread.title == "Topic"

    cur = repo.get_current()
    assert cur is not None
    assert len(cur.threads) == 1

    updated = svc.update_thread(str(thread.id), "New state", add_moment="A moment")
    assert updated is not None
    assert updated.current_state == "New state"
    assert "A moment" in updated.key_moments

    assert svc.update_thread("not-a-uuid", "x") is None
    assert svc.update_thread(str(uuid4()), "x") is None

    assert svc.close_thread(str(thread.id), "done") is True
    assert svc.close_thread("bad", "r") is False
    assert svc.close_thread(str(uuid4()), "r") is False

    svc2 = NarrativeRevisionService(repo, MockReflectionModel())
    t2 = svc2.open_thread("T2", "D2")
    assert svc2.close_thread(str(t2.id), "") is False
