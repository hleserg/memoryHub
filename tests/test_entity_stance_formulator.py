"""Tests for :mod:`atman.core.services.entity_stance_formulator` (R7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from atman.adapters.clock import FrozenClock
from atman.adapters.memory.in_memory_entity_registry import InMemoryEntityRegistry
from atman.adapters.memory.in_memory_entity_stance import InMemoryEntityStanceStore
from atman.adapters.reflection.mock_reflection_model import MockReflectionModel
from atman.adapters.storage.in_memory_state_store import InMemoryStateStore
from atman.core.models.entity import Entity, EntityType
from atman.core.models.experience import EmotionalDepth, FeltSense, KeyMoment
from atman.core.models.reflection import StanceFormulationOutput
from atman.core.services.entity_stance_formulator import (
    CONFIDENCE_REAFFIRM_BUMP,
    DEFAULT_MIN_MOMENTS,
    EntityStanceFormulator,
)

AGENT_ID = UUID("00000000-0000-4000-8000-000000000fff")


# ---------------------------------------------------------------------------
# Test stubs (minimal protocol satisfaction)
# ---------------------------------------------------------------------------


class _StanceModel(MockReflectionModel):
    """MockReflectionModel + a deterministic stance formulator for tests."""

    def __init__(
        self,
        *,
        stance_text: str = "I feel cautious warmth toward this entity.",
        valence: float | None = 0.4,
        intensity: float | None = 0.6,
        confidence: float | None = 0.7,
    ) -> None:
        super().__init__()
        self.calls: list[tuple[UUID, int]] = []
        self._stance_text = stance_text
        self._valence = valence
        self._intensity = intensity
        self._confidence = confidence

    def formulate_entity_stance(
        self,
        entity: Entity,
        moments: list[KeyMoment],
        structured_markers: dict[str, int] | None = None,
    ) -> StanceFormulationOutput:
        self.calls.append((entity.id, len(moments)))
        return StanceFormulationOutput(
            stance_text=self._stance_text,
            valence_estimate=self._valence,
            intensity_estimate=self._intensity,
            confidence=self._confidence,
        )


class _RegistryStub(InMemoryEntityRegistry):
    """InMemoryEntityRegistry pre-populated with a fixed entity set."""

    def __init__(self, entities: list[Entity]):
        super().__init__()
        for e in entities:
            self._entities[e.id] = e  # type: ignore[attr-defined]


class _StateStoreStub(InMemoryStateStore):
    """InMemoryStateStore + an explicit entity → moments index for the test."""

    def __init__(self) -> None:
        super().__init__()
        self._by_entity: dict[UUID, list[KeyMoment]] = {}

    def add(self, entity_id: UUID, moment: KeyMoment) -> None:
        self._by_entity.setdefault(entity_id, []).append(moment)

    def find_moments_by_entity(self, entity_id: UUID, *, limit: int = 20) -> list[KeyMoment]:
        return list(self._by_entity.get(entity_id, []))[:limit]


def _moment(
    *,
    when: datetime,
    markers: dict[str, Any] | None = None,
) -> KeyMoment:
    return KeyMoment(
        session_id=uuid4(),
        what_happened="e",
        when=when,
        how_i_felt=FeltSense(
            emotional_valence=0.1,
            emotional_intensity=0.5,
            depth=EmotionalDepth.MEANINGFUL,
        ),
        why_it_matters="t",
        structured_markers=markers,
    )


def _make_entity_with_moments(
    *,
    state: _StateStoreStub,
    n_moments: int,
    base_time: datetime | None = None,
    name: str = "Alice",
) -> tuple[Entity, list[KeyMoment]]:
    base = base_time or datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
    entity = Entity(agent_id=AGENT_ID, canonical_name=name, entity_type=EntityType.person)
    moments = [
        _moment(when=base + timedelta(hours=i), markers={"trust_signal": "warm"})
        for i in range(n_moments)
    ]
    for m in moments:
        state.add(entity.id, m)
    return entity, moments


# ---------------------------------------------------------------------------
# Daily — formulate_for_new_entities
# ---------------------------------------------------------------------------


def test_below_threshold_yields_no_stance():
    state = _StateStoreStub()
    stance_store = InMemoryEntityStanceStore()
    model = _StanceModel()
    entity, _ = _make_entity_with_moments(state=state, n_moments=DEFAULT_MIN_MOMENTS - 1)
    registry = _RegistryStub([entity])
    fmt = EntityStanceFormulator(state, registry, stance_store, model)  # type: ignore[arg-type]

    outcome = fmt.formulate_for_new_entities(AGENT_ID, candidate_entity_ids=[entity.id])

    assert outcome.formulated == 0
    assert outcome.skipped == 1
    assert stance_store.get_current_stance(AGENT_ID, entity.id) is None
    assert model.calls == []


def test_at_threshold_writes_provisional_stance():
    state = _StateStoreStub()
    stance_store = InMemoryEntityStanceStore()
    model = _StanceModel()
    entity, moments = _make_entity_with_moments(state=state, n_moments=DEFAULT_MIN_MOMENTS)
    registry = _RegistryStub([entity])
    fmt = EntityStanceFormulator(state, registry, stance_store, model)  # type: ignore[arg-type]

    outcome = fmt.formulate_for_new_entities(AGENT_ID, candidate_entity_ids=[entity.id])

    assert outcome.formulated == 1
    stance = stance_store.get_current_stance(AGENT_ID, entity.id)
    assert stance is not None
    assert stance.stance_text == model._stance_text
    assert stance.is_provisional is True
    assert stance.confidence == model._confidence
    # based_on_moment_ids — mandatory (§9).
    assert sorted(stance.based_on_moment_ids) == sorted(m.id for m in moments)
    assert model.calls == [(entity.id, DEFAULT_MIN_MOMENTS)]


def test_second_run_supersedes_old_stance():
    state = _StateStoreStub()
    stance_store = InMemoryEntityStanceStore()
    model = _StanceModel()
    entity, _ = _make_entity_with_moments(state=state, n_moments=DEFAULT_MIN_MOMENTS)
    registry = _RegistryStub([entity])
    fmt = EntityStanceFormulator(state, registry, stance_store, model)  # type: ignore[arg-type]

    fmt.formulate_for_new_entities(AGENT_ID, candidate_entity_ids=[entity.id])
    first = stance_store.get_current_stance(AGENT_ID, entity.id)
    assert first is not None

    fmt.formulate_for_new_entities(AGENT_ID, candidate_entity_ids=[entity.id])
    second = stance_store.get_current_stance(AGENT_ID, entity.id)
    assert second is not None
    assert second.id != first.id
    history = stance_store.get_stance_history(AGENT_ID, entity.id)
    assert len(history) == 2
    superseded = [s for s in history if s.superseded_at is not None]
    assert len(superseded) == 1 and superseded[0].id == first.id
    assert superseded[0].superseded_by == second.id


def test_empty_llm_output_skips_persistence():
    state = _StateStoreStub()
    stance_store = InMemoryEntityStanceStore()

    class _SilentModel(MockReflectionModel):
        def formulate_entity_stance(self, entity, moments, structured_markers=None):
            return StanceFormulationOutput(stance_text="")

    entity, _ = _make_entity_with_moments(state=state, n_moments=DEFAULT_MIN_MOMENTS)
    registry = _RegistryStub([entity])
    fmt = EntityStanceFormulator(state, registry, stance_store, _SilentModel())  # type: ignore[arg-type]

    outcome = fmt.formulate_for_new_entities(AGENT_ID, candidate_entity_ids=[entity.id])
    assert outcome.formulated == 0
    assert outcome.skipped == 1
    assert stance_store.get_current_stance(AGENT_ID, entity.id) is None


def test_default_reflection_model_returns_empty_stance():
    """Subclasses that haven't wired the method get the default no-op behaviour."""
    out = MockReflectionModel().formulate_entity_stance(
        Entity(agent_id=AGENT_ID, canonical_name="X", entity_type=EntityType.person),
        [],
    )
    assert isinstance(out, StanceFormulationOutput)
    assert out.stance_text == ""


