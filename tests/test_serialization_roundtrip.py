"""
P0.2 — Serialization round-trip tests for every persisted entity.

Each test: create entity → serialize to JSON → deserialize → assert equality.
Also tests: save via FileStateStore → restart (new store instance) → load.

Guards against: field renames, type changes, added required fields, removed
optional fields that break deserialization of old data.

SYSTEM_MAP §2.1 / §5.3 regression freeze.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from atman.adapters.storage import FileStateStore
from atman.core.models import (
    Eigenstate,
    EmotionalDepth,
    ExperienceRecord,
    FeltSense,
    HealthCriterionOutput,
    Identity,
    IdentitySnapshot,
    KeyMoment,
    LayerType,
    NarrativeDocument,
    NarrativeLayer,
    NarrativeUpdateOutput,
    PatternDetectionOutput,
    ReframingNote,
    ReframingNoteOutput,
    SessionExperience,
)
from atman.core.services import IdentityService

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_experience_record() -> ExperienceRecord:
    return ExperienceRecord(
        experience=SessionExperience(
            session_id=uuid4(),
            timestamp=datetime.now(UTC),
            key_moments=[
                KeyMoment(
                    what_happened="round-trip test",
                    how_i_felt=FeltSense(
                        emotional_valence=0.6,
                        emotional_intensity=0.7,
                        depth=EmotionalDepth.MEANINGFUL,
                    ),
                    why_it_matters="coverage",
                    values_touched=["honesty", "competence"],
                )
            ],
        )
    )


def _bootstrap_identity(store: FileStateStore) -> Identity:
    svc = IdentityService(store)
    return svc.bootstrap_identity(uuid4())


# ---------------------------------------------------------------------------
# Pure model round-trips (no disk)
# ---------------------------------------------------------------------------


def test_experience_record_json_roundtrip() -> None:
    record = _make_experience_record()
    j = record.model_dump_json()
    restored = ExperienceRecord.model_validate_json(j)

    assert restored.experience.id == record.experience.id
    assert restored.experience.session_id == record.experience.session_id
    assert restored.experience.key_moments[0].what_happened == "round-trip test"
    assert restored.experience.key_moments[0].how_i_felt.depth == EmotionalDepth.MEANINGFUL
    assert set(restored.experience.key_moments[0].values_touched) == {"honesty", "competence"}


def test_experience_record_with_reframing_note_roundtrip() -> None:
    record = _make_experience_record()
    record.experience.add_reframing_note(
        ReframingNote(reflection="see it differently", reflection_type="growth")
    )
    j = record.model_dump_json()
    restored = ExperienceRecord.model_validate_json(j)

    assert len(restored.experience.reframing_notes) == 1
    assert restored.experience.reframing_notes[0].reflection == "see it differently"


def test_identity_json_roundtrip(tmp_path: Path) -> None:
    store = FileStateStore(tmp_path)
    identity = _bootstrap_identity(store)
    j = identity.model_dump_json()
    restored = Identity.model_validate_json(j)

    assert restored.id == identity.id
    assert restored.self_description == identity.self_description
    assert restored.schema_version == identity.schema_version
    assert len(restored.open_questions) == len(identity.open_questions)


def test_identity_snapshot_json_roundtrip(tmp_path: Path) -> None:
    store = FileStateStore(tmp_path)
    identity = _bootstrap_identity(store)
    snap = IdentitySnapshot(
        identity_id=identity.id,
        identity_snapshot=identity.model_copy(deep=True),
        description="snapshot round-trip",
        change_summary="initial",
    )
    j = snap.model_dump_json()
    restored = IdentitySnapshot.model_validate_json(j)

    assert restored.id == snap.id
    assert restored.identity_id == identity.id
    assert restored.description == "snapshot round-trip"


def test_narrative_document_json_roundtrip() -> None:
    iid = uuid4()
    narrative = NarrativeDocument(
        identity_id=iid,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="Core content here."),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="Recent events."),
    )
    j = narrative.model_dump_json()
    restored = NarrativeDocument.model_validate_json(j)

    assert restored.id == narrative.id
    assert restored.identity_id == iid
    assert restored.core_layer.content == "Core content here."
    assert restored.recent_layer.content == "Recent events."


def test_eigenstate_json_roundtrip() -> None:
    e = Eigenstate(
        session_id=uuid4(),
        emotional_tone=0.4,
        emotional_intensity=0.6,
        cognitive_load=0.3,
        open_threads=["unresolved question"],
        dominant_themes=["growth", "focus"],
        unresolved_tensions=["tension A"],
        session_summary="A productive session.",
        key_insight="Everything connects.",
    )
    j = e.model_dump_json()
    restored = Eigenstate.model_validate_json(j)

    assert restored.id == e.id
    assert restored.session_id == e.session_id
    assert restored.dominant_themes == ["growth", "focus"]
    assert restored.key_insight == "Everything connects."


# ---------------------------------------------------------------------------
# Disk round-trips: save → new store instance → load
# ---------------------------------------------------------------------------


def test_experience_persists_across_store_restart(tmp_path: Path) -> None:
    record = _make_experience_record()

    store1 = FileStateStore(tmp_path)
    store1.create_experience(record)

    store2 = FileStateStore(tmp_path)
    loaded = store2.get_experience(record.experience.id)

    assert loaded is not None
    assert loaded.experience.id == record.experience.id
    assert loaded.experience.key_moments[0].what_happened == "round-trip test"


def test_identity_persists_across_store_restart(tmp_path: Path) -> None:
    store1 = FileStateStore(tmp_path)
    identity = _bootstrap_identity(store1)

    store2 = FileStateStore(tmp_path)
    loaded = store2.load_identity(identity.id)

    assert loaded is not None
    assert loaded.id == identity.id
    assert loaded.self_description == identity.self_description


def test_narrative_persists_across_store_restart(tmp_path: Path) -> None:
    iid = uuid4()
    narrative = NarrativeDocument(
        identity_id=iid,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="Persisted core."),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="Persisted recent."),
    )

    store1 = FileStateStore(tmp_path)
    store1.save_narrative(narrative)

    store2 = FileStateStore(tmp_path)
    loaded = store2.load_narrative(iid)

    assert loaded is not None
    assert loaded.id == narrative.id
    assert loaded.core_layer.content == "Persisted core."


def test_eigenstate_persists_across_store_restart(tmp_path: Path) -> None:
    e = Eigenstate(
        session_id=uuid4(),
        emotional_tone=0.2,
        emotional_intensity=0.3,
        cognitive_load=0.1,
        open_threads=[],
        dominant_themes=["persistence"],
        unresolved_tensions=[],
        session_summary="Test persistence.",
        key_insight="Data survives.",
    )

    store1 = FileStateStore(tmp_path)
    store1.save_eigenstate(e)

    store2 = FileStateStore(tmp_path)
    loaded = store2.load_latest_eigenstate()

    assert loaded is not None
    assert loaded.id == e.id
    assert loaded.dominant_themes == ["persistence"]


def test_reframing_note_persists_across_store_restart(tmp_path: Path) -> None:
    record = _make_experience_record()
    store1 = FileStateStore(tmp_path)
    store1.create_experience(record)
    note = ReframingNote(reflection="persisted reframe", reflection_type="growth")
    store1.add_reframing_note(record.experience.id, note)

    store2 = FileStateStore(tmp_path)
    loaded = store2.get_experience(record.experience.id)

    assert loaded is not None
    assert len(loaded.experience.reframing_notes) == 1
    assert loaded.experience.reframing_notes[0].reflection == "persisted reframe"


def test_reflection_model_dto_json_roundtrip() -> None:
    """Round-trip for structured ReflectionModel outputs (GitHub #146)."""
    samples = [
        ReframingNoteOutput(reflection="note", reflection_type="pattern"),
        PatternDetectionOutput(
            description="desc",
            confidence=0.5,
            potential_habit="h",
            potential_principle="p",
        ),
        NarrativeUpdateOutput(body="fragment"),
        HealthCriterionOutput(
            score=0.55,
            evidence=["a", "b"],
            concerns=["c"],
        ),
    ]
    for obj in samples:
        j = obj.model_dump_json()
        restored = type(obj).model_validate_json(j)
        assert restored == obj


def test_reflection_model_dto_edge_cases() -> None:
    """Edge cases for structured ReflectionModel outputs (GitHub #146 / review)."""
    # ReframingNoteOutput with empty reflection (skip-persistence sentinel)
    empty_reframe = ReframingNoteOutput(reflection="", reflection_type="insight")
    assert empty_reframe.reflection == ""
    assert empty_reframe.reflection_type == "insight"
    j1 = empty_reframe.model_dump_json()
    r1 = ReframingNoteOutput.model_validate_json(j1)
    assert r1.reflection == ""

    # ReframingNoteOutput with empty reflection_type → should fallback to "insight"
    empty_type = ReframingNoteOutput(reflection="text", reflection_type="")
    assert empty_type.reflection_type == "insight"  # model_validator ensures non-empty

    # PatternDetectionOutput with confidence=None (default behavior)
    no_confidence = PatternDetectionOutput(description="pattern without confidence")
    assert no_confidence.confidence is None
    j2 = no_confidence.model_dump_json()
    r2 = PatternDetectionOutput.model_validate_json(j2)
    assert r2.confidence is None

    # HealthCriterionOutput with empty strings in lists → normalize_lists strips them
    messy_lists = HealthCriterionOutput(
        score=0.6,
        evidence=["", "  ", "real evidence", ""],
        concerns=["  ", "real concern"],
    )
    assert messy_lists.evidence == ["real evidence"]
    assert messy_lists.concerns == ["real concern"]
    j3 = messy_lists.model_dump_json()
    r3 = HealthCriterionOutput.model_validate_json(j3)
    assert r3.evidence == ["real evidence"]
    assert r3.concerns == ["real concern"]


# ---------------------------------------------------------------------------
# Schema stability: known-good JSON fixtures must still deserialize
# ---------------------------------------------------------------------------


_MINIMAL_EXPERIENCE_JSON = json.dumps(
    {
        "schema_version": "1.0",
        "experience": {
            "id": "11111111-1111-4111-8111-111111111111",
            "session_id": "22222222-2222-4222-8222-222222222222",
            "timestamp": "2025-01-01T12:00:00+00:00",
            "key_moments": [
                {
                    "id": "33333333-3333-4333-8333-333333333333",
                    "what_happened": "schema stability test",
                    "how_i_felt": {
                        "emotional_valence": 0.5,
                        "emotional_intensity": 0.5,
                        "depth": "surface",
                        "physical_sensation": None,
                        "cognitive_state": None,
                    },
                    "why_it_matters": "stability",
                    "values_touched": ["honesty"],
                    "reframing_notes": [],
                }
            ],
            "reframing_notes": [],
            "salience": 1.0,
            "access_count": 0,
        },
    }
)


def test_known_good_experience_json_still_deserializes() -> None:
    """If this fails, a model field was renamed or removed — check migration path."""
    record = ExperienceRecord.model_validate_json(_MINIMAL_EXPERIENCE_JSON)
    assert str(record.experience.id) == "11111111-1111-4111-8111-111111111111"
    assert record.experience.key_moments[0].what_happened == "schema stability test"
