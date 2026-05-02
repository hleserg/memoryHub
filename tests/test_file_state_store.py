"""Tests for FileStateStore (experiences, identity, narrative, eigenstate on disk)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

import pytest

from atman.adapters.storage import FileStateStore
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
from atman.core.ports import DateRangeQuery, DepthQuery, SessionExperienceQuery, ValuesTouchedQuery


def _experience_record(
    *,
    session_id=None,
    values_touched: list[str] | None = None,
    depth: EmotionalDepth = EmotionalDepth.SURFACE,
    timestamp: datetime | None = None,
) -> ExperienceRecord:
    sid = session_id or uuid4()
    felt = FeltSense(
        emotional_valence=0.1,
        emotional_intensity=0.5,
        depth=depth,
    )
    moment = KeyMoment(
        what_happened="Recorded moment",
        how_i_felt=felt,
        why_it_matters="Testing",
        values_touched=values_touched or ["patience"],
    )
    ts = timestamp or datetime.now(UTC)
    exp = SessionExperience(
        session_id=sid,
        key_moments=[moment],
        importance=0.5,
        salience=0.5,
        timestamp=ts,
    )
    return ExperienceRecord(experience=exp)


def test_experience_round_trip_and_get_missing() -> None:
    with TemporaryDirectory() as tmp:
        store = FileStateStore(Path(tmp))
        rec = _experience_record()
        store.create_experience(rec)

        loaded = store.get_experience(rec.experience.id)
        assert loaded is not None
        assert loaded.experience.id == rec.experience.id

        assert store.get_experience(uuid4()) is None


def test_add_reframing_note_and_mark_accessed_missing() -> None:
    with TemporaryDirectory() as tmp:
        store = FileStateStore(Path(tmp))
        note = ReframingNote(reflection="Later insight")
        assert store.add_reframing_note(uuid4(), note) is None
        assert store.mark_accessed(uuid4()) is None


def test_add_reframing_note_and_mark_accessed_success() -> None:
    with TemporaryDirectory() as tmp:
        store = FileStateStore(Path(tmp))
        rec = _experience_record()
        store.create_experience(rec)
        eid = rec.experience.id

        updated = store.add_reframing_note(eid, ReframingNote(reflection="R1"))
        assert updated is not None
        assert len(updated.experience.reframing_notes) == 1

        accessed = store.mark_accessed(eid)
        assert accessed is not None
        assert accessed.experience.access_count >= 1


def test_search_experiences_filters_and_limit() -> None:
    with TemporaryDirectory() as tmp:
        store = FileStateStore(Path(tmp))
        sid = uuid4()
        t0 = datetime(2026, 1, 10, 12, 0, 0, tzinfo=UTC)
        store.create_experience(
            _experience_record(session_id=sid, timestamp=t0, depth=EmotionalDepth.PROFOUND)
        )
        store.create_experience(
            _experience_record(session_id=uuid4(), timestamp=t0 + timedelta(days=1))
        )

        all_recent = store.search_experiences(query=None, limit=10)
        assert len(all_recent) == 2

        by_session = store.search_experiences(SessionExperienceQuery(sid), limit=10)
        assert len(by_session) == 1
        assert by_session[0].experience.session_id == sid

        by_values = store.search_experiences(ValuesTouchedQuery(["patience"]), limit=10)
        assert len(by_values) == 2

        by_depth = store.search_experiences(DepthQuery("profound"), limit=10)
        assert len(by_depth) == 1

        dr = DateRangeQuery(
            start_date=t0 - timedelta(days=1),
            end_date=t0 + timedelta(days=2),
        )
        by_date = store.search_experiences(dr, limit=10)
        assert len(by_date) == 2

        limited = store.search_experiences(query=None, limit=1)
        assert len(limited) == 1


def test_list_recent_experiences_delegates() -> None:
    with TemporaryDirectory() as tmp:
        store = FileStateStore(Path(tmp))
        store.create_experience(_experience_record())
        out = store.list_recent_experiences(limit=5)
        assert len(out) == 1


def test_identity_load_save_mismatch_and_version() -> None:
    with TemporaryDirectory() as tmp:
        store = FileStateStore(Path(tmp))
        agent = uuid4()
        assert store.load_identity(agent) is None

        identity = Identity(id=agent, self_description="I exist.")
        store.save_identity(identity)

        assert store.load_identity(uuid4()) is None
        assert store.load_identity(agent) is not None

        with pytest.raises(ValueError, match="Version mismatch"):
            store.save_identity(identity, expected_version="wrong-version")


def test_identity_snapshots_listing() -> None:
    with TemporaryDirectory() as tmp:
        store = FileStateStore(Path(tmp))
        agent = uuid4()
        identity = Identity(id=agent, self_description="Snap me.")
        store.save_identity(identity)

        snap = IdentitySnapshot(
            identity_id=agent,
            description="Checkpoint",
            identity_snapshot=identity,
            change_summary="test",
        )
        store.create_identity_snapshot(snap)

        listed = store.list_identity_snapshots(agent, limit=10)
        assert len(listed) == 1
        assert listed[0].identity_id == agent

        other = uuid4()
        assert store.list_identity_snapshots(other, limit=10) == []


def test_narrative_load_mismatch_version_save() -> None:
    with TemporaryDirectory() as tmp:
        store = FileStateStore(Path(tmp))
        iid = uuid4()
        assert store.load_narrative(iid) is None

        narrative = NarrativeDocument(
            identity_id=iid,
            core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="I am core."),
            recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="I am recent."),
            threads=[],
        )
        store.save_narrative(narrative)

        assert store.load_narrative(uuid4()) is None
        loaded = store.load_narrative(iid)
        assert loaded is not None

        with pytest.raises(ValueError, match="Version mismatch"):
            store.save_narrative(loaded, expected_version="not-matching")


def test_archive_narrative_noop_and_list_archived() -> None:
    with TemporaryDirectory() as tmp:
        store = FileStateStore(Path(tmp))
        iid = uuid4()
        narrative = NarrativeDocument(
            identity_id=iid,
            core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="C"),
            recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="R"),
            threads=[],
        )
        store.save_narrative(narrative)

        store.archive_narrative(uuid4(), "no match")
        assert store.list_archived_narratives(iid) == []

        store.archive_narrative(narrative.id, "archived for test")
        archived = store.list_archived_narratives(iid, limit=5)
        assert len(archived) == 1
        assert archived[0][1] == "archived for test"
        assert archived[0][0].id == narrative.id


def test_eigenstate_round_trip_and_session_filter() -> None:
    with TemporaryDirectory() as tmp:
        store = FileStateStore(Path(tmp))
        sid = uuid4()
        assert store.load_latest_eigenstate() is None

        es = Eigenstate(session_id=sid, emotional_tone=0.0, session_summary="Done.")
        store.save_eigenstate(es)

        assert store.load_latest_eigenstate(session_id=uuid4()) is None
        loaded = store.load_latest_eigenstate(session_id=sid)
        assert loaded is not None
        assert loaded.session_id == sid

        assert store.load_latest_eigenstate() is not None


def test_archive_narrative_when_narrative_file_missing() -> None:
    with TemporaryDirectory() as tmp:
        store = FileStateStore(Path(tmp))
        store.archive_narrative(uuid4(), "orphan")


def test_search_values_no_match_and_depth_no_match() -> None:
    with TemporaryDirectory() as tmp:
        store = FileStateStore(Path(tmp))
        store.create_experience(_experience_record(values_touched=["alpha"]))
        assert store.search_experiences(ValuesTouchedQuery(["zzz"]), limit=10) == []
        assert store.search_experiences(DepthQuery("profound"), limit=10) == []


def test_save_identity_first_write_with_expected_version_no_conflict() -> None:
    with TemporaryDirectory() as tmp:
        store = FileStateStore(Path(tmp))
        agent = uuid4()
        identity = Identity(id=agent, self_description="First.")
        out = store.save_identity(identity, expected_version=identity.schema_version)
        assert out.id == agent


def test_save_narrative_first_write_with_expected_version() -> None:
    with TemporaryDirectory() as tmp:
        store = FileStateStore(Path(tmp))
        iid = uuid4()
        doc = NarrativeDocument(
            identity_id=iid,
            core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="C"),
            recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="R"),
            threads=[],
        )
        store.save_narrative(doc, expected_version=doc.schema_version)


def test_list_archived_filters_other_identity() -> None:
    with TemporaryDirectory() as tmp:
        store = FileStateStore(Path(tmp))
        a, b = uuid4(), uuid4()
        na = NarrativeDocument(
            identity_id=a,
            core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="a"),
            recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="r"),
            threads=[],
        )
        nb = NarrativeDocument(
            identity_id=b,
            core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="b"),
            recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="r"),
            threads=[],
        )
        store.save_narrative(na)
        store.archive_narrative(na.id, "a-reason")
        store.save_narrative(nb)
        store.archive_narrative(nb.id, "b-reason")

        for_a = store.list_archived_narratives(a, limit=10)
        assert len(for_a) == 1
        assert for_a[0][0].identity_id == a


def test_list_archived_normalizes_naive_archived_at_and_sorts_with_utc_fields() -> None:
    """Legacy archives may store naive ISO timestamps; loading must yield UTC-aware datetimes."""
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = FileStateStore(root)
        iid = uuid4()
        doc = NarrativeDocument(
            identity_id=iid,
            core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="C"),
            recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="R"),
            threads=[],
        )
        legacy = {
            "narrative": doc.model_dump(mode="json"),
            "reason": "legacy",
            "archived_at": "2020-01-01T12:00:00",
        }
        archive_path = root / "narrative_archive" / f"{doc.id}_legacy.json"
        archive_path.write_text(json.dumps(legacy), encoding="utf-8")

        listed = store.list_archived_narratives(iid, limit=10)
        assert len(listed) == 1
        archived_at = listed[0][2]
        assert archived_at.tzinfo is not None
        _ = doc.created_at <= archived_at
