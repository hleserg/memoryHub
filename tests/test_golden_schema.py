"""
P2.7 — Golden schema / snapshot stability tests.

Embeds known-good JSON fixtures as inline strings. If any model field is
renamed, removed, or its type changes in a backwards-incompatible way, these
tests fail immediately — before any file-store migration can hide the breakage.

The fixtures represent the *minimum viable* structure: only required fields,
no optional ones. This makes the test maximally sensitive to breaking changes
while not requiring updates when optional fields are added.

SYSTEM_MAP §2.1 / §5.3 regression freeze.
"""

from __future__ import annotations

from atman.core.models import (
    Eigenstate,
    ExperienceRecord,
    NarrativeDocument,
)
from atman.core.models.fact import FactRecord

# ---------------------------------------------------------------------------
# ExperienceRecord
# ---------------------------------------------------------------------------

_GOLDEN_EXPERIENCE = """{
  "schema_version": "1.0",
  "experience": {
    "id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    "session_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    "timestamp": "2025-01-15T09:00:00+00:00",
    "key_moment_ids": ["cccccccc-cccc-4ccc-8ccc-cccccccccccc"],
    "avg_emotional_intensity": 0.7,
    "has_profound_moment": false,
    "reframing_notes": [],
    "salience": 1.0,
    "access_count": 0,
    "last_accessed_at": "2025-01-15T09:00:00+00:00",
    "fact_refs": ["33333333-3333-4333-8333-333333333333"]
  }
}"""


def test_golden_experience_record_deserializes() -> None:
    record = ExperienceRecord.model_validate_json(_GOLDEN_EXPERIENCE)
    assert str(record.experience.id) == "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    assert len(record.experience.key_moment_ids) == 1
    assert str(record.experience.key_moment_ids[0]) == "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    assert record.experience.salience == 1.0
    assert record.experience.access_count == 0
    assert record.experience.avg_emotional_intensity == 0.7
    assert record.experience.has_profound_moment is False
    # E24.2: fact_refs lift back-links from facts -> experiences.
    assert str(record.experience.fact_refs[0]) == "33333333-3333-4333-8333-333333333333"


# ---------------------------------------------------------------------------
# NarrativeDocument
# ---------------------------------------------------------------------------

_GOLDEN_NARRATIVE = """{
  "id": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
  "identity_id": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
  "created_at": "2025-01-15T09:00:00+00:00",
  "updated_at": "2025-01-15T09:00:00+00:00",
  "core_layer": {
    "layer_type": "core",
    "content": "I exist at the ground zero.",
    "updated_at": "2025-01-15T09:00:00+00:00"
  },
  "recent_layer": {
    "layer_type": "recent",
    "content": "No recent experiences yet.",
    "updated_at": "2025-01-15T09:00:00+00:00"
  },
  "threads": [],
  "schema_version": "1.0"
}"""


def test_golden_narrative_document_deserializes() -> None:
    narrative = NarrativeDocument.model_validate_json(_GOLDEN_NARRATIVE)
    assert str(narrative.id) == "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
    assert str(narrative.identity_id) == "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
    assert narrative.core_layer.content == "I exist at the ground zero."
    assert narrative.recent_layer.content == "No recent experiences yet."


# ---------------------------------------------------------------------------
# Eigenstate
# ---------------------------------------------------------------------------

_GOLDEN_EIGENSTATE = """{
  "id": "ffffffff-ffff-4fff-8fff-ffffffffffff",
  "session_id": "11111111-1111-4111-8111-111111111111",
  "timestamp": "2025-01-15T09:00:00+00:00",
  "emotional_tone": 0.2,
  "emotional_intensity": 0.4,
  "cognitive_load": 0.3,
  "open_threads": ["unresolved question A"],
  "dominant_themes": ["growth"],
  "unresolved_tensions": [],
  "session_summary": "A focused session.",
  "key_insight": "Progress is possible."
}"""


def test_golden_eigenstate_deserializes() -> None:
    e = Eigenstate.model_validate_json(_GOLDEN_EIGENSTATE)
    assert str(e.id) == "ffffffff-ffff-4fff-8fff-ffffffffffff"
    assert e.dominant_themes == ["growth"]
    assert e.key_insight == "Progress is possible."
    assert e.schema_version == "1.0.0"


# ---------------------------------------------------------------------------
# FactRecord (factual memory)
# ---------------------------------------------------------------------------

_GOLDEN_FACT = """{
  "id": "22222222-2222-4222-8222-222222222222",
  "content": "Golden fact content",
  "source": "test",
  "tags": ["knowledge", "test"],
  "created_at": "2025-01-15T09:00:00+00:00",
  "updated_at": "2025-01-15T09:00:00+00:00",
  "relations": [],
  "metadata": {},
  "status": "active",
  "invalidation_note": "",
  "invalidated_at": null,
  "disputed_at": null,
  "superseded_by": null,
  "confirmation_count": 0,
  "last_confirmed_at": null,
  "salience": 1.0
}"""

