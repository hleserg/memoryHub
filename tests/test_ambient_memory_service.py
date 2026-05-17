"""Tests for HLE-33 — AmbientMemoryService entity-anchor parallel RAG."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from atman.adapters.memory.in_memory_entity_registry import InMemoryEntityRegistry
from atman.adapters.memory.in_memory_entity_stance import InMemoryEntityStanceStore
from atman.adapters.storage.in_memory_state_store import InMemoryStateStore
from atman.core.models.entity import Entity, EntityType
from atman.core.models.experience import EmotionalDepth, FeltSense, KeyMoment
from atman.core.models.fact import FactRecord
from atman.core.ports.linguistic import (
    AgentMessageAnalysis,
    AmbientAnchor,
    KeyMomentAnalysis,
    LinguisticAnalyzer,
    UserMessageAnalysis,
)
from atman.core.services.ambient_memory_service import (
    AmbientMemoryService,
    AmbientSurfaceItem,
)


class _Analyzer(LinguisticAnalyzer):
    """Stub analyzer returning fixed anchors so tests stay deterministic."""

    def __init__(self, anchors: list[AmbientAnchor]) -> None:
        self._anchors = anchors

    def analyze_user_message(self, text: str) -> UserMessageAnalysis:  # type: ignore[override]
        return UserMessageAnalysis(text=text, anchors=self._anchors)

    def analyze_agent_message(self, message, *, thinking=None):  # type: ignore[override]
        return AgentMessageAnalysis()

    def analyze_key_moment(self, what_happened, why_it_matters):  # type: ignore[override]
        return KeyMomentAnalysis()


class _StoreWithMomentLink(InMemoryStateStore):
    """InMemoryStateStore augmented with a hand-rolled moment↔entity index
    so the ambient service has something to query."""

    def __init__(self) -> None:
        super().__init__()
        self._moments_by_entity: dict[UUID, list[KeyMoment]] = {}

    def link(self, entity_id: UUID, moment: KeyMoment) -> None:
        self._moments_by_entity.setdefault(entity_id, []).append(moment)
        # Also register in the regular store so other ports (e.g. salience)
        # can find it by id.
        if moment.session_id is not None:
            self.store_key_moments(moment.session_id, [moment])

    def find_moments_by_entity(self, entity_id: UUID, *, limit: int = 20) -> list[KeyMoment]:  # type: ignore[override]
        return self._moments_by_entity.get(entity_id, [])[:limit]


class _Facts:
    """Minimal stub for FactualMemory.find_facts_by_entity."""

    def __init__(self) -> None:
        self._by_entity: dict[UUID, list[FactRecord]] = {}

    def link(self, entity_id: UUID, fact: FactRecord) -> None:
        self._by_entity.setdefault(entity_id, []).append(fact)

    def find_facts_by_entity(
        self, entity_id: UUID, roles=None, *, limit: int = 20
    ) -> list[FactRecord]:
        return self._by_entity.get(entity_id, [])[:limit]


class _SalienceSpy:
    """Records mark_accessed calls so we can verify the (f) workflow step."""

    def __init__(self) -> None:
        self.marked: list[UUID] = []

    def mark_accessed(self, moment_id: UUID) -> None:
        self.marked.append(moment_id)

    # Other SalienceDecayService methods left unimplemented — the ambient
    # service only calls mark_accessed.


def _moment(text: str, *, intensity: float = 0.5, salience: float = 0.5) -> KeyMoment:
    return KeyMoment(
        what_happened=text,
        when=datetime.now(UTC),
        how_i_felt=FeltSense(
            emotional_valence=0.2, emotional_intensity=intensity, depth=EmotionalDepth.MEANINGFUL
        ),
        why_it_matters="why",
        salience=salience,
        session_id=uuid4(),
    )


def _seed_entity(registry: InMemoryEntityRegistry, agent: UUID, name: str) -> Entity:
    entity, _method = registry.resolve_or_create(
        agent_id=agent,
        canonical_name=name,
        entity_type=EntityType.person,
    )
    return entity


def _anchor(text: str, anchor_type: str = "person_ref") -> AmbientAnchor:
    return AmbientAnchor(
        anchor_type=anchor_type,
        text=text,
        confidence=0.9,
        entity_type=EntityType.person,
    )


# ---- basic anchor → moments path -----------------------------------------


def test_compose_injection_surfaces_moments_for_known_entity() -> None:
    agent = uuid4()
    store = _StoreWithMomentLink()
    registry = InMemoryEntityRegistry()
    alice = _seed_entity(registry, agent, "Alice")
    m1 = _moment("alice mentored bob", salience=0.8, intensity=0.7)
    m2 = _moment("alice helped me debug", salience=0.6, intensity=0.4)
    store.link(alice.id, m1)
    store.link(alice.id, m2)

    svc = AmbientMemoryService(
        linguistic_analyzer=_Analyzer([_anchor("Alice")]),
        entity_registry=registry,
        state_store=store,
    )
    out = svc.compose_injection("tell me about Alice", agent_id=agent)
    moment_items = [i for i in out.items if i.kind == "moment"]
    assert {i.payload.id for i in moment_items} == {m1.id, m2.id}


def test_compose_injection_orders_moments_by_salience_aware_score() -> None:
    """Plan §8: salience*0.4 + intensity*0.3 + recency*0.3."""
    agent = uuid4()
    store = _StoreWithMomentLink()
    registry = InMemoryEntityRegistry()
    alice = _seed_entity(registry, agent, "Alice")
    high = _moment("important", salience=0.95, intensity=0.95)
    low = _moment("not important", salience=0.1, intensity=0.1)
    store.link(alice.id, low)
    store.link(alice.id, high)

    svc = AmbientMemoryService(
        linguistic_analyzer=_Analyzer([_anchor("Alice")]),
        entity_registry=registry,
        state_store=store,
    )
    out = svc.compose_injection("about Alice", agent_id=agent)
    moments = [i.payload for i in out.items if i.kind == "moment"]
    assert moments[0].id == high.id
    assert moments[-1].id == low.id


# ---- stance precedence ---------------------------------------------------


def test_compose_injection_puts_stance_above_moments() -> None:
    """Plan §7: stances precede raw episodes regardless of their score."""
    agent = uuid4()
    store = _StoreWithMomentLink()
    registry = InMemoryEntityRegistry()
    stance_store = InMemoryEntityStanceStore()
    alice = _seed_entity(registry, agent, "Alice")
    # High-scored moment so the test proves ordering, not luck.
    store.link(alice.id, _moment("very intense moment", salience=1.0, intensity=1.0))
    stance_store.write_stance(
        agent_id=agent,
        entity_id=alice.id,
        stance_text="I think highly of Alice.",
    )

    svc = AmbientMemoryService(
        linguistic_analyzer=_Analyzer([_anchor("Alice")]),
        entity_registry=registry,
        state_store=store,
        entity_stance_store=stance_store,
    )
    out = svc.compose_injection("about Alice", agent_id=agent)
    assert out.items
    assert out.items[0].kind == "stance"


# ---- facts ----------------------------------------------------------------


def test_compose_injection_surfaces_linked_facts() -> None:
    agent = uuid4()
    store = _StoreWithMomentLink()
    registry = InMemoryEntityRegistry()
    facts = _Facts()
    alice = _seed_entity(registry, agent, "Alice")
    fact = FactRecord(content="Alice is a senior engineer.", source="manual")
    facts.link(alice.id, fact)

    svc = AmbientMemoryService(
        linguistic_analyzer=_Analyzer([_anchor("Alice")]),
        entity_registry=registry,
        state_store=store,
        factual_memory=facts,  # type: ignore[arg-type]
    )
    out = svc.compose_injection("about Alice", agent_id=agent)
    fact_items = [i for i in out.items if i.kind == "fact"]
    assert any(i.payload.id == fact.id for i in fact_items)


# ---- mark_accessed --------------------------------------------------------


def test_compose_injection_marks_returned_moments_accessed() -> None:
    """Plan §12 шаг (f): used moments are routed through SalienceDecayService."""
    agent = uuid4()
    store = _StoreWithMomentLink()
    registry = InMemoryEntityRegistry()
    salience = _SalienceSpy()
    alice = _seed_entity(registry, agent, "Alice")
    m = _moment("test", salience=0.8, intensity=0.6)
    store.link(alice.id, m)

    svc = AmbientMemoryService(
        linguistic_analyzer=_Analyzer([_anchor("Alice")]),
        entity_registry=registry,
        state_store=store,
        salience_decay=salience,  # type: ignore[arg-type]
    )
    out = svc.compose_injection("about Alice", agent_id=agent)
    assert any(i.payload.id == m.id for i in out.items)
    assert m.id in salience.marked


# ---- token budget ---------------------------------------------------------


def test_compose_injection_respects_token_budget() -> None:
    """Anchored items beyond the budget are dropped, items inside stay."""
    agent = uuid4()
    store = _StoreWithMomentLink()
    registry = InMemoryEntityRegistry()
    alice = _seed_entity(registry, agent, "Alice")
    long_text = "x" * 6000  # ~2000 tokens at /3 heuristic
    store.link(alice.id, _moment(long_text, salience=0.9))
    store.link(alice.id, _moment("short", salience=0.95))  # still has 'why'

    svc = AmbientMemoryService(
        linguistic_analyzer=_Analyzer([_anchor("Alice")]),
        entity_registry=registry,
        state_store=store,
        token_budget=50,
    )
    out = svc.compose_injection("about Alice", agent_id=agent)
    # At least one item fits; the budget is enforced (item count bounded).
    assert 1 <= len(out.items) <= 2
    assert out.tokens_used <= 50 or len(out.items) == 1


# ---- no anchors / unknown entity ----------------------------------------


def test_compose_injection_empty_when_no_biographical_anchors() -> None:
    agent = uuid4()
    store = _StoreWithMomentLink()
    registry = InMemoryEntityRegistry()
    svc = AmbientMemoryService(
        linguistic_analyzer=_Analyzer([]),  # no anchors
        entity_registry=registry,
        state_store=store,
    )
    out = svc.compose_injection("how are you", agent_id=agent)
    assert out.items == []
    assert out.tokens_used == 0


def test_compose_injection_skips_unresolvable_anchor() -> None:
    agent = uuid4()
    store = _StoreWithMomentLink()
    registry = InMemoryEntityRegistry()
    svc = AmbientMemoryService(
        linguistic_analyzer=_Analyzer([_anchor("Stranger")]),
        entity_registry=registry,  # registry has no 'Stranger' entity
        state_store=store,
    )
    out = svc.compose_injection("about Stranger", agent_id=agent)
    assert out.items == []


# ---- defensive paths -----------------------------------------------------


def test_compose_injection_swallows_backend_errors() -> None:
    """A flaky state_store must not crash the hot path."""

    class _Boom(_StoreWithMomentLink):
        def find_moments_by_entity(self, entity_id, *, limit=20):  # type: ignore[override]
            raise RuntimeError("store offline")

    agent = uuid4()
    store = _Boom()
    registry = InMemoryEntityRegistry()
    alice = _seed_entity(registry, agent, "Alice")
    _ = alice

    svc = AmbientMemoryService(
        linguistic_analyzer=_Analyzer([_anchor("Alice")]),
        entity_registry=registry,
        state_store=store,
    )
    # Should not raise:
    out = svc.compose_injection("about Alice", agent_id=agent)
    moments = [i for i in out.items if i.kind == "moment"]
    assert moments == []  # the broken backend yields nothing


def test_compose_injection_empty_for_blank_text() -> None:
    """Cover the empty-text early return."""
    svc = AmbientMemoryService(
        linguistic_analyzer=_Analyzer([]),
        entity_registry=InMemoryEntityRegistry(),
        state_store=_StoreWithMomentLink(),
    )
    out = svc.compose_injection("   ", agent_id=uuid4())
    assert out.items == []
    assert out.tokens_used == 0


def test_compose_injection_handles_naive_timestamp() -> None:
    """KeyMoment.when with tzinfo=None should not crash _moment_score."""
    agent = uuid4()
    store = _StoreWithMomentLink()
    registry = InMemoryEntityRegistry()
    alice = _seed_entity(registry, agent, "Alice")
    m = KeyMoment(
        what_happened="naive",
        when=datetime.now(),  # explicitly tz-naive for the test
        how_i_felt=FeltSense(
            emotional_valence=0.0,
            emotional_intensity=0.5,
            depth=EmotionalDepth.SURFACE,
        ),
        why_it_matters="why",
        session_id=uuid4(),
    )
    store.link(alice.id, m)
    svc = AmbientMemoryService(
        linguistic_analyzer=_Analyzer([_anchor("Alice")]),
        entity_registry=registry,
        state_store=store,
    )
    out = svc.compose_injection("about Alice", agent_id=agent)
    assert any(i.payload.id == m.id for i in out.items)


# ---- factory wiring -------------------------------------------------------


def test_factory_exposes_ambient_memory_service_on_deps(tmp_path) -> None:
    """build_deps should construct an AmbientMemoryService so the runner
    can call deps.ambient_memory.compose_injection without further wiring."""
    from atman.adapters.agent.factory import build_deps
    from atman.core.services.ambient_memory_service import AmbientMemoryService

    deps, _sm, _store = build_deps(tmp_path, uuid4())
    assert isinstance(deps.ambient_memory, AmbientMemoryService)
    # The default in-memory adapter has no anchors → empty result, but the
    # call must succeed without raising.
    out = deps.ambient_memory.compose_injection("hello", agent_id=deps.agent_id)
    assert out.items == []


def test_factory_shares_entity_registry_with_ambient_service(tmp_path) -> None:
    """Devin Review #600 ANALYSIS: the EntityRegistry constructed in
    build_deps must be the *same instance* visible via
    ``deps.entity_registry`` as the one fed into AmbientMemoryService.
    Otherwise live write paths populate one registry while ambient memory
    reads from another and never sees anything.

    Direct attribute access proves identity without relying on a real
    NER analyzer (NoOp returns no anchors)."""
    from atman.adapters.agent.factory import build_deps

    deps, _sm, _store = build_deps(tmp_path, uuid4())
    assert deps.entity_registry is not None
    # The ambient service was constructed with the same registry instance:
    assert deps.ambient_memory._registry is deps.entity_registry  # type: ignore[attr-defined]


def test_surface_item_dataclass_is_frozen() -> None:
    item = AmbientSurfaceItem(kind="fact", payload=None, score=0.5)
    import dataclasses

    import pytest

    assert dataclasses.is_dataclass(item)
    with pytest.raises(dataclasses.FrozenInstanceError):
        item.score = 0.7  # type: ignore[misc]
