"""Tests for :mod:`atman.core.services.merge_candidates_handler` (R10)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from atman.adapters.memory.in_memory_entity_registry import InMemoryEntityRegistry
from atman.adapters.reflection.mock_reflection_model import MockReflectionModel
from atman.adapters.storage.in_memory_state_store import InMemoryStateStore
from atman.core.models.entity import Entity, EntityType
from atman.core.models.experience import EmotionalDepth, FeltSense, KeyMoment
from atman.core.models.reflection import MergeDecisionOutput
from atman.core.models.validation import (
    FindingSeverity,
    FindingType,
    ResolutionStatus,
    ValidationFinding,
)
from atman.core.ports.memory_guardian import MemoryGuardian
from atman.core.services.merge_candidates_handler import (
    MERGE_RESOLVED_BY,
    MergeCandidatesHandler,
)

AGENT_ID = UUID("00000000-0000-4000-8000-000000000bbb")


class _MergeModel(MockReflectionModel):
    def __init__(
        self,
        *,
        confirmed: bool = True,
        canonical_name: str | None = "Alice",
        reason: str = "same person referenced both ways",
    ) -> None:
        super().__init__()
        self.calls: list[tuple[UUID, UUID, int, int]] = []
        self._confirmed = confirmed
        self._canonical_name = canonical_name
        self._reason = reason

    def decide_entity_merge(self, entity_a, entity_b, contexts_a, contexts_b):
        self.calls.append((entity_a.id, entity_b.id, len(contexts_a), len(contexts_b)))
        return MergeDecisionOutput(
            confirmed=self._confirmed,
            canonical_name=self._canonical_name,
            reason=self._reason,
        )


class _Guardian(MemoryGuardian):
    def __init__(self, findings: list[ValidationFinding]) -> None:
        self._findings = {f.id: f for f in findings}
        self.resolved_calls: list[tuple[UUID, str, str, str]] = []

    def scan_orphan_entities(self, agent_id):  # pragma: no cover
        return []

    def scan_merge_candidates(self, agent_id, *, similarity_threshold=0.92):  # pragma: no cover
        return []

    def scan_stale_moments(self, agent_id, *, days_threshold=90):  # pragma: no cover
        return []

    def scan_embedding_gaps(self, agent_id):  # pragma: no cover
        return []

    def write_finding(self, finding):  # pragma: no cover
        self._findings[finding.id] = finding
        return finding

    def get_unresolved(self, agent_id, severity=None):
        out = [f for f in self._findings.values() if not f.is_resolved]
        if severity is not None:
            out = [f for f in out if f.severity.value == severity]
        return out

    def resolve_finding(self, finding_id, *, resolution, resolved_by, note=""):
        f = self._findings.get(finding_id)
        if f is None:
            return None
        resolved = f.model_copy(
            update={
                "resolution": ResolutionStatus(resolution),
                "resolved_at": datetime.now(UTC),
                "resolved_by": resolved_by,
                "resolution_note": note,
            }
        )
        self._findings[finding_id] = resolved
        self.resolved_calls.append((finding_id, resolution, resolved_by, note))
        return resolved


class _RegistryStub(InMemoryEntityRegistry):
    def __init__(self, entities: list[Entity]):
        super().__init__()
        for e in entities:
            self._entities[e.id] = e  # type: ignore[attr-defined]
        self.merge_calls: list[tuple[UUID, UUID, str]] = []

    def merge_entities(self, source_id, target_id, *, reason):
        self.merge_calls.append((source_id, target_id, reason))
        return super().merge_entities(source_id, target_id, reason=reason)


class _StateStoreStub(InMemoryStateStore):
    def __init__(self) -> None:
        super().__init__()
        self._by_entity: dict[UUID, list[KeyMoment]] = {}

    def add(self, entity_id: UUID, moment: KeyMoment) -> None:
        self._by_entity.setdefault(entity_id, []).append(moment)

    def find_moments_by_entity(self, entity_id, *, limit=20):
        return list(self._by_entity.get(entity_id, []))[:limit]


def _moment() -> KeyMoment:
    return KeyMoment(
        session_id=uuid4(),
        what_happened="e",
        when=datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC),
        how_i_felt=FeltSense(
            emotional_valence=0.0,
            emotional_intensity=0.5,
            depth=EmotionalDepth.MEANINGFUL,
        ),
        why_it_matters="t",
    )


def _make_pair() -> tuple[Entity, Entity]:
    a = Entity(agent_id=AGENT_ID, canonical_name="Alice", entity_type=EntityType.person)
    b = Entity(agent_id=AGENT_ID, canonical_name="Alice S.", entity_type=EntityType.person)
    return a, b


def _similar_finding(a: Entity, b: Entity, *, cosine: float = 0.94) -> ValidationFinding:
    return ValidationFinding(
        agent_id=AGENT_ID,
        finding_type=FindingType.similar_entities,
        severity=FindingSeverity.warning,
        target_table="entities",
        target_id=a.id,
        details={"candidate_id": b.id, "cosine": cosine},
        detected_at=datetime.now(UTC),
        detected_by="memory_guardian",
    )


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_confirmed_triggers_merge_and_marks_finding_fixed():
    state = _StateStoreStub()
    a, b = _make_pair()
    state.add(a.id, _moment())
    state.add(b.id, _moment())
    registry = _RegistryStub([a, b])
    guardian = _Guardian([_similar_finding(a, b)])
    model = _MergeModel(confirmed=True, canonical_name="Alice", reason="same person")

    handler = MergeCandidatesHandler(state, registry, guardian, model)  # type: ignore[arg-type]
    outcome = handler.run(AGENT_ID)

    assert outcome.merged == 1
    assert outcome.ignored == 0
    # Alice is the canonical keeper; "Alice S." gets merged into Alice.
    assert registry.merge_calls and registry.merge_calls[0][1] == a.id
    assert registry.merge_calls[0][0] == b.id
    # Finding resolved as fixed.
    assert guardian.resolved_calls
    _fid, resolution, by, note = guardian.resolved_calls[0]
    assert resolution == ResolutionStatus.fixed.value
    assert by == MERGE_RESOLVED_BY
    assert "same person" in note


def test_not_confirmed_marks_finding_ignored_with_reason():
    state = _StateStoreStub()
    a, b = _make_pair()
    state.add(a.id, _moment())
    state.add(b.id, _moment())
    registry = _RegistryStub([a, b])
    guardian = _Guardian([_similar_finding(a, b)])
    model = _MergeModel(confirmed=False, reason="different referents")

    handler = MergeCandidatesHandler(state, registry, guardian, model)  # type: ignore[arg-type]
    outcome = handler.run(AGENT_ID)

    assert outcome.merged == 0
    assert outcome.ignored == 1
    assert registry.merge_calls == []
    _fid, resolution, _by, note = guardian.resolved_calls[0]
    assert resolution == ResolutionStatus.ignored.value
    assert "different referents" in note


def test_confirmed_without_canonical_name_uses_mention_count_tiebreak():
    state = _StateStoreStub()
    a = Entity(
        agent_id=AGENT_ID, canonical_name="A", entity_type=EntityType.person, mention_count=2
    )
    b = Entity(
        agent_id=AGENT_ID, canonical_name="B", entity_type=EntityType.person, mention_count=7
    )
    registry = _RegistryStub([a, b])
    guardian = _Guardian([_similar_finding(a, b)])
    model = _MergeModel(confirmed=True, canonical_name=None, reason="same")

    handler = MergeCandidatesHandler(state, registry, guardian, model)  # type: ignore[arg-type]
    handler.run(AGENT_ID)

    # B has higher mention_count, so it's kept; A is merged into B.
    assert registry.merge_calls[0] == (a.id, b.id, "deep_reflection: same")


# ---------------------------------------------------------------------------
# Skipping / safety
# ---------------------------------------------------------------------------


def test_missing_entities_skip_without_merging():
    state = _StateStoreStub()
    a, b = _make_pair()
    # Only register A — B is missing from the registry.
    registry = _RegistryStub([a])
    guardian = _Guardian([_similar_finding(a, b)])
    model = _MergeModel(confirmed=True)

    handler = MergeCandidatesHandler(state, registry, guardian, model)  # type: ignore[arg-type]
    outcome = handler.run(AGENT_ID)

    assert outcome.skipped == 1
    assert outcome.merged == 0
    assert registry.merge_calls == []
    assert guardian.resolved_calls == []


def test_missing_candidate_id_in_details_skip():
    state = _StateStoreStub()
    a, _b = _make_pair()
    registry = _RegistryStub([a])
    f = ValidationFinding(
        agent_id=AGENT_ID,
        finding_type=FindingType.similar_entities,
        severity=FindingSeverity.warning,
        target_table="entities",
        target_id=a.id,
        details={},  # no candidate id
        detected_at=datetime.now(UTC),
        detected_by="memory_guardian",
    )
    guardian = _Guardian([f])
    handler = MergeCandidatesHandler(state, registry, guardian, _MergeModel())  # type: ignore[arg-type]

    outcome = handler.run(AGENT_ID)
    assert outcome.skipped == 1
    assert guardian.resolved_calls == []


def test_other_finding_types_are_left_alone():
    state = _StateStoreStub()
    a, _b = _make_pair()
    registry = _RegistryStub([a])
    f = ValidationFinding(
        agent_id=AGENT_ID,
        finding_type=FindingType.orphan_entity,
        severity=FindingSeverity.warning,
        target_table="entities",
        target_id=a.id,
        detected_at=datetime.now(UTC),
        detected_by="test",
    )
    guardian = _Guardian([f])
    handler = MergeCandidatesHandler(state, registry, guardian, _MergeModel())  # type: ignore[arg-type]

    outcome = handler.run(AGENT_ID)
    assert outcome.merged == 0
    assert outcome.ignored == 0
    assert outcome.skipped == 0
    assert guardian.resolved_calls == []


def test_idempotent_second_run_processes_nothing_after_resolution():
    state = _StateStoreStub()
    a, b = _make_pair()
    state.add(a.id, _moment())
    state.add(b.id, _moment())
    registry = _RegistryStub([a, b])
    guardian = _Guardian([_similar_finding(a, b)])
    model = _MergeModel(confirmed=False, reason="distinct")
    handler = MergeCandidatesHandler(state, registry, guardian, model)  # type: ignore[arg-type]

    first = handler.run(AGENT_ID)
    second = handler.run(AGENT_ID)
    assert first.ignored == 1
    assert second.merged == 0
    assert second.ignored == 0
    assert second.skipped == 0


def test_llm_error_leaves_finding_unresolved_for_retry():
    state = _StateStoreStub()
    a, b = _make_pair()
    state.add(a.id, _moment())
    state.add(b.id, _moment())
    registry = _RegistryStub([a, b])

    class _Boom(MockReflectionModel):
        def decide_entity_merge(self, *args, **kwargs):
            raise RuntimeError("LLM down")

    guardian = _Guardian([_similar_finding(a, b)])
    handler = MergeCandidatesHandler(state, registry, guardian, _Boom())  # type: ignore[arg-type]

    outcome = handler.run(AGENT_ID)
    assert outcome.skipped == 1
    assert guardian.resolved_calls == []  # finding still unresolved


def test_default_reflection_model_returns_no_decision():
    """Subclasses that haven't wired the method get the default no-op."""
    out = MockReflectionModel().decide_entity_merge(
        Entity(agent_id=AGENT_ID, canonical_name="X", entity_type=EntityType.person),
        Entity(agent_id=AGENT_ID, canonical_name="Y", entity_type=EntityType.person),
        [],
        [],
    )
    assert isinstance(out, MergeDecisionOutput)
    assert out.confirmed is False
    assert out.reason == ""


