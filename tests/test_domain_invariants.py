"""
P1.5 — Domain invariant tests.

These tests encode rules that MUST hold regardless of which agent last
modified the codebase.  They are intentionally redundant with unit tests —
that's the point: if a refactor breaks an invariant, at least one of these
tests will catch it even if the direct unit test was accidentally removed.

Invariants covered:
1. list_recent_experiences always returns newest-first.
2. DateRangeQuery never returns records outside the range.
3. add_reframing_note never modifies key_moments.
4. Duplicate triggered_by on reframing notes is a no-op (idempotent).
5. reflection_run_key for the same day/identity is deterministic.
6. Micro reflection over the same session twice produces the same level.
7. ExperienceRecord.salience starts at 1.0 and can only decrease with time.
8. Access count increments by exactly 1 per mark_accessed call.
9. (E24) FactRecord.salience stays in [0.0, 1.0] across all mutation paths.
10. (E24) FactRecord.confirm() bumps confirmation_count by 1 and bumps
    salience by +0.1, capped at 1.0.
11. (E24) FactRecord.invalidate() zeroes salience for terminal states.
12. (E24) confirm_fact() at the backend port is a no-op for non-ACTIVE facts.
13. (E24) decay_stale_facts() only decays ACTIVE facts; non-ACTIVE are skipped.
14. (E21.5) unexamined_fact_refs: facts in _facts_read but NOT in any key moment
    fact_refs appear in SessionExperience.unexamined_fact_refs.
15. (E21.5) unexamined_fact_refs: facts in both _facts_read AND key moment fact_refs
    do NOT appear in unexamined_fact_refs (they are "colored").
16. (E21.5) unexamined_fact_refs: empty _facts_read produces empty unexamined list.
17. (E21.5) unexamined_fact_refs: facts only in key moment fact_refs (not in
    _facts_read) do not appear in unexamined_fact_refs.
18. (E21.7) Key moments preserve insertion order throughout session lifecycle.
19. (E21.7) Recording events never contaminates key moments list.
20. (E21.7) SessionExperience fact_refs aggregate from key moments AND _note_facts_read.
21. (E21.7) incomplete_coloring flag propagates from KeyMomentInput to SessionExperience.

SYSTEM_MAP §2.1 / §3 B–E / §4.2 / §5.3 regression freeze.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from atman.adapters.memory import InMemoryBackend
from atman.adapters.storage import FileStateStore, InMemoryStateStore
from atman.core.clock_impl import FrozenClock
from atman.core.models import (
    CoreValue,
    EmotionalDepth,
    ExperienceRecord,
    FactRecord,
    FeltSense,
    Goal,
    GoalHorizon,
    Identity,
    KeyMoment,
    KeyMomentInput,
    LayerType,
    NarrativeDocument,
    NarrativeLayer,
    ReframingNote,
    SessionEvent,
    SessionExperience,
)
from atman.core.models.fact import FactStatus
from atman.core.ports.state_store import DateRangeQuery
from atman.core.services import SessionManager
from atman.core.services.session_manager import deterministic_session_experience_id


def _record(
    *, timestamp: datetime | None = None, values: list[str] | None = None
) -> tuple[ExperienceRecord, KeyMoment]:
    moment = KeyMoment(
        what_happened="invariant test",
        how_i_felt=FeltSense(
            emotional_valence=0.5,
            emotional_intensity=0.5,
            depth=EmotionalDepth.SURFACE,
        ),
        why_it_matters="coverage",
        values_touched=values or ["honesty"],
    )
    exp = SessionExperience(
        session_id=uuid4(),
        timestamp=timestamp or datetime.now(UTC),
        key_moment_ids=[moment.id],
        avg_emotional_intensity=moment.how_i_felt.emotional_intensity,
        has_profound_moment=False,
    )
    return ExperienceRecord(experience=exp), moment


def _persist(store: FileStateStore, record: ExperienceRecord, moment: KeyMoment) -> None:
    store.create_experience(record)
    store.store_key_moments(record.experience.session_id, [moment])


# ---------------------------------------------------------------------------
# Invariant 1: list_recent_experiences → newest first
# ---------------------------------------------------------------------------


def test_invariant_list_recent_newest_first(tmp_path: Path) -> None:
    store = FileStateStore(tmp_path)
    base = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
    ids_in_order = []
    for i in range(5):
        r, m = _record(timestamp=base + timedelta(hours=i))
        _persist(store, r, m)
        ids_in_order.append(r.experience.id)

    results = store.list_recent_experiences(limit=10)
    timestamps = [r.experience.timestamp for r in results]
    assert timestamps == sorted(timestamps, reverse=True), "list_recent must return newest first"


# ---------------------------------------------------------------------------
# Invariant 2: DateRangeQuery never leaks outside the window
# ---------------------------------------------------------------------------


def test_invariant_date_range_excludes_outside(tmp_path: Path) -> None:
    store = FileStateStore(tmp_path)
    now = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)

    inside, mi = _record(timestamp=now)
    early, me = _record(timestamp=now - timedelta(days=2))
    late, ml = _record(timestamp=now + timedelta(days=2))

    for r, m in ((inside, mi), (early, me), (late, ml)):
        _persist(store, r, m)

    window = DateRangeQuery(
        start_date=now - timedelta(hours=1),
        end_date=now + timedelta(hours=1),
    )
    results = store.search_experiences(window)

    result_ids = {r.experience.id for r in results}
    assert inside.experience.id in result_ids
    assert early.experience.id not in result_ids, "early record must be excluded by DateRangeQuery"
    assert late.experience.id not in result_ids, "late record must be excluded by DateRangeQuery"


# ---------------------------------------------------------------------------
# Invariant 3: add_reframing_note never modifies key_moments
# ---------------------------------------------------------------------------


def test_invariant_reframing_note_does_not_mutate_key_moments(tmp_path: Path) -> None:
    store = FileStateStore(tmp_path)
    record, moment = _record()
    original_what = moment.what_happened
    original_values = list(moment.values_touched)
    _persist(store, record, moment)

    note = ReframingNote(reflection="new perspective", reflection_type="growth")
    updated = store.add_reframing_note(record.experience.id, note)

    assert updated is not None
    mid = updated.experience.key_moment_ids[0]
    loaded = store.get_key_moment(mid)
    assert loaded is not None
    assert loaded.what_happened == original_what
    assert list(loaded.values_touched) == original_values


# ---------------------------------------------------------------------------
# Invariant 4: duplicate triggered_by is idempotent
# ---------------------------------------------------------------------------


def test_invariant_duplicate_triggered_by_is_noop(tmp_path: Path) -> None:
    store = FileStateStore(tmp_path)
    record, moment = _record()
    _persist(store, record, moment)

    run_id = str(uuid4())
    note = ReframingNote(reflection="first", reflection_type="growth", triggered_by=run_id)
    store.add_reframing_note(record.experience.id, note)

    dup = ReframingNote(reflection="second", reflection_type="growth", triggered_by=run_id)
    result = store.add_reframing_note(record.experience.id, dup)

    assert result is not None
    notes = result.experience.reframing_notes
    assert len(notes) == 1, "duplicate triggered_by must not add a second note"
    assert notes[0].reflection == "first"


# ---------------------------------------------------------------------------
# Invariant 5: salience is in [0, 1] and calculate_current_salience decreases with time
# ---------------------------------------------------------------------------


def test_invariant_salience_is_in_valid_range() -> None:
    record, _moment = _record()
    assert 0.0 <= record.experience.salience <= 1.0


def test_invariant_salience_decreases_with_time() -> None:
    record, _moment = _record()
    # Pin last_accessed_at to "now" and compare salience at +0 vs +365 days
    from datetime import UTC, datetime

    t0 = datetime.now(UTC)
    record.experience.last_accessed_at = t0
    s_now = record.experience.calculate_current_salience(current_time=t0)
    t_future = t0 + timedelta(days=365)
    s_future = record.experience.calculate_current_salience(current_time=t_future)
    assert s_future < s_now, "salience must be lower one year later than at access time"
    assert s_future >= 0.0, "salience must never go below 0"


# ---------------------------------------------------------------------------
# Invariant 6: access_count increments by exactly 1 each call
# ---------------------------------------------------------------------------


def test_invariant_access_count_increments_by_one(tmp_path: Path) -> None:
    store = FileStateStore(tmp_path)
    record, moment = _record()
    _persist(store, record, moment)

    for expected in range(1, 4):
        updated = store.mark_accessed(record.experience.id)
        assert updated is not None
        assert updated.experience.access_count == expected


# ---------------------------------------------------------------------------
# Invariant 7: reflection_run_key is deterministic for same inputs
# ---------------------------------------------------------------------------


def test_invariant_reflection_run_key_deterministic() -> None:
    from atman.core.reflection_run_keys import daily_reflection_run_key_for_identity

    date = datetime(2025, 6, 1, tzinfo=UTC)
    identity_id = uuid4()
    key1 = daily_reflection_run_key_for_identity(date, identity_id)
    key2 = daily_reflection_run_key_for_identity(date, identity_id)

    assert key1 == key2, "run_key must be deterministic for same (date, identity_id)"


def test_invariant_reflection_run_key_differs_by_date() -> None:
    from atman.core.reflection_run_keys import daily_reflection_run_key_for_identity

    iid = uuid4()
    d1 = datetime(2025, 6, 1, tzinfo=UTC)
    d2 = datetime(2025, 6, 2, tzinfo=UTC)

    assert daily_reflection_run_key_for_identity(d1, iid) != daily_reflection_run_key_for_identity(
        d2, iid
    )


def test_invariant_reflection_run_key_differs_by_identity() -> None:
    from atman.core.reflection_run_keys import daily_reflection_run_key_for_identity

    date = datetime(2025, 6, 1, tzinfo=UTC)
    assert daily_reflection_run_key_for_identity(
        date, uuid4()
    ) != daily_reflection_run_key_for_identity(date, uuid4())


# ---------------------------------------------------------------------------
# Invariant 9 (E24): FactRecord.salience stays in [0.0, 1.0] across all
# mutation paths.
# ---------------------------------------------------------------------------


def test_invariant_fact_salience_in_unit_interval_after_confirm_and_invalidate() -> None:
    """Across confirm() and invalidate(), salience must never escape [0, 1]."""
    fact = FactRecord(content="x", source="unit", salience=0.95)
    # 50 confirms must clamp at 1.0 (each adds +0.1 capped at 1.0).
    for _ in range(50):
        fact.confirm()
        assert 0.0 <= fact.salience <= 1.0
    assert fact.salience == 1.0

    fact.invalidate(reason="zero")
    assert fact.salience == 0.0


# ---------------------------------------------------------------------------
# Invariant 10 (E24): confirm() bumps confirmation_count by 1 and salience
# by +0.1 capped at 1.0.
# ---------------------------------------------------------------------------


def test_invariant_fact_confirm_increments_count_and_salience_step() -> None:
    """Each confirm() call: count += 1; salience += 0.1 (clamped at 1.0)."""
    fact = FactRecord(content="x", source="unit", salience=0.5)
    assert fact.confirmation_count == 0

    fact.confirm()
    assert fact.confirmation_count == 1
    # 0.5 + 0.1 with float jitter; allow 1e-9 tolerance.
    assert abs(fact.salience - 0.6) < 1e-9
    assert fact.last_confirmed_at is not None


# ---------------------------------------------------------------------------
# Invariant 11 (E24): invalidate() zeros salience for terminal states.
# ---------------------------------------------------------------------------


def test_invariant_fact_invalidate_zeros_salience() -> None:
    """invalidate() must zero salience and stamp invalidated_at."""
    fact = FactRecord(content="x", source="unit", salience=0.95)
    fact.invalidate(reason="superseded by experiment")

    assert fact.status == FactStatus.INVALIDATED
    assert fact.salience == 0.0
    assert fact.invalidated_at is not None
    assert fact.invalidation_note == "superseded by experiment"


# ---------------------------------------------------------------------------
# Invariant 12 (E24): backend confirm_fact is a no-op for non-ACTIVE facts.
# A non-ACTIVE fact whose salience was already zeroed by invalidate() must
# not be silently resurrected to 0.1 on a stray confirm() call.
# ---------------------------------------------------------------------------


def test_invariant_backend_confirm_fact_is_noop_for_non_active() -> None:
    backend = InMemoryBackend()

    # ACTIVE → confirmable.
    active = FactRecord(content="active", source="unit", salience=0.5)
    backend.add_fact(active)
    assert backend.confirm_fact(active.id) is True

    # DISPUTED / SUPERSEDED / INVALIDATED → MUST be skipped.
    for status in (FactStatus.DISPUTED, FactStatus.SUPERSEDED, FactStatus.INVALIDATED):
        fact = FactRecord(content=f"f-{status.value}", source="unit", salience=0.5)
        backend.add_fact(fact)
        backend.invalidate_fact(fact.id, status=status, note="test")
        before = backend.get_fact(fact.id)
        assert before is not None
        assert backend.confirm_fact(fact.id) is False, (
            f"confirm_fact must skip {status.value} facts"
        )
        after = backend.get_fact(fact.id)
        assert after is not None
        assert after.confirmation_count == before.confirmation_count
        assert after.salience == before.salience
        assert after.last_confirmed_at == before.last_confirmed_at


# ---------------------------------------------------------------------------
# Invariant 13 (E24): decay_stale_facts only touches ACTIVE facts; the
# salience of DISPUTED/SUPERSEDED/INVALIDATED facts is preserved as-is.
# ---------------------------------------------------------------------------


def test_invariant_decay_stale_facts_only_decays_active() -> None:
    backend = InMemoryBackend()

    # ACTIVE fact, never confirmed → stale and should decay.
    stale_active = FactRecord(content="stale-active", source="unit", salience=0.8)
    backend.add_fact(stale_active)

    # DISPUTED fact preserved at salience 0.7 — must NOT decay.
    disputed = FactRecord(content="disputed", source="unit", salience=0.7)
    backend.add_fact(disputed)
    backend.invalidate_fact(disputed.id, status=FactStatus.DISPUTED, note="why")
    disputed_before = backend.get_fact(disputed.id)
    assert disputed_before is not None

    cutoff = datetime.now(UTC) + timedelta(seconds=1)
    decayed_count = backend.decay_stale_facts(before=cutoff, decay_factor=0.5)

    decayed_active = backend.get_fact(stale_active.id)
    assert decayed_active is not None
    assert decayed_count >= 1
    assert decayed_active.salience < 0.8  # strictly decayed

    disputed_after = backend.get_fact(disputed.id)
    assert disputed_after is not None
    # Non-ACTIVE facts are untouched: salience preserved exactly.
    assert disputed_after.salience == disputed_before.salience


# ---------------------------------------------------------------------------
# Invariants 14-17 (E21.5): unexamined_fact_refs computation
# ---------------------------------------------------------------------------


def test_invariant_unexamined_fact_refs_only_facts_read_but_not_colored() -> None:
    """Facts in _facts_read but NOT in any key moment fact_refs → unexamined_fact_refs."""
    store = InMemoryStateStore()
    agent_id = uuid4()
    identity = Identity(
        id=agent_id,
        self_description="test",
        core_values=[CoreValue(name="test", description="test", confidence=0.5)],
        goals=[Goal(content="test", horizon=GoalHorizon.SHORT)],
        emotional_baseline=0.0,
    )
    narrative = NarrativeDocument(
        identity_id=agent_id,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="core"),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="recent"),
    )
    store.save_identity(identity)
    store.save_narrative(narrative)

    manager = SessionManager(store, clock=FrozenClock(datetime(2025, 6, 1, tzinfo=UTC)))
    ctx = manager.start_session(agent_id)

    # Note 3 facts read, but only reference 1 in a key moment
    fact1, fact2, fact3 = uuid4(), uuid4(), uuid4()
    manager._note_facts_read(ctx.session_id, [fact1, fact2, fact3])

    # Key moment only references fact1
    moment = KeyMomentInput(
        what_happened="event",
        emotional_valence=0.2,
        emotional_intensity=0.5,
        depth=EmotionalDepth.SURFACE,
        why_it_matters="reason",
    )
    manager.append_key_moment_input(ctx.session_id, moment)
    # Manually inject fact_refs into the stored key moment
    session_result = manager._active_sessions[ctx.session_id]
    session_result.key_moments[0].fact_refs.append(fact1)

    manager.finish_session(ctx.session_id)

    # fact2 and fact3 should be unexamined (read but not colored)
    experience_id = deterministic_session_experience_id(ctx.session_id)
    experience_record = store.get_experience(experience_id)
    assert experience_record is not None
    unexamined = set(experience_record.experience.unexamined_fact_refs)
    assert fact2 in unexamined
    assert fact3 in unexamined
    assert fact1 not in unexamined  # colored in key moment


def test_invariant_unexamined_fact_refs_colored_facts_excluded() -> None:
    """Facts in both _facts_read AND key moment fact_refs do NOT appear in unexamined."""
    store = InMemoryStateStore()
    agent_id = uuid4()
    identity = Identity(
        id=agent_id,
        self_description="test",
        core_values=[CoreValue(name="test", description="test", confidence=0.5)],
        goals=[Goal(content="test", horizon=GoalHorizon.SHORT)],
        emotional_baseline=0.0,
    )
    narrative = NarrativeDocument(
        identity_id=agent_id,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="core"),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="recent"),
    )
    store.save_identity(identity)
    store.save_narrative(narrative)

    manager = SessionManager(store, clock=FrozenClock(datetime(2025, 6, 1, tzinfo=UTC)))
    ctx = manager.start_session(agent_id)

    # Note fact_id as read
    fact_id = uuid4()
    manager._note_facts_read(ctx.session_id, [fact_id])

    # Also reference it in a key moment
    moment = KeyMomentInput(
        what_happened="event",
        emotional_valence=0.2,
        emotional_intensity=0.5,
        depth=EmotionalDepth.SURFACE,
        why_it_matters="reason",
    )
    manager.append_key_moment_input(ctx.session_id, moment)
    session_result = manager._active_sessions[ctx.session_id]
    session_result.key_moments[0].fact_refs.append(fact_id)

    manager.finish_session(ctx.session_id)

    # fact_id is colored (in key moment), so NOT in unexamined
    experience_id = deterministic_session_experience_id(ctx.session_id)
    experience_record = store.get_experience(experience_id)
    assert experience_record is not None
    assert fact_id not in experience_record.experience.unexamined_fact_refs


def test_invariant_unexamined_fact_refs_empty_when_no_facts_read() -> None:
    """Empty _facts_read → empty unexamined_fact_refs."""
    store = InMemoryStateStore()
    agent_id = uuid4()
    identity = Identity(
        id=agent_id,
        self_description="test",
        core_values=[CoreValue(name="test", description="test", confidence=0.5)],
        goals=[Goal(content="test", horizon=GoalHorizon.SHORT)],
        emotional_baseline=0.0,
    )
    narrative = NarrativeDocument(
        identity_id=agent_id,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="core"),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="recent"),
    )
    store.save_identity(identity)
    store.save_narrative(narrative)

    manager = SessionManager(store, clock=FrozenClock(datetime(2025, 6, 1, tzinfo=UTC)))
    ctx = manager.start_session(agent_id)

    # No facts read; one key moment
    moment = KeyMomentInput(
        what_happened="event",
        emotional_valence=0.2,
        emotional_intensity=0.5,
        depth=EmotionalDepth.SURFACE,
        why_it_matters="reason",
    )
    manager.append_key_moment_input(ctx.session_id, moment)

    manager.finish_session(ctx.session_id)

    experience_id = deterministic_session_experience_id(ctx.session_id)
    experience_record = store.get_experience(experience_id)
    assert experience_record is not None
    assert experience_record.experience.unexamined_fact_refs == []


def test_invariant_unexamined_fact_refs_only_in_key_moment_not_unexamined() -> None:
    """Facts only in key moment fact_refs (not in _facts_read) do NOT appear in unexamined."""
    store = InMemoryStateStore()
    agent_id = uuid4()
    identity = Identity(
        id=agent_id,
        self_description="test",
        core_values=[CoreValue(name="test", description="test", confidence=0.5)],
        goals=[Goal(content="test", horizon=GoalHorizon.SHORT)],
        emotional_baseline=0.0,
    )
    narrative = NarrativeDocument(
        identity_id=agent_id,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="core"),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="recent"),
    )
    store.save_identity(identity)
    store.save_narrative(narrative)

    manager = SessionManager(store, clock=FrozenClock(datetime(2025, 6, 1, tzinfo=UTC)))
    ctx = manager.start_session(agent_id)

    # Note one fact as read
    read_fact = uuid4()
    manager._note_facts_read(ctx.session_id, [read_fact])

    # Key moment references a DIFFERENT fact (not in _facts_read)
    moment_fact = uuid4()
    moment = KeyMomentInput(
        what_happened="event",
        emotional_valence=0.2,
        emotional_intensity=0.5,
        depth=EmotionalDepth.SURFACE,
        why_it_matters="reason",
    )
    manager.append_key_moment_input(ctx.session_id, moment)
    session_result = manager._active_sessions[ctx.session_id]
    session_result.key_moments[0].fact_refs.append(moment_fact)

    manager.finish_session(ctx.session_id)

    experience_id = deterministic_session_experience_id(ctx.session_id)
    experience_record = store.get_experience(experience_id)
    assert experience_record is not None
    unexamined = experience_record.experience.unexamined_fact_refs

    # read_fact is unexamined (read but not colored)
    assert read_fact in unexamined
    # moment_fact is NOT unexamined (not in _facts_read at all)
    assert moment_fact not in unexamined


# ---------------------------------------------------------------------------
# Invariants 18-21 (E21.7): Session Manager key moment invariants
# ---------------------------------------------------------------------------


@pytest.fixture(params=["in_memory", "file_based"])
def _temp_storage(request, tmp_path):
    """Storage adapter for domain invariant tests."""
    if request.param == "in_memory":
        return InMemoryStateStore()
    else:
        return FileStateStore(workspace=tmp_path / "invariant_test")


@pytest.fixture
def _session_manager(_temp_storage):
    """Session manager with test identity and narrative."""
    identity = Identity(
        id=uuid4(),
        self_description="Domain invariant test agent",
        core_values=[CoreValue(name="test", description="test", confidence=0.8)],
        goals=[Goal(content="test", horizon=GoalHorizon.SHORT)],
        emotional_baseline=0.0,
    )
    narrative = NarrativeDocument(
        identity_id=identity.id,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="core"),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="recent"),
    )
    _temp_storage.save_identity(identity)
    _temp_storage.save_narrative(narrative)
    clock = FrozenClock(datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC))
    return SessionManager(_temp_storage, clock=clock), identity.id


def test_invariant_key_moments_preserve_temporal_order(_session_manager):
    """Key moments must preserve insertion order throughout session lifecycle."""
    manager, agent_id = _session_manager
    context = manager.start_session(agent_id)

    moments_order = []
    for i in range(5):
        moment = KeyMomentInput(
            what_happened=f"Event {i}",
            emotional_valence=0.1 * i,
            emotional_intensity=0.5,
            depth=EmotionalDepth.SURFACE,
            why_it_matters=f"Reason {i}",
        )
        manager.append_key_moment_input(context.session_id, moment)
        moments_order.append(f"Event {i}")

    active = manager.get_active_session(context.session_id)
    assert active is not None
    assert [m.what_happened for m in active.key_moments] == moments_order

    result = manager.finish_session(context.session_id)
    assert [m.what_happened for m in result.key_moments] == moments_order


def test_invariant_events_do_not_affect_key_moments(_session_manager):
    """Recording events must never contaminate key moments list."""
    manager, agent_id = _session_manager
    context = manager.start_session(agent_id)

    for i in range(10):
        manager.record_event(
            context.session_id,
            SessionEvent(
                session_id=context.session_id,
                event_type="regular_event",
                description=f"Event {i}",
            ),
        )

    active = manager.get_active_session(context.session_id)
    assert active is not None
    assert len(active.events) == 10
    assert len(active.key_moments) == 0

    manager.append_key_moment_input(
        context.session_id,
        KeyMomentInput(
            what_happened="Key moment",
            emotional_valence=0.5,
            emotional_intensity=0.5,
            depth=EmotionalDepth.SURFACE,
            why_it_matters="Important",
        ),
    )

    active = manager.get_active_session(context.session_id)
    assert active is not None
    assert len(active.key_moments) == 1
    assert len(active.events) == 10


def test_invariant_fact_refs_aggregate_from_all_sources(_session_manager, _temp_storage):
    """SessionExperience fact_refs must aggregate from key moments AND _note_facts_read."""
    manager, agent_id = _session_manager
    context = manager.start_session(agent_id)

    km_fact_id = uuid4()
    moment = KeyMomentInput(
        what_happened="Used fact A",
        emotional_valence=0.3,
        emotional_intensity=0.5,
        depth=EmotionalDepth.SURFACE,
        why_it_matters="Fact reference test",
        fact_refs=[km_fact_id],
    )
    manager.append_key_moment_input(context.session_id, moment)

    noted_fact_id = uuid4()
    manager._note_facts_read(context.session_id, [noted_fact_id])

    manager.finish_session(context.session_id)

    experiences = _temp_storage.list_recent_experiences(limit=1)
    assert len(experiences) == 1
    exp = experiences[0].experience
    assert km_fact_id in exp.fact_refs
    assert noted_fact_id in exp.fact_refs


def test_invariant_incomplete_coloring_flag_propagates(_session_manager, _temp_storage):
    """incomplete_coloring flag must propagate from KeyMomentInput to SessionExperience."""
    manager, agent_id = _session_manager
    context = manager.start_session(agent_id)

    manager.append_key_moment_input(
        context.session_id,
        KeyMomentInput(
            what_happened="Uncolored moment",
            emotional_valence=0.0,
            emotional_intensity=0.0,
            depth=EmotionalDepth.SURFACE,
            why_it_matters="Coloring was incomplete",
            incomplete_coloring=True,
        ),
    )

    manager.finish_session(context.session_id)

    experiences = _temp_storage.list_recent_experiences(limit=1)
    assert len(experiences) == 1
    assert experiences[0].experience.incomplete_coloring is True