def test_candidate_entity_ids_none_iterates_registry():
    state = _StateStoreStub()
    stance_store = InMemoryEntityStanceStore()
    model = _StanceModel()
    entity, _ = _make_entity_with_moments(state=state, n_moments=DEFAULT_MIN_MOMENTS)
    registry = _RegistryStub([entity])
    fmt = EntityStanceFormulator(state, registry, stance_store, model)  # type: ignore[arg-type]

    outcome = fmt.formulate_for_new_entities(AGENT_ID)
    assert outcome.formulated == 1


# ---------------------------------------------------------------------------
# Deep — revise_stale
# ---------------------------------------------------------------------------


def test_revise_stale_no_new_moments_skips():
    state = _StateStoreStub()
    stance_store = InMemoryEntityStanceStore()
    now = datetime(2026, 6, 30, 12, 0, 0, tzinfo=UTC)
    clock = FrozenClock(now)
    model = _StanceModel()

    # All moments dated before stance.formed_at.
    entity, _ = _make_entity_with_moments(
        state=state,
        n_moments=DEFAULT_MIN_MOMENTS,
        base_time=now - timedelta(days=60),
    )
    registry = _RegistryStub([entity])
    fmt = EntityStanceFormulator(
        state,
        registry,
        stance_store,
        model,  # type: ignore[arg-type]
        clock=clock,
        staleness_days=30,
    )
    stance = stance_store.write_stance(
        AGENT_ID,
        entity.id,
        "old stance",
        valence=0.3,
        confidence=0.5,
        based_on_moment_ids=[],
    )
    stance.formed_at = now - timedelta(days=45)

    outcome = fmt.revise_stale(AGENT_ID)
    assert outcome.formulated == 0
    assert outcome.promoted == 0
    assert outcome.skipped == 1
    assert model.calls == []


