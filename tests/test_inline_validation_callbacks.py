"""Tests for HLE-32 — inline post-write validation callbacks."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from atman.adapters.memory.in_memory_memory_guardian import InMemoryMemoryGuardian
from atman.adapters.storage.in_memory_state_store import InMemoryStateStore
from atman.core.models.entity import Entity, EntityType
from atman.core.models.experience import EmotionalDepth, FeltSense, KeyMoment
from atman.core.models.fact import FactRecord
from atman.core.models.validation import FindingSeverity, FindingType, ValidationFinding
from atman.core.services.inline_validator import InlineValidator


def _moment(*, incomplete: bool, session_id: UUID | None = None) -> KeyMoment:
    return KeyMoment(
        what_happened="event",
        when=datetime.now(UTC),
        how_i_felt=FeltSense(
            emotional_valence=0.1, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
        ),
        why_it_matters="why",
        session_id=session_id,
        incomplete_coloring=incomplete,
    )


# ---- inline_check_fact -----------------------------------------------


def test_inline_fact_with_explicit_null_embedding_emits_finding() -> None:
    """Per Devin Review #599: only fire when the caller explicitly opted
    into the embedding signal by writing ``embedding=None`` into metadata
    (e.g. Postgres adapter or a future inline embedder). A fresh FactRecord
    without the key is silent — embeddings are not a first-class field on
    the in-memory model so flagging every row would be noise."""
    agent = uuid4()
    guardian = InMemoryMemoryGuardian()
    fact = FactRecord(content="example", source="test", metadata={"embedding": None})
    findings = guardian.inline_check_fact(fact, agent_id=agent)
    assert len(findings) == 1
    f = findings[0]
    assert f.finding_type == FindingType.embedding_missing
    assert f.target_table == "facts"
    assert f.target_id == fact.id
    assert f.severity == FindingSeverity.info


def test_inline_fact_without_embedding_signal_emits_nothing() -> None:
    """Default-constructed FactRecord has no 'embedding' key in metadata
    and must therefore be silent — fixes the Devin #599 every-row-flagged
    noise."""
    agent = uuid4()
    guardian = InMemoryMemoryGuardian()
    fact = FactRecord(content="ex", source="t")
    assert guardian.inline_check_fact(fact, agent_id=agent) == []


def test_inline_fact_with_embedding_in_metadata_emits_nothing() -> None:
    """A populated metadata['embedding'] is the success case."""
    agent = uuid4()
    guardian = InMemoryMemoryGuardian()
    fact = FactRecord(content="ex", source="t", metadata={"embedding": [0.1, 0.2]})
    assert guardian.inline_check_fact(fact, agent_id=agent) == []


# ---- inline_check_entity ---------------------------------------------


def test_inline_entity_missing_embedding_emits_finding() -> None:
    agent = uuid4()
    guardian = InMemoryMemoryGuardian()
    entity = Entity(
        agent_id=agent,
        canonical_name="Alice",
        entity_type=EntityType.person,
    )  # embedding=None
    findings = guardian.inline_check_entity(entity, agent_id=agent)
    assert len(findings) == 1
    assert findings[0].finding_type == FindingType.embedding_missing
    assert findings[0].target_table == "entities"


def test_inline_entity_value_label_is_skipped() -> None:
    """Values / principles are short labels — no embedding expected."""
    agent = uuid4()
    guardian = InMemoryMemoryGuardian()
    value = Entity(
        agent_id=agent,
        canonical_name="honesty",
        entity_type=EntityType.core_value,
    )
    assert guardian.inline_check_entity(value, agent_id=agent) == []


# ---- inline_check_key_moment -----------------------------------------


def test_inline_key_moment_incomplete_coloring_emits_finding() -> None:
    agent = uuid4()
    guardian = InMemoryMemoryGuardian()
    moment = _moment(incomplete=True)
    findings = guardian.inline_check_key_moment(moment, agent_id=agent)
    assert len(findings) == 1
    f = findings[0]
    assert f.finding_type == FindingType.affect_detector_silent
    assert f.severity == FindingSeverity.info
    assert f.target_table == "key_moments"
    assert f.details["phase"] == "inline"


def test_inline_key_moment_complete_coloring_emits_nothing() -> None:
    agent = uuid4()
    guardian = InMemoryMemoryGuardian()
    moment = _moment(incomplete=False)
    assert guardian.inline_check_key_moment(moment, agent_id=agent) == []


def test_inline_entity_with_embedding_emits_nothing() -> None:
    agent = uuid4()
    guardian = InMemoryMemoryGuardian()
    entity = Entity(
        agent_id=agent,
        canonical_name="Alice",
        entity_type=EntityType.person,
        embedding=[0.1, 0.2, 0.3],
    )
    assert guardian.inline_check_entity(entity, agent_id=agent) == []


def test_inline_fact_check_dedups() -> None:
    """Same fact rechecked after write_finding → empty list (de-dup branch).
    Requires the explicit embedding=None opt-in (see #599)."""
    agent = uuid4()
    guardian = InMemoryMemoryGuardian()
    fact = FactRecord(content="example", source="t", metadata={"embedding": None})
    out1 = guardian.inline_check_fact(fact, agent_id=agent)
    guardian.write_finding(out1[0])
    out2 = guardian.inline_check_fact(fact, agent_id=agent)
    assert out2 == []


def test_inline_key_moment_check_dedups() -> None:
    agent = uuid4()
    guardian = InMemoryMemoryGuardian()
    moment = _moment(incomplete=True)
    out1 = guardian.inline_check_key_moment(moment, agent_id=agent)
    guardian.write_finding(out1[0])
    assert guardian.inline_check_key_moment(moment, agent_id=agent) == []


def test_inline_entity_check_dedups() -> None:
    agent = uuid4()
    guardian = InMemoryMemoryGuardian()
    entity = Entity(agent_id=agent, canonical_name="x", entity_type=EntityType.person)
    out1 = guardian.inline_check_entity(entity, agent_id=agent)
    guardian.write_finding(out1[0])
    assert guardian.inline_check_entity(entity, agent_id=agent) == []


# ---- de-duplication --------------------------------------------------


def test_inline_check_dedups_against_existing_unresolved() -> None:
    """Re-checking the same row when an unresolved finding already exists
    must return [] — the de-dup check fires inside the guardian."""
    agent = uuid4()
    guardian = InMemoryMemoryGuardian()
    fact = FactRecord(content="example", source="t", metadata={"embedding": None})
    # First check writes; pretend the validator persisted it.
    findings = guardian.inline_check_fact(fact, agent_id=agent)
    assert len(findings) == 1
    guardian.write_finding(findings[0])
    # Second check on the same row should be a no-op.
    assert guardian.inline_check_fact(fact, agent_id=agent) == []


# ---- InlineValidator wrapper -----------------------------------------


def test_validator_persists_findings_via_write_finding() -> None:
    agent = uuid4()
    guardian = InMemoryMemoryGuardian()
    validator = InlineValidator(guardian)
    moment = _moment(incomplete=True)
    validator.check_key_moment(moment, agent_id=agent)
    unresolved = guardian.get_unresolved(agent)
    assert len(unresolved) == 1
    assert unresolved[0].finding_type == FindingType.affect_detector_silent


def test_validator_check_fact_persists_finding() -> None:
    """InlineValidator.check_fact also writes to the guardian. Uses the
    explicit metadata['embedding'] = None opt-in (see #599)."""
    agent = uuid4()
    guardian = InMemoryMemoryGuardian()
    validator = InlineValidator(guardian)
    validator.check_fact(
        FactRecord(content="ex", source="t", metadata={"embedding": None}),
        agent_id=agent,
    )
    unresolved = guardian.get_unresolved(agent)
    assert len(unresolved) == 1
    assert unresolved[0].finding_type == FindingType.embedding_missing


def test_validator_check_entity_persists_finding() -> None:
    agent = uuid4()
    guardian = InMemoryMemoryGuardian()
    validator = InlineValidator(guardian)
    validator.check_entity(
        Entity(agent_id=agent, canonical_name="x", entity_type=EntityType.person),
        agent_id=agent,
    )
    unresolved = guardian.get_unresolved(agent)
    assert len(unresolved) == 1
    assert unresolved[0].target_table == "entities"


def test_validator_swallows_check_exceptions() -> None:
    """A broken check method must not propagate — the hot path must not
    block on validation per plan §17 principle 12."""

    class _Boom(InMemoryMemoryGuardian):
        def inline_check_key_moment(self, moment, *, agent_id):  # type: ignore[override]
            raise RuntimeError("validator offline")

    agent = uuid4()
    validator = InlineValidator(_Boom())
    # Must not raise:
    validator.check_key_moment(_moment(incomplete=True), agent_id=agent)


def test_validator_swallows_write_finding_exceptions() -> None:
    """write_finding errors must also be swallowed — even when the check
    produced a finding, a queue/db outage cannot bring down the writer."""

    class _Half(InMemoryMemoryGuardian):
        def write_finding(self, finding: ValidationFinding) -> ValidationFinding:  # type: ignore[override]
            raise RuntimeError("store offline")

    agent = uuid4()
    validator = InlineValidator(_Half())
    validator.check_key_moment(_moment(incomplete=True), agent_id=agent)


# ---- end-to-end via SessionManager.finish_session --------------------


def test_session_manager_runs_inline_validator_on_finish(tmp_path) -> None:
    from atman.core.models.identity import Identity
    from atman.core.models.narrative import LayerType, NarrativeDocument, NarrativeLayer
    from atman.core.services.session_manager import SessionManager

    store = InMemoryStateStore()
    identity = Identity(self_description="t")
    store.save_identity(identity)
    store.save_narrative(
        NarrativeDocument(
            identity_id=identity.id,
            core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="c"),
            recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="r"),
        )
    )
    guardian = InMemoryMemoryGuardian(state_store=store)
    validator = InlineValidator(guardian)
    mgr = SessionManager(store, workspace=tmp_path, inline_validator=validator)

    ctx = mgr.start_session(identity.id)
    mgr.append_key_moment(ctx.session_id, _moment(incomplete=True, session_id=ctx.session_id))
    mgr.finish_session(
        ctx.session_id,
        overall_emotional_tone=0.0,
        key_insight="t",
        alignment_check=True,
        alignment_notes="",
    )

    unresolved = guardian.get_unresolved(identity.id)
    assert any(
        f.finding_type == FindingType.affect_detector_silent and f.details.get("phase") == "inline"
        for f in unresolved
    )


def test_factory_exposes_memory_guardian_on_deps(tmp_path) -> None:
    from atman.adapters.agent.factory import build_deps

    deps, _sm, _store = build_deps(tmp_path, uuid4())
    assert deps.memory_guardian is not None
    # Same instance used inline + exposed for downstream consumers.
    assert isinstance(deps.memory_guardian, InMemoryMemoryGuardian)
