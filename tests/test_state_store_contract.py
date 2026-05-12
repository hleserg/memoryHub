"""
P0.1 — Contract tests for the StateStore port.

Every concrete implementation of ``StateStore`` must pass this suite.
Parametrised over ``["file"]`` today; add ``"in_memory"`` here when that
adapter is built.  A missing or mis-implemented method will surface immediately.

SYSTEM_MAP §2.1 / §5.3 regression freeze.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import pytest

from atman.adapters.storage import FileStateStore, InMemoryStateStore
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

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(params=["file", "in_memory"])
def store(request, tmp_path: Path) -> StateStore:
    if request.param == "file":
        return FileStateStore(tmp_path)
    if request.param == "in_memory":
        return InMemoryStateStore()
    raise NotImplementedError(request.param)


def _make_record(
    *,
    session_id=None,
    values: list[str] | None = None,
    depth: EmotionalDepth = EmotionalDepth.SURFACE,
    timestamp: datetime | None = None,
) -> ExperienceRecord:
    return ExperienceRecord(
        experience=SessionExperience(
            session_id=session_id or uuid4(),
            timestamp=timestamp or datetime.now(UTC),
            key_moments=[
                KeyMoment(
                    what_happened="contract test event",
                    how_i_felt=FeltSense(
                        emotional_valence=0.1,
                        emotional_intensity=0.5,
                        depth=depth,
                    ),
                    why_it_matters="contract coverage",
                    values_touched=values or ["honesty"],
                )
            ],
        )
    )


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
    record = _make_record()
    stored = store.create_experience(record)
    assert stored.experience.id == record.experience.id

    fetched = store.get_experience(record.experience.id)
    assert fetched is not None
    assert fetched.experience.id == record.experience.id


def test_get_experience_unknown_returns_none(store: StateStore) -> None:
    assert store.get_experience(uuid4()) is None


def test_create_experience_duplicate_raises(store: StateStore) -> None:
    record = _make_record()
    store.create_experience(record)
    with pytest.raises(Exception):
        store.create_experience(record)


def test_add_reframing_note(store: StateStore) -> None:
    record = _make_record()
    store.create_experience(record)

    note = ReframingNote(reflection="new perspective", reflection_type="growth")
    updated = store.add_reframing_note(record.experience.id, note)
    assert updated is not None
    assert any(n.reflection == "new perspective" for n in updated.experience.reframing_notes)


def test_add_reframing_note_unknown_returns_none(store: StateStore) -> None:
    note = ReframingNote(reflection="x", reflection_type="growth")
    assert store.add_reframing_note(uuid4(), note) is None


def test_add_reframing_note_preserves_key_moments(store: StateStore) -> None:
    record = _make_record()
    original_moment = record.experience.key_moments[0].what_happened
    store.create_experience(record)

    note = ReframingNote(reflection="reframe", reflection_type="growth")
    updated = store.add_reframing_note(record.experience.id, note)
    assert updated is not None
    assert updated.experience.key_moments[0].what_happened == original_moment


def test_mark_accessed(store: StateStore) -> None:
    record = _make_record()
    store.create_experience(record)
    updated = store.mark_accessed(record.experience.id)
    assert updated is not None
    assert updated.experience.access_count == 1


def test_mark_accessed_unknown_returns_none(store: StateStore) -> None:
    assert store.mark_accessed(uuid4()) is None


def test_list_recent_experiences_newest_first(store: StateStore) -> None:
    base = datetime.now(UTC)
    for i in range(3):
        store.create_experience(_make_record(timestamp=base + timedelta(minutes=i)))

    results = store.list_recent_experiences(limit=10)
    assert len(results) == 3
    timestamps = [r.experience.timestamp for r in results]
    assert timestamps == sorted(timestamps, reverse=True)


def test_search_by_session(store: StateStore) -> None:
    sid = uuid4()
    store.create_experience(_make_record(session_id=sid))
    store.create_experience(_make_record())

    results = store.search_experiences(SessionExperienceQuery(session_id=sid))
    assert len(results) == 1
    assert results[0].experience.session_id == sid


def test_search_by_values(store: StateStore) -> None:
    store.create_experience(_make_record(values=["courage", "honesty"]))
    store.create_experience(_make_record(values=["patience"]))

    results = store.search_experiences(ValuesTouchedQuery(values=["courage"]))
    assert len(results) == 1


def test_search_by_depth(store: StateStore) -> None:
    store.create_experience(_make_record(depth=EmotionalDepth.PROFOUND))
    store.create_experience(_make_record(depth=EmotionalDepth.SURFACE))

    results = store.search_experiences(DepthQuery(depth="profound"))
    assert len(results) == 1
    assert results[0].experience.key_moments[0].how_i_felt.depth == EmotionalDepth.PROFOUND


def test_search_by_date_range_excludes_outside(store: StateStore) -> None:
    now = datetime.now(UTC)
    inside = _make_record(timestamp=now)
    outside = _make_record(timestamp=now - timedelta(days=10))
    store.create_experience(inside)
    store.create_experience(outside)

    q = DateRangeQuery(start_date=now - timedelta(hours=1), end_date=now + timedelta(hours=1))
    results = store.search_experiences(q)
    assert len(results) == 1
    assert results[0].experience.id == inside.experience.id


def test_search_by_fact_refs(store: StateStore) -> None:
    """Contract test: FactRefsContainsQuery filters by fact_refs in key_moments."""
    fact_id = uuid4()
    other_fact_id = uuid4()

    # Create experience with target fact_id
    with_fact = ExperienceRecord(
        experience=SessionExperience(
            session_id=uuid4(),
            key_moments=[
                KeyMoment(
                    what_happened="used fact",
                    how_i_felt=FeltSense(
                        emotional_valence=0.1, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
                    ),
                    why_it_matters="test",
                    fact_refs=[fact_id],
                )
            ],
        )
    )

    # Create experience without target fact_id
    without_fact = ExperienceRecord(
        experience=SessionExperience(
            session_id=uuid4(),
            key_moments=[
                KeyMoment(
                    what_happened="no fact",
                    how_i_felt=FeltSense(
                        emotional_valence=0.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
                    ),
                    why_it_matters="test",
                )
            ],
        )
    )

    # Create experience with different fact_id
    with_other_fact = ExperienceRecord(
        experience=SessionExperience(
            session_id=uuid4(),
            key_moments=[
                KeyMoment(
                    what_happened="other fact",
                    how_i_felt=FeltSense(
                        emotional_valence=0.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
                    ),
                    why_it_matters="test",
                    fact_refs=[other_fact_id],
                )
            ],
        )
    )

    store.create_experience(with_fact)
    store.create_experience(without_fact)
    store.create_experience(with_other_fact)

    # Query by fact_id
    results = store.search_experiences(FactRefsContainsQuery(fact_id=fact_id))

    # Should return only the experience with matching fact_id
    assert len(results) == 1
    assert results[0].experience.id == with_fact.experience.id
    assert fact_id in results[0].experience.key_moments[0].fact_refs


# ---------------------------------------------------------------------------
# Identity operations
# ---------------------------------------------------------------------------


def test_save_and_load_identity(store: StateStore) -> None:
    identity = _make_identity()
    store.save_identity(identity)

    loaded = store.load_identity(identity.id)
    assert loaded is not None
    assert loaded.id == identity.id


def test_load_identity_unknown_returns_none(store: StateStore) -> None:
    assert store.load_identity(uuid4()) is None


def test_create_and_list_identity_snapshots(store: StateStore) -> None:
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
    identity = _make_identity()
    store.save_identity(identity)
    narrative = _make_narrative(identity.id)
    store.save_narrative(narrative)

    loaded = store.load_narrative(identity.id)
    assert loaded is not None
    assert loaded.id == narrative.id


def test_load_narrative_unknown_identity_returns_none(store: StateStore) -> None:
    assert store.load_narrative(uuid4()) is None


# ---------------------------------------------------------------------------
# Eigenstate operations
# ---------------------------------------------------------------------------


def test_save_and_load_eigenstate(store: StateStore) -> None:
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
    assert store.load_latest_eigenstate() is None


def test_load_latest_eigenstate_filters_by_session(store: StateStore) -> None:
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
    ident = _make_identity()
    store.save_identity(ident)
    stale = ident.model_copy(update={"self_description": "changed"})
    with pytest.raises(ValueError, match=r"version|Version|mismatch"):
        store.save_identity(stale, expected_version="definitely-wrong")


def test_save_narrative_optimistic_lock_mismatch_raises(store: StateStore) -> None:
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
    ident = _make_identity()
    narrative = _make_narrative(ident.id)
    store.save_narrative(narrative)
    store.archive_narrative(narrative.id, "integration test archive")
    archived = store.list_archived_narratives(ident.id, limit=5)
    assert len(archived) >= 1
    assert archived[0][0].id == narrative.id
    assert "integration test archive" in archived[0][1]


# ---------------------------------------------------------------------------
# KeyMoment operations (E21.2)
# ---------------------------------------------------------------------------


def test_create_and_get_key_moment(store: StateStore) -> None:
    """Test create_key_moment and get_key_moment."""
    session_id = uuid4()
    moment = KeyMoment(
        what_happened="Test event",
        how_i_felt=FeltSense(
            emotional_valence=0.5,
            emotional_intensity=0.7,
            depth=EmotionalDepth.MEANINGFUL,
        ),
        why_it_matters="Contract test",
        values_touched=["honesty"],
    )

    store.create_key_moment(moment, session_id)
    retrieved = store.get_key_moment(moment.id)

    assert retrieved.id == moment.id
    assert retrieved.what_happened == "Test event"
    assert retrieved.why_it_matters == "Contract test"


def test_create_key_moment_duplicate_raises(store: StateStore) -> None:
    """Test that creating duplicate key moment raises ValueError."""
    session_id = uuid4()
    moment = KeyMoment(
        what_happened="Test event",
        how_i_felt=FeltSense(
            emotional_valence=0.5,
            emotional_intensity=0.7,
            depth=EmotionalDepth.MEANINGFUL,
        ),
        why_it_matters="Contract test",
    )

    store.create_key_moment(moment, session_id)

    with pytest.raises(ValueError, match=r"already exists"):
        store.create_key_moment(moment, session_id)


def test_get_key_moment_not_found_raises(store: StateStore) -> None:
    """Test that getting non-existent key moment raises KeyError."""
    fake_id = uuid4()

    with pytest.raises(KeyError, match=r"not found"):
        store.get_key_moment(fake_id)


def test_list_key_moments_empty(store: StateStore) -> None:
    """Test listing key moments for session with no moments."""
    session_id = uuid4()
    moments = store.list_key_moments(session_id)

    assert moments == []


def test_list_key_moments_returns_session_moments_only(store: StateStore) -> None:
    """Test that list_key_moments returns only moments for specified session."""
    session1 = uuid4()
    session2 = uuid4()

    moment1 = KeyMoment(
        what_happened="Session 1 event",
        how_i_felt=FeltSense(
            emotional_valence=0.5,
            emotional_intensity=0.7,
            depth=EmotionalDepth.MEANINGFUL,
        ),
        why_it_matters="Test",
    )
    moment2 = KeyMoment(
        what_happened="Session 2 event",
        how_i_felt=FeltSense(
            emotional_valence=0.3,
            emotional_intensity=0.6,
            depth=EmotionalDepth.SURFACE,
        ),
        why_it_matters="Test",
    )

    store.create_key_moment(moment1, session1)
    store.create_key_moment(moment2, session2)

    session1_moments = store.list_key_moments(session1)
    session2_moments = store.list_key_moments(session2)

    assert len(session1_moments) == 1
    assert len(session2_moments) == 1
    assert session1_moments[0].id == moment1.id
    assert session2_moments[0].id == moment2.id


def test_list_key_moments_ordered_by_timestamp(store: StateStore) -> None:
    """Test that list_key_moments returns moments ordered by timestamp."""
    session_id = uuid4()

    # Create moments with explicit timestamps
    now = datetime.now(UTC)
    moment1 = KeyMoment(
        what_happened="First event",
        when=now,
        how_i_felt=FeltSense(
            emotional_valence=0.5,
            emotional_intensity=0.7,
            depth=EmotionalDepth.MEANINGFUL,
        ),
        why_it_matters="Test",
    )
    moment2 = KeyMoment(
        what_happened="Second event",
        when=now + timedelta(seconds=10),
        how_i_felt=FeltSense(
            emotional_valence=0.3,
            emotional_intensity=0.6,
            depth=EmotionalDepth.SURFACE,
        ),
        why_it_matters="Test",
    )
    moment3 = KeyMoment(
        what_happened="Third event",
        when=now + timedelta(seconds=20),
        how_i_felt=FeltSense(
            emotional_valence=0.8,
            emotional_intensity=0.9,
            depth=EmotionalDepth.PROFOUND,
        ),
        why_it_matters="Test",
    )

    # Store in non-chronological order
    store.create_key_moment(moment2, session_id)
    store.create_key_moment(moment1, session_id)
    store.create_key_moment(moment3, session_id)

    moments = store.list_key_moments(session_id)

    assert len(moments) == 3
    assert moments[0].what_happened == "First event"
    assert moments[1].what_happened == "Second event"
    assert moments[2].what_happened == "Third event"
