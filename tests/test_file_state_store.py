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
        key_moment_ids=[moment.id],
        avg_emotional_intensity=0.5,
        has_profound_moment=False,
        importance=0.5,
        salience=0.5,
        timestamp=ts,
    )
    rec = ExperienceRecord(experience=exp)
    # Attach moment for tests that need it
    rec._test_moment = moment  # type: ignore[attr-defined]
    return rec


def test_experience_round_trip_and_get_missing() -> None:
    with TemporaryDirectory() as tmp:
        store = FileStateStore(Path(tmp))
        rec = _experience_record()
        store.create_experience(rec)

        loaded = store.get_experience(rec.experience.id)
        assert loaded is not None
        assert loaded.experience.id == rec.experience.id

        assert store.get_experience(uuid4()) is None


def test_create_experience_duplicate_raises_like_other_stores() -> None:
    with TemporaryDirectory() as tmp:
        store = FileStateStore(Path(tmp))
        rec = _experience_record()
        store.create_experience(rec)
        with pytest.raises(ValueError, match="already exists"):
            store.create_experience(rec)


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
        rec1 = _experience_record(session_id=sid, timestamp=t0, depth=EmotionalDepth.PROFOUND)
        store.create_experience(rec1)
        store.store_key_moments(sid, [rec1._test_moment])  # type: ignore[attr-defined]

        rec2 = _experience_record(session_id=uuid4(), timestamp=t0 + timedelta(days=1))
        store.create_experience(rec2)
        store.store_key_moments(rec2.experience.session_id, [rec2._test_moment])  # type: ignore[attr-defined]

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


def test_identity_save_failure_preserves_previous_file(monkeypatch: pytest.MonkeyPatch) -> None:
    with TemporaryDirectory() as tmp:
        store = FileStateStore(Path(tmp))
        agent = uuid4()
        original = Identity(id=agent, self_description="Stable.")
        store.save_identity(original)
        original_bytes = store.identity_path.read_bytes()

        def fail_replace(src: str | bytes | Path, dst: str | bytes | Path) -> None:
            raise OSError("simulated replace failure")

        monkeypatch.setattr("atman.adapters.storage._atomic_write.os.replace", fail_replace)

        changed = Identity(id=agent, self_description="Interrupted.")
        with pytest.raises(OSError, match="simulated replace failure"):
            store.save_identity(changed)

        assert store.identity_path.read_bytes() == original_bytes
        loaded = store.load_identity(agent)
        assert loaded is not None
        assert loaded.self_description == "Stable."
        assert list(Path(tmp).glob(".identity.json.*.tmp")) == []


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


def test_eigenstate_without_identity_not_visible_when_filtering_by_identity() -> None:
    """Legacy eigenstate rows without identity_id must not bind to an arbitrary agent."""
    with TemporaryDirectory() as tmp:
        store = FileStateStore(Path(tmp))
        sid = uuid4()
        es = Eigenstate(session_id=sid, emotional_tone=0.0, session_summary="Legacy.")
        store.save_eigenstate(es)
        assert store.load_latest_eigenstate(identity_id=uuid4()) is None


def test_save_narrative_expected_updated_at_mismatch() -> None:
    with TemporaryDirectory() as tmp:
        store = FileStateStore(Path(tmp))
        iid = uuid4()
        doc = NarrativeDocument(
            identity_id=iid,
            core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="C"),
            recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="R"),
            threads=[],
        )
        store.save_narrative(doc)
        loaded = store.load_narrative(iid)
        assert loaded is not None
        stale = loaded.model_copy(deep=True)
        stale.update_recent_layer("changed elsewhere")
        store.save_narrative(stale)
        loaded_again = store.load_narrative(iid)
        assert loaded_again is not None
        loaded_again.update_recent_layer("session manager attempt")
        with pytest.raises(ValueError, match="updated_at mismatch"):
            store.save_narrative(loaded_again, expected_updated_at=loaded.updated_at)


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


# --- SYSTEM_MAP §4.3 / §5.3: corrupted JSON state files ---


def test_get_experience_with_corrupted_json_raises_clear_error():
    """SYSTEM_MAP §4.3: ``JSONDecodeError`` from a state file is wrapped with file path context."""
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = FileStateStore(root)
        record = _experience_record()
        store.create_experience(record)

        # Corrupt the file written for that experience.
        experience_file = root / "experiences" / f"{record.experience.id}.json"
        experience_file.write_text("{not really json", encoding="utf-8")

        with pytest.raises(ValueError, match="Corrupted JSON in state store file"):
            store.get_experience(record.experience.id)


def test_load_identity_with_corrupted_json_raises_clear_error():
    """SYSTEM_MAP §4.3: corrupted ``identity.json`` raises ``ValueError`` with file context."""
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = FileStateStore(root)

        identity = Identity(self_description="Тестовое самоописание для проверки")
        store.save_identity(identity)

        # Corrupt the identity file.
        store.identity_path.write_text("{ broken", encoding="utf-8")

        with pytest.raises(ValueError, match="Corrupted JSON"):
            store.load_identity(identity.id)


# --- SYSTEM_MAP §4.4 / §5.3: concurrent identity writers ---


def test_save_identity_concurrent_writers_resolve_to_last_writer():
    """SYSTEM_MAP §5.3: concurrent identity writes resolve to a single committed state.

    The file backend currently implements last-writer-wins (no optimistic
    locking on identity). This test freezes that behavior so any future
    introduction of write-conflict semantics fails the test on purpose and
    forces a follow-up.
    """
    import threading

    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = FileStateStore(root)

        identity = Identity(self_description="Initial state")
        store.save_identity(identity)

        # Two concurrent updates with distinct self_descriptions.
        descriptions = [f"writer_{i}" for i in range(8)]
        errors: list[BaseException] = []

        def writer(desc: str) -> None:
            try:
                updated = identity.model_copy(update={"self_description": desc}, deep=True)
                store.save_identity(updated)
            except BaseException as exc:  # pragma: no cover - exercised only on failure
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(d,)) for d in descriptions]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []

        # Reload and verify the final state corresponds to one of the writers.
        reloaded = store.load_identity(identity.id)
        assert reloaded is not None
        assert reloaded.self_description in descriptions