def test_revise_stale_material_change_writes_new_stance():
    state = _StateStoreStub()
    stance_store = InMemoryEntityStanceStore()
    now = datetime(2026, 6, 30, 12, 0, 0, tzinfo=UTC)
    clock = FrozenClock(now)
    # New stance reverses direction → material change.
    model = _StanceModel(stance_text="I feel cooler now.", valence=-0.5)

    entity, _ = _make_entity_with_moments(
        state=state,
        n_moments=DEFAULT_MIN_MOMENTS,
        base_time=now - timedelta(days=5),  # All moments after stance.formed_at.
    )
    registry = _RegistryStub([entity])
    fmt = EntityStanceFormulator(
        state,
        registry,
        stance_store,
        model,  # type: ignore[arg-type]
        clock=clock,
        staleness_days=30,
    )
    stance = stance_store.write_stance(
        AGENT_ID,
        entity.id,
        "old stance",
        valence=0.5,
        confidence=0.4,
        based_on_moment_ids=[],
    )
    stance.formed_at = now - timedelta(days=45)

    outcome = fmt.revise_stale(AGENT_ID)
    assert outcome.formulated == 1
    assert outcome.promoted == 0
    history = stance_store.get_stance_history(AGENT_ID, entity.id)
    assert len(history) == 2
    current = stance_store.get_current_stance(AGENT_ID, entity.id)
    assert current is not None
    assert current.stance_text == "I feel cooler now."
    assert current.valence == -0.5


def test_revise_stale_no_material_change_promotes_to_non_provisional():
    state = _StateStoreStub()
    stance_store = InMemoryEntityStanceStore()
    now = datetime(2026, 6, 30, 12, 0, 0, tzinfo=UTC)
    clock = FrozenClock(now)
    model = _StanceModel(stance_text="Same overall feel.", valence=0.45, confidence=0.6)

    entity, _ = _make_entity_with_moments(
        state=state,
        n_moments=DEFAULT_MIN_MOMENTS,
        base_time=now - timedelta(days=5),
    )
    registry = _RegistryStub([entity])
    fmt = EntityStanceFormulator(
        state,
        registry,
        stance_store,
        model,  # type: ignore[arg-type]
        clock=clock,
        staleness_days=30,
    )
    stance = stance_store.write_stance(
        AGENT_ID,
        entity.id,
        "old stance",
        valence=0.5,
        confidence=0.4,
        based_on_moment_ids=[],
        is_provisional=True,
    )
    stance.formed_at = now - timedelta(days=45)
    prev_conf = stance.confidence
    assert prev_conf is not None

    outcome = fmt.revise_stale(AGENT_ID)
    assert outcome.formulated == 0
    assert outcome.promoted == 1
    history = stance_store.get_stance_history(AGENT_ID, entity.id)
    assert len(history) == 1  # No new row.
    current = stance_store.get_current_stance(AGENT_ID, entity.id)
    assert current is not None
    assert current.is_provisional is False
    assert current.confidence is not None
    assert current.confidence == min(1.0, prev_conf + CONFIDENCE_REAFFIRM_BUMP)


def test_revise_stale_skips_recent_stances():
    state = _StateStoreStub()
    stance_store = InMemoryEntityStanceStore()
    now = datetime(2026, 6, 30, 12, 0, 0, tzinfo=UTC)
    clock = FrozenClock(now)
    model = _StanceModel()

    entity, _ = _make_entity_with_moments(state=state, n_moments=DEFAULT_MIN_MOMENTS)
    registry = _RegistryStub([entity])
    fmt = EntityStanceFormulator(
        state,
        registry,
        stance_store,
        model,  # type: ignore[arg-type]
        clock=clock,
        staleness_days=30,
    )
    stance_store.write_stance(
        AGENT_ID, entity.id, "recent", based_on_moment_ids=[]
    )  # formed_at = now, not stale.

    outcome = fmt.revise_stale(AGENT_ID)
    assert outcome.formulated == 0
    assert outcome.promoted == 0
    assert model.calls == []