# E24.1: lifecycle states. The previous OUTDATED/RETRACTED/UNCERTAIN names
# were renamed to DISPUTED/SUPERSEDED/INVALIDATED — this fixture freezes the
# new wire values on disk so a future rename is caught immediately.
_GOLDEN_FACT_DISPUTED = """{
  "id": "44444444-4444-4444-8444-444444444444",
  "content": "Disputed fact body",
  "source": "test",
  "tags": [],
  "created_at": "2025-01-15T09:00:00+00:00",
  "updated_at": "2025-01-15T09:00:00+00:00",
  "relations": [],
  "metadata": {},
  "status": "disputed",
  "invalidation_note": "conflicts with newer evidence",
  "invalidated_at": null,
  "disputed_at": "2025-01-15T10:00:00+00:00",
  "superseded_by": null,
  "confirmation_count": 2,
  "last_confirmed_at": "2025-01-15T08:00:00+00:00",
  "salience": 0.7
}"""

_GOLDEN_FACT_SUPERSEDED = """{
  "id": "55555555-5555-4555-8555-555555555555",
  "content": "Superseded fact body",
  "source": "test",
  "tags": [],
  "created_at": "2025-01-14T09:00:00+00:00",
  "updated_at": "2025-01-15T09:00:00+00:00",
  "relations": [],
  "metadata": {},
  "status": "superseded",
  "invalidation_note": "replaced by newer fact",
  "invalidated_at": "2025-01-15T09:00:00+00:00",
  "disputed_at": null,
  "superseded_by": "66666666-6666-4666-8666-666666666666",
  "confirmation_count": 0,
  "last_confirmed_at": null,
  "salience": 0.0
}"""

_GOLDEN_FACT_INVALIDATED = """{
  "id": "77777777-7777-4777-8777-777777777777",
  "content": "Invalidated fact body",
  "source": "test",
  "tags": [],
  "created_at": "2025-01-14T09:00:00+00:00",
  "updated_at": "2025-01-15T09:00:00+00:00",
  "relations": [],
  "metadata": {},
  "status": "invalidated",
  "invalidation_note": "no longer true",
  "invalidated_at": "2025-01-15T09:00:00+00:00",
  "disputed_at": null,
  "superseded_by": null,
  "confirmation_count": 0,
  "last_confirmed_at": null,
  "salience": 0.0
}"""


def test_golden_fact_record_deserializes() -> None:
    fact = FactRecord.model_validate_json(_GOLDEN_FACT)
    assert str(fact.id) == "22222222-2222-4222-8222-222222222222"
    assert fact.content == "Golden fact content"
    assert "knowledge" in fact.tags
    # E24.1 / E24.3: lifecycle + confirmation/salience fields persist on disk.
    assert fact.status.value == "active"
    assert fact.confirmation_count == 0
    assert fact.last_confirmed_at is None
    assert fact.disputed_at is None
    assert fact.salience == 1.0


def test_golden_fact_record_disputed_deserializes() -> None:
    fact = FactRecord.model_validate_json(_GOLDEN_FACT_DISPUTED)
    assert fact.status.value == "disputed"
    assert fact.disputed_at is not None
    assert fact.invalidated_at is None
    assert fact.confirmation_count == 2
    # DISPUTED keeps salience non-zero (provisional, not terminal).
    assert fact.salience == 0.7
    # ``effective_lifecycle_timestamp`` returns ``disputed_at`` for DISPUTED.
    assert fact.effective_lifecycle_timestamp == fact.disputed_at


def test_golden_fact_record_superseded_deserializes() -> None:
    fact = FactRecord.model_validate_json(_GOLDEN_FACT_SUPERSEDED)
    assert fact.status.value == "superseded"
    assert fact.superseded_by is not None
    assert fact.salience == 0.0
    assert fact.effective_lifecycle_timestamp == fact.invalidated_at


def test_golden_fact_record_invalidated_deserializes() -> None:
    fact = FactRecord.model_validate_json(_GOLDEN_FACT_INVALIDATED)
    assert fact.status.value == "invalidated"
    assert fact.invalidated_at is not None
    assert fact.disputed_at is None
    assert fact.salience == 0.0


# ---------------------------------------------------------------------------
# Stability of re-serialization: deserialize → serialize → deserialize
# ---------------------------------------------------------------------------


def test_experience_double_roundtrip_is_stable() -> None:
    """Serialize → deserialize twice; the result must be identical."""
    r1 = ExperienceRecord.model_validate_json(_GOLDEN_EXPERIENCE)
    j = r1.model_dump_json()
    r2 = ExperienceRecord.model_validate_json(j)
    assert r2.experience.id == r1.experience.id
    assert r2.experience.key_moment_ids == r1.experience.key_moment_ids
    assert r2.experience.avg_emotional_intensity == r1.experience.avg_emotional_intensity


def test_narrative_double_roundtrip_is_stable() -> None:
    n1 = NarrativeDocument.model_validate_json(_GOLDEN_NARRATIVE)
    j = n1.model_dump_json()
    n2 = NarrativeDocument.model_validate_json(j)
    assert n2.id == n1.id
    assert n2.core_layer.content == n1.core_layer.content


def test_eigenstate_double_roundtrip_is_stable() -> None:
    e1 = Eigenstate.model_validate_json(_GOLDEN_EIGENSTATE)
    j = e1.model_dump_json()
    e2 = Eigenstate.model_validate_json(j)
    assert e2.id == e1.id
    assert e2.dominant_themes == e1.dominant_themes