def test_merge_decision_output_accepts_empty_reason_and_blank_canonical_name():
    """Regression: empty ``reason`` must not raise, and whitespace-only
    ``canonical_name`` becomes None. Splits the previously-shared
    ``strip_text`` validator into two field-specific validators so the
    ``reason: str`` field can't get None."""
    out = MergeDecisionOutput(confirmed=False, canonical_name="   ", reason="")
    assert out.reason == ""
    assert out.canonical_name is None
    out2 = MergeDecisionOutput(confirmed=True, canonical_name="Alice", reason="ok")
    assert out2.canonical_name == "Alice"
    assert out2.reason == "ok"
def test_already_disambiguated_drop_entity_does_not_double_merge_mention_count():
    """Regression: if a previous pass merged but resolve_finding failed,
    the next pass sees the same `similar_entities` finding plus a source
    entity already flagged ``needs_disambiguation=True``. The handler must
    NOT call ``merge_entities`` again (double-accumulates mention_count);
    it should resolve the leftover finding and move on."""
    state = _StateStoreStub()
    a, b = _make_pair()
    # Simulate the leftover state: b was already merged into a previously,
    # so b carries needs_disambiguation=True and a holds the inflated count.
    b.needs_disambiguation = True
    a.mention_count = 5
    registry = _RegistryStub([a, b])
    guardian = _Guardian([_similar_finding(a, b)])
    model = _MergeModel(confirmed=True, canonical_name="Alice", reason="confirmed")

    handler = MergeCandidatesHandler(state, registry, guardian, model)  # type: ignore[arg-type]
    outcome = handler.run(AGENT_ID)

    # Finding is resolved (no longer cluttering unresolved list).
    assert outcome.merged == 1
    assert outcome.skipped == 0
    # But the registry was NOT called again, so mention_count stays put.
    assert registry.merge_calls == []
    assert a.mention_count == 5
    # Note records that this was a leftover-finding cleanup.
    _fid, _resolution, _by, note = guardian.resolved_calls[0]
    assert "previously merged" in note
