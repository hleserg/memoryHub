"""
P0.1 — Contract tests for the StateStore port.

Every concrete implementation of ``StateStore`` must pass this suite.
Parametrised over ``["file"]`` today; add ``"in_memory"`` here when that
adapter is built.  A missing or mis-implemented method will surface immediately.

SYSTEM_MAP §2.1 / §5.3 regression freeze.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import pytest

from atman.adapters.storage import (
    FileStateStore,
    InMemoryExperienceStore,
    InMemoryStateStore,
    JsonlExperienceStore,
)
from atman.core.models import (
    Eigenstate,
    EmotionalDepth,
    ExperienceRecord,
    FeltSense,
    Identity,
    IdentitySnapshot,
    KeyMoment,
    LayerType,
    NarrativeDocument,
    NarrativeLayer,
    ReframingNote,
    SessionExperience,
)
from atman.core.ports.state_store import (
    DateRangeQuery,
    DepthQuery,
    FactRefsContainsQuery,
    SessionExperienceQuery,
    StateStore,
    ValuesTouchedQuery,
)

try:
    import psycopg  # noqa: F401

    from atman.adapters.state import PostgresStateStore

    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False
    PostgresStateStore = None  # type: ignore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(params=["file", "in_memory", "postgres"])
def store(request, tmp_path: Path) -> StateStore:
    if request.param == "file":
        return FileStateStore(tmp_path)
    if request.param == "in_memory":
        return InMemoryStateStore()
    if request.param == "postgres":
        if not POSTGRES_AVAILABLE or PostgresStateStore is None:
            pytest.skip("psycopg not installed")
        db_url = os.environ.get("TEST_DB_URL")
        if not db_url:
            pytest.skip("TEST_DB_URL not set")
        s = PostgresStateStore(db_url=db_url)
        # Clean up before test
        conn = s._get_conn()
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE public.key_moments")
        conn.commit()
        return s
    raise NotImplementedError(request.param)


def _skip_if_postgres_partial(store: StateStore) -> None:
    """Skip test if store is PostgresStateStore (only implements KeyMoment ops)."""
    if (
        POSTGRES_AVAILABLE
        and PostgresStateStore is not None
        and isinstance(store, PostgresStateStore)
    ):
        pytest.skip("PostgresStateStore only implements KeyMoment operations")


def _make_record(
    *,
    session_id=None,
    values: list[str] | None = None,
    depth: EmotionalDepth = EmotionalDepth.SURFACE,
    timestamp: datetime | None = None,
) -> tuple[ExperienceRecord, KeyMoment]:
    moment = KeyMoment(
        what_happened="contract test event",
        how_i_felt=FeltSense(
            emotional_valence=0.1,
            emotional_intensity=0.5,
            depth=depth,
        ),
        why_it_matters="contract coverage",
        values_touched=values or ["honesty"],
    )
    sid = session_id or uuid4()
    exp = SessionExperience(
        session_id=sid,
        timestamp=timestamp or datetime.now(UTC),
        key_moment_ids=[moment.id],
        avg_emotional_intensity=moment.how_i_felt.emotional_intensity,
        has_profound_moment=moment.how_i_felt.depth == EmotionalDepth.PROFOUND,
    )
    return ExperienceRecord(experience=exp), moment


def _persist(store: StateStore, record: ExperienceRecord, moment: KeyMoment) -> ExperienceRecord:
    created = store.create_experience(record)
    store.store_key_moments(record.experience.session_id, [moment])
    return created


def _make_identity() -> Identity:
    from atman.adapters.storage import FileStateStore
    from atman.core.services import IdentityService

    with TemporaryDirectory() as tmp:
        svc = IdentityService(FileStateStore(Path(tmp)))
        return svc.bootstrap_identity(uuid4())


def _make_narrative(identity_id) -> NarrativeDocument:
    return NarrativeDocument(
        identity_id=identity_id,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="I exist."),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="Recently."),
    )


# ---------------------------------------------------------------------------
# Experience operations
# ---------------------------------------------------------------------------


def test_create_and_get_experience(store: StateStore) -> None:
    _skip_if_postgres_partial(store)
    record, moment = _make_record()
    stored = _persist(store, record, moment)
    assert stored.experience.id == record.experience.id

    fetched = store.get_experience(record.experience.id)
    assert fetched is not None
    assert fetched.experience.id == record.experience.id


def test_get_experience_unknown_returns_none(store: StateStore) -> None:
    _skip_if_postgres_partial(store)
    assert store.get_experience(uuid4()) is None


def test_create_experience_duplicate_raises(store: StateStore) -> None:
    _skip_if_postgres_partial(store)
    record, moment = _make_record()
    _persist(store, record, moment)
    with pytest.raises(Exception):
        store.create_experience(record)


def test_add_reframing_note(store: StateStore) -> None:
    _skip_if_postgres_partial(store)
    record, moment = _make_record()
    _persist(store, record, moment)

    note = ReframingNote(reflection="new perspective", reflection_type="growth")
    updated = store.add_reframing_note(record.experience.id, note)
    assert updated is not None
    assert any(n.reflection == "new perspective" for n in updated.experience.reframing_notes)


def test_add_reframing_note_unknown_returns_none(store: StateStore) -> None:
    _skip_if_postgres_partial(store)
    note = ReframingNote(reflection="x", reflection_type="growth")
    assert store.add_reframing_note(uuid4(), note) is None


def test_add_reframing_note_preserves_key_moments(store: StateStore) -> None:
    _skip_if_postgres_partial(store)
    record, moment = _make_record()
    original_moment = moment.what_happened
    _persist(store, record, moment)

    note = ReframingNote(reflection="reframe", reflection_type="growth")
    updated = store.add_reframing_note(record.experience.id, note)
    assert updated is not None
    mid = updated.experience.key_moment_ids[0]
    loaded = store.get_key_moment(mid)
    assert loaded is not None
    assert loaded.what_happened == original_moment


def test_mark_accessed(store: StateStore) -> None:
    _skip_if_postgres_partial(store)
    record, moment = _make_record()
    _persist(store, record, moment)
    updated = store.mark_accessed(record.experience.id)
    assert updated is not None
    assert updated.experience.access_count == 1


def test_mark_accessed_unknown_returns_none(store: StateStore) -> None:
    _skip_if_postgres_partial(store)
    assert store.mark_accessed(uuid4()) is None


def test_list_recent_experiences_newest_first(store: StateStore) -> None:
    _skip_if_postgres_partial(store)
    base = datetime.now(UTC)
    for i in range(3):
        rec, m = _make_record(timestamp=base + timedelta(minutes=i))
        _persist(store, rec, m)

    results = store.list_recent_experiences(limit=10)
    assert len(results) == 3
    timestamps = [r.experience.timestamp for r in results]
    assert timestamps == sorted(timestamps, reverse=True)


def test_search_by_session(store: StateStore) -> None:
    _skip_if_postgres_partial(store)
    sid = uuid4()
    r1, m1 = _make_record(session_id=sid)
    _persist(store, r1, m1)
    r2, m2 = _make_record()
    _persist(store, r2, m2)

    results = store.search_experiences(SessionExperienceQuery(session_id=sid))
    assert len(results) == 1
    assert results[0].experience.session_id == sid


def test_search_by_values(store: StateStore) -> None:
    _skip_if_postgres_partial(store)
    r1, m1 = _make_record(values=["courage", "honesty"])
    _persist(store, r1, m1)
    r2, m2 = _make_record(values=["patience"])
    _persist(store, r2, m2)

    results = store.search_experiences(ValuesTouchedQuery(values=["courage"]))
    assert len(results) == 1


def test_search_by_depth(store: StateStore) -> None:
    _skip_if_postgres_partial(store)
    r1, m1 = _make_record(depth=EmotionalDepth.PROFOUND)
    _persist(store, r1, m1)
    r2, m2 = _make_record(depth=EmotionalDepth.SURFACE)
    _persist(store, r2, m2)

    results = store.search_experiences(DepthQuery(depth="profound"))
    assert len(results) == 1
    mid = results[0].experience.key_moment_ids[0]
    got = store.get_key_moment(mid)
    assert got is not None
    assert got.how_i_felt.depth == EmotionalDepth.PROFOUND


def test_search_by_date_range_excludes_outside(store: StateStore) -> None:
    _skip_if_postgres_partial(store)
    now = datetime.now(UTC)
    inside, mi = _make_record(timestamp=now)
    outside, mo = _make_record(timestamp=now - timedelta(days=10))
    _persist(store, inside, mi)
    _persist(store, outside, mo)

    q = DateRangeQuery(start_date=now - timedelta(hours=1), end_date=now + timedelta(hours=1))
    results = store.search_experiences(q)
    assert len(results) == 1
    assert results[0].experience.id == inside.experience.id


def test_search_by_fact_refs(store: StateStore) -> None:
    _skip_if_postgres_partial(store)
    """Contract test: FactRefsContainsQuery filters by fact_refs in key moments."""
    fact_id = uuid4()
    other_fact_id = uuid4()

    km_with = KeyMoment(
        what_happened="used fact",
        how_i_felt=FeltSense(
            emotional_valence=0.1, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
        ),
        why_it_matters="test",
        fact_refs=[fact_id],
    )
    with_fact = ExperienceRecord(
        experience=SessionExperience(
            session_id=uuid4(),
            key_moment_ids=[km_with.id],
            avg_emotional_intensity=km_with.how_i_felt.emotional_intensity,
            has_profound_moment=False,
        )
    )

    km_without = KeyMoment(
        what_happened="no fact",
        how_i_felt=FeltSense(
            emotional_valence=0.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
        ),
        why_it_matters="test",
    )
    without_fact = ExperienceRecord(
        experience=SessionExperience(
            session_id=uuid4(),
            key_moment_ids=[km_without.id],
            avg_emotional_intensity=km_without.how_i_felt.emotional_intensity,
            has_profound_moment=False,
        )
    )

    km_other = KeyMoment(
        what_happened="other fact",
        how_i_felt=FeltSense(
            emotional_valence=0.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
        ),
        why_it_matters="test",
        fact_refs=[other_fact_id],
    )
    with_other_fact = ExperienceRecord(
        experience=SessionExperience(
            session_id=uuid4(),
            key_moment_ids=[km_other.id],
            avg_emotional_intensity=km_other.how_i_felt.emotional_intensity,
            has_profound_moment=False,
        )
    )

    _persist(store, with_fact, km_with)
    _persist(store, without_fact, km_without)
    _persist(store, with_other_fact, km_other)

    # Query by fact_id
    results = store.search_experiences(FactRefsContainsQuery(fact_id=fact_id))

    # Should return only the experience with matching fact_id
    assert len(results) == 1
    assert results[0].experience.id == with_fact.experience.id
    mid = results[0].experience.key_moment_ids[0]
    got = store.get_key_moment(mid)
    assert got is not None
    assert fact_id in got.fact_refs


# ---------------------------------------------------------------------------
# Identity operations
# ---------------------------------------------------------------------------


def test_save_and_load_identity(store: StateStore) -> None:
    _skip_if_postgres_partial(store)
    identity = _make_identity()
    store.save_identity(identity)

    loaded = store.load_identity(identity.id)
    assert loaded is not None
    assert loaded.id == identity.id


def test_load_identity_unknown_returns_none(store: StateStore) -> None:
    _skip_if_postgres_partial(store)
    assert store.load_identity(uuid4()) is None


def test_create_and_list_identity_snapshots(store: StateStore) -> None:
    _skip_if_postgres_partial(store)
    identity = _make_identity()
    store.save_identity(identity)

    snap = IdentitySnapshot(
        identity_id=identity.id,
        identity_snapshot=identity.model_copy(deep=True),
        description="test snap",
        change_summary="initial",
    )
    store.create_identity_snapshot(snap)

    snaps = store.list_identity_snapshots(identity.id)
    assert len(snaps) == 1
    assert snaps[0].id == snap.id


def test_list_identity_snapshots_filters_by_identity(store: StateStore) -> None:
    _skip_if_postgres_partial(store)
    id1 = _make_identity()
    id2 = _make_identity()
    store.save_identity(id1)
    store.save_identity(id2)

    snap = IdentitySnapshot(
        identity_id=id1.id,
        identity_snapshot=id1.model_copy(deep=True),
        description="snap for id1",
        change_summary="x",
    )
    store.create_identity_snapshot(snap)

    assert len(store.list_identity_snapshots(id1.id)) == 1
    assert len(store.list_identity_snapshots(id2.id)) == 0


# ---------------------------------------------------------------------------
# Narrative operations
# ---------------------------------------------------------------------------


def test_save_and_load_narrative(store: StateStore) -> None:
    _skip_if_postgres_partial(store)
    identity = _make_identity()
    store.save_identity(identity)
    narrative = _make_narrative(identity.id)
    store.save_narrative(narrative)

    loaded = store.load_narrative(identity.id)
    assert loaded is not None
    assert loaded.id == narrative.id


def test_load_narrative_unknown_identity_returns_none(store: StateStore) -> None:
    _skip_if_postgres_partial(store)
    assert store.load_narrative(uuid4()) is None


# ---------------------------------------------------------------------------
# Eigenstate operations
# ---------------------------------------------------------------------------


def test_save_and_load_eigenstate(store: StateStore) -> None:
    _skip_if_postgres_partial(store)
    eigenstate = Eigenstate(
        session_id=uuid4(),
        emotional_tone=0.3,
        emotional_intensity=0.5,
        cognitive_load=0.2,
        open_threads=[],
        dominant_themes=["focus"],
        unresolved_tensions=[],
        session_summary="summary",
        key_insight="insight",
    )
    store.save_eigenstate(eigenstate)

    loaded = store.load_latest_eigenstate()
    assert loaded is not None
    assert loaded.id == eigenstate.id


def test_load_latest_eigenstate_no_data_returns_none(store: StateStore) -> None:
    _skip_if_postgres_partial(store)
    assert store.load_latest_eigenstate() is None


def test_load_latest_eigenstate_filters_by_session(store: StateStore) -> None:
    _skip_if_postgres_partial(store)
    sid = uuid4()
    e = Eigenstate(
        session_id=sid,
        emotional_tone=0.0,
        emotional_intensity=0.0,
        cognitive_load=0.0,
        open_threads=[],
        dominant_themes=[],
        unresolved_tensions=[],
        session_summary="s",
        key_insight="k",
    )
    store.save_eigenstate(e)

    assert store.load_latest_eigenstate(session_id=sid) is not None
    assert store.load_latest_eigenstate(session_id=uuid4()) is None


def test_load_latest_eigenstate_filters_by_identity(store: StateStore) -> None:
    _skip_if_postgres_partial(store)
    sid = uuid4()
    iid = uuid4()
    e = Eigenstate(
        session_id=sid,
        identity_id=iid,
        emotional_tone=0.0,
        emotional_intensity=0.0,
        cognitive_load=0.0,
        open_threads=[],
        dominant_themes=[],
        unresolved_tensions=[],
        session_summary="s",
        key_insight="k",
    )
    store.save_eigenstate(e)

    assert store.load_latest_eigenstate(identity_id=iid) is not None
    assert store.load_latest_eigenstate(identity_id=uuid4()) is None


def test_save_identity_expected_version_mismatch_raises(store: StateStore) -> None:
    _skip_if_postgres_partial(store)
    ident = _make_identity()
    store.save_identity(ident)
    stale = ident.model_copy(update={"self_description": "changed"})
    with pytest.raises(ValueError, match=r"version|Version|mismatch"):
        store.save_identity(stale, expected_version="definitely-wrong")


def test_save_narrative_optimistic_lock_mismatch_raises(store: StateStore) -> None:
    _skip_if_postgres_partial(store)
    ident = _make_identity()
    narrative = _make_narrative(ident.id)
    store.save_narrative(narrative)
    loaded_v1 = store.load_narrative(ident.id)
    assert loaded_v1 is not None
    winner = loaded_v1.model_copy(
        update={
            "recent_layer": loaded_v1.recent_layer.model_copy(
                update={"content": "winner branch saves first"}
            ),
            "updated_at": loaded_v1.updated_at + timedelta(seconds=1),
        }
    )
    store.save_narrative(winner)
    stale = loaded_v1.model_copy(
        update={
            "recent_layer": loaded_v1.recent_layer.model_copy(
                update={"content": "stale branch loses optimistic lock"}
            )
        }
    )
    with pytest.raises(ValueError, match=r"updated_at|mismatch|Version|version"):
        store.save_narrative(
            stale,
            expected_version=loaded_v1.schema_version,
            expected_updated_at=loaded_v1.updated_at,
        )


def test_archive_narrative_and_list(store: StateStore) -> None:
    _skip_if_postgres_partial(store)
    ident = _make_identity()
    narrative = _make_narrative(ident.id)
    store.save_narrative(narrative)
    store.archive_narrative(narrative.id, "integration test archive")
    archived = store.list_archived_narratives(ident.id, limit=5)
    assert len(archived) >= 1
    assert archived[0][0].id == narrative.id
    assert "integration test archive" in archived[0][1]


# ---------------------------------------------------------------------------
# KeyMoment operations (E21.3)
# ---------------------------------------------------------------------------


def test_create_and_get_key_moment(store: StateStore) -> None:
    """Test creating and retrieving a key moment."""
    km = KeyMoment(
        what_happened="test event",
        how_i_felt=FeltSense(
            emotional_valence=0.5,
            emotional_intensity=0.7,
            depth=EmotionalDepth.MEANINGFUL,
        ),
        why_it_matters="test reason",
    )
    stored = store.create_key_moment(km)
    assert stored.id == km.id

    retrieved = store.get_key_moment(km.id)
    assert retrieved is not None
    assert retrieved.id == km.id
    assert retrieved.what_happened == "test event"
    assert retrieved.why_it_matters == "test reason"


def test_create_key_moment_duplicate_raises(store: StateStore) -> None:
    """Test that creating duplicate key moment raises ValueError."""
    km = KeyMoment(
        what_happened="test",
        how_i_felt=FeltSense(
            emotional_valence=0.0,
            emotional_intensity=0.5,
            depth=EmotionalDepth.SURFACE,
        ),
        why_it_matters="reason",
    )
    store.create_key_moment(km)

    with pytest.raises(ValueError, match="already exists"):
        store.create_key_moment(km)


def test_get_key_moment_unknown_returns_none(store: StateStore) -> None:
    """Unknown key moment id returns None (port contract)."""
    assert store.get_key_moment(uuid4()) is None


def test_list_key_moments_empty(store: StateStore) -> None:
    """Test listing key moments when none exist."""
    moments = store.list_key_moments()
    assert moments == []


def test_list_key_moments_returns_all(store: StateStore) -> None:
    """Test listing all key moments."""
    km1 = KeyMoment(
        what_happened="first",
        how_i_felt=FeltSense(
            emotional_valence=0.1,
            emotional_intensity=0.5,
            depth=EmotionalDepth.SURFACE,
        ),
        why_it_matters="reason1",
    )
    km2 = KeyMoment(
        what_happened="second",
        how_i_felt=FeltSense(
            emotional_valence=0.2,
            emotional_intensity=0.6,
            depth=EmotionalDepth.MEANINGFUL,
        ),
        why_it_matters="reason2",
    )

    store.create_key_moment(km1)
    store.create_key_moment(km2)

    moments = store.list_key_moments()
    assert len(moments) == 2
    ids = {m.id for m in moments}
    assert km1.id in ids
    assert km2.id in ids


def test_list_key_moments_with_session_id_raises_not_implemented(store: StateStore) -> None:
    """Test that filtering by session_id returns an empty list (not NotImplementedError)."""
    # Skip for stores that don't support KeyMoment operations
    if isinstance(store, InMemoryExperienceStore | JsonlExperienceStore):
        pytest.skip("Store doesn't support KeyMoment operations")

    # session_id filtering is now supported — returns empty list for unknown session
    result = store.list_key_moments(session_id=uuid4())
    assert result == []
