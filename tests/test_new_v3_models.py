"""Unit tests for v3 domain models: entity, validation, maintenance."""

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from atman.core.models.entity import (
    Entity,
    EntityAlias,
    EntityRelation,
    EntityStance,
    EntityType,
    FactEntityLink,
    KeyMomentEntityLink,
    ResolutionMethod,
)
from atman.core.models.maintenance import (
    JobName,
    JobStatus,
    MaintenanceJob,
)
from atman.core.models.validation import (
    DivergenceEvent,
    DivergenceSeverity,
    DivergenceType,
    FindingSeverity,
    FindingType,
    ResolutionStatus,
    ValidationFinding,
)

# ----------------------------- EntityType -----------------------------


def test_entity_type_values_complete():
    assert EntityType.person == "person"
    assert EntityType.place == "place"
    assert EntityType.organization == "organization"
    assert EntityType.object == "object"
    assert EntityType.topic == "topic"
    assert EntityType.event == "event"
    assert EntityType.tool == "tool"
    assert EntityType.health_condition == "health_condition"
    assert EntityType.skill == "skill"
    assert EntityType.principle == "principle"


def test_entity_type_core_value_is_value_string():
    assert EntityType.core_value.value == "value"
    assert EntityType.core_value == "value"
    assert EntityType("value") is EntityType.core_value


def test_entity_type_member_count():
    assert len(list(EntityType)) == 11


# ----------------------------- ResolutionMethod -----------------------------


def test_resolution_method_values():
    assert ResolutionMethod.L1_exact == "exact match"
    assert ResolutionMethod.L2_embedding == "cosine similarity ≥ threshold"
    assert ResolutionMethod.L3_new == "created new entity"


# ----------------------------- Entity -----------------------------


def test_entity_minimal_creation():
    agent_id = uuid4()
    entity = Entity(
        agent_id=agent_id,
        canonical_name="Alice",
        entity_type=EntityType.person,
    )
    assert isinstance(entity.id, UUID)
    assert entity.agent_id == agent_id
    assert entity.canonical_name == "Alice"
    assert entity.entity_type is EntityType.person
    assert entity.description is None
    assert entity.mention_count == 1
    assert entity.needs_disambiguation is False
    assert entity.embedding is None
    assert entity.schema_version == "atman-1.0"
    assert entity.metadata == {}
    assert isinstance(entity.first_seen_at, datetime)
    assert isinstance(entity.last_seen_at, datetime)


def test_entity_full_creation():
    agent_id = uuid4()
    eid = uuid4()
    now = datetime.now(UTC)
    entity = Entity(
        id=eid,
        agent_id=agent_id,
        canonical_name="Vermont",
        entity_type=EntityType.place,
        description="A US state",
        first_seen_at=now,
        last_seen_at=now,
        mention_count=5,
        needs_disambiguation=True,
        embedding=[0.1, 0.2, 0.3],
        schema_version="atman-2.0",
        metadata={"source": "manual"},
    )
    assert entity.id == eid
    assert entity.description == "A US state"
    assert entity.mention_count == 5
    assert entity.needs_disambiguation is True
    assert entity.embedding == [0.1, 0.2, 0.3]
    assert entity.schema_version == "atman-2.0"
    assert entity.metadata == {"source": "manual"}


def test_entity_canonical_name_stripped():
    entity = Entity(
        agent_id=uuid4(),
        canonical_name="  Bob  ",
        entity_type=EntityType.person,
    )
    assert entity.canonical_name == "Bob"


def test_entity_canonical_name_empty_rejected():
    with pytest.raises(ValidationError, match="must not be empty"):
        Entity(agent_id=uuid4(), canonical_name="", entity_type=EntityType.person)


def test_entity_canonical_name_whitespace_rejected():
    with pytest.raises(ValidationError, match="must not be empty"):
        Entity(agent_id=uuid4(), canonical_name="    ", entity_type=EntityType.person)


def test_entity_mention_count_lower_bound():
    with pytest.raises(ValidationError):
        Entity(
            agent_id=uuid4(),
            canonical_name="x",
            entity_type=EntityType.person,
            mention_count=0,
        )


def test_entity_is_mutable_validate_on_assignment():
    entity = Entity(
        agent_id=uuid4(),
        canonical_name="Carol",
        entity_type=EntityType.person,
    )
    entity.mention_count = 10
    assert entity.mention_count == 10
    with pytest.raises(ValidationError):
        entity.mention_count = 0


def test_entity_assignment_strips_canonical_name():
    entity = Entity(
        agent_id=uuid4(),
        canonical_name="Dan",
        entity_type=EntityType.person,
    )
    entity.canonical_name = "  Daniel  "
    assert entity.canonical_name == "Daniel"


# ----------------------------- EntityAlias -----------------------------


def test_entity_alias_creation_lowercases_and_strips():
    alias = EntityAlias(
        entity_id=uuid4(),
        agent_id=uuid4(),
        alias_text="  HELLO  ",
    )
    assert alias.alias_text == "hello"
    assert isinstance(alias.id, UUID)
    assert alias.learned_from_fact_id is None
    assert isinstance(alias.learned_at, datetime)


def test_entity_alias_empty_rejected():
    with pytest.raises(ValidationError, match="must not be empty"):
        EntityAlias(entity_id=uuid4(), agent_id=uuid4(), alias_text="   ")


def test_entity_alias_frozen():
    alias = EntityAlias(entity_id=uuid4(), agent_id=uuid4(), alias_text="x")
    with pytest.raises(ValidationError):
        alias.alias_text = "y"


def test_entity_alias_with_learned_from_fact():
    fid = uuid4()
    alias = EntityAlias(
        entity_id=uuid4(),
        agent_id=uuid4(),
        alias_text="Bob",
        learned_from_fact_id=fid,
    )
    assert alias.learned_from_fact_id == fid


# ----------------------------- EntityRelation -----------------------------


def test_entity_relation_creation():
    a = uuid4()
    b = uuid4()
    rel = EntityRelation(
        agent_id=uuid4(),
        from_entity_id=a,
        to_entity_id=b,
        relation_type="friend_of",
        learned_by="manual",
    )
    assert rel.from_entity_id == a
    assert rel.to_entity_id == b
    assert rel.relation_type == "friend_of"
    assert rel.confidence == 1.0
    assert rel.since is None
    assert rel.until is None


def test_entity_relation_with_dates():
    rel = EntityRelation(
        agent_id=uuid4(),
        from_entity_id=uuid4(),
        to_entity_id=uuid4(),
        relation_type="works_at",
        since=date(2020, 1, 1),
        until=date(2024, 12, 31),
        confidence=0.85,
        learned_from_fact_id=uuid4(),
        learned_by="mrebel",
    )
    assert rel.since == date(2020, 1, 1)
    assert rel.until == date(2024, 12, 31)
    assert rel.confidence == 0.85


def test_entity_relation_self_reference_rejected():
    same = uuid4()
    with pytest.raises(ValidationError, match="must differ"):
        EntityRelation(
            agent_id=uuid4(),
            from_entity_id=same,
            to_entity_id=same,
            relation_type="x",
            learned_by="manual",
        )


def test_entity_relation_learned_by_invalid():
    with pytest.raises(ValidationError, match="learned_by"):
        EntityRelation(
            agent_id=uuid4(),
            from_entity_id=uuid4(),
            to_entity_id=uuid4(),
            relation_type="x",
            learned_by="nope",
        )


@pytest.mark.parametrize("source", ["mrebel", "rules", "reflection", "manual"])
def test_entity_relation_learned_by_allowed(source):
    rel = EntityRelation(
        agent_id=uuid4(),
        from_entity_id=uuid4(),
        to_entity_id=uuid4(),
        relation_type="x",
        learned_by=source,
    )
    assert rel.learned_by == source


def test_entity_relation_confidence_bounds():
    with pytest.raises(ValidationError):
        EntityRelation(
            agent_id=uuid4(),
            from_entity_id=uuid4(),
            to_entity_id=uuid4(),
            relation_type="x",
            confidence=1.5,
            learned_by="manual",
        )
    with pytest.raises(ValidationError):
        EntityRelation(
            agent_id=uuid4(),
            from_entity_id=uuid4(),
            to_entity_id=uuid4(),
            relation_type="x",
            confidence=-0.1,
            learned_by="manual",
        )


def test_entity_relation_empty_relation_type_rejected():
    with pytest.raises(ValidationError):
        EntityRelation(
            agent_id=uuid4(),
            from_entity_id=uuid4(),
            to_entity_id=uuid4(),
            relation_type="",
            learned_by="manual",
        )


def test_entity_relation_frozen():
    rel = EntityRelation(
        agent_id=uuid4(),
        from_entity_id=uuid4(),
        to_entity_id=uuid4(),
        relation_type="x",
        learned_by="manual",
    )
    with pytest.raises(ValidationError):
        rel.relation_type = "y"


# ----------------------------- EntityStance -----------------------------


def test_entity_stance_creation_default_active():
    stance = EntityStance(
        agent_id=uuid4(),
        entity_id=uuid4(),
        stance_text="I trust Alice",
    )
    assert stance.is_active is True
    assert stance.superseded_at is None
    assert stance.superseded_by is None
    assert stance.is_provisional is True
    assert stance.valence is None
    assert stance.intensity is None
    assert stance.confidence is None
    assert stance.based_on_moment_ids == []


def test_entity_stance_inactive_when_superseded():
    stance = EntityStance(
        agent_id=uuid4(),
        entity_id=uuid4(),
        stance_text="I trust Alice",
        superseded_at=datetime.now(UTC),
        superseded_by=uuid4(),
    )
    assert stance.is_active is False


def test_entity_stance_assignment_toggles_is_active():
    stance = EntityStance(
        agent_id=uuid4(),
        entity_id=uuid4(),
        stance_text="x",
    )
    assert stance.is_active is True
    stance.superseded_at = datetime.now(UTC)
    assert stance.is_active is False


def test_entity_stance_valence_intensity_bounds():
    with pytest.raises(ValidationError):
        EntityStance(
            agent_id=uuid4(),
            entity_id=uuid4(),
            stance_text="x",
            valence=2.0,
        )
    with pytest.raises(ValidationError):
        EntityStance(
            agent_id=uuid4(),
            entity_id=uuid4(),
            stance_text="x",
            intensity=-0.1,
        )
    with pytest.raises(ValidationError):
        EntityStance(
            agent_id=uuid4(),
            entity_id=uuid4(),
            stance_text="x",
            confidence=2.0,
        )


def test_entity_stance_full_fields():
    rid = uuid4()
    mids = [uuid4(), uuid4()]
    stance = EntityStance(
        agent_id=uuid4(),
        entity_id=uuid4(),
        stance_text="strong stance",
        valence=0.5,
        intensity=0.8,
        formed_in_reflection_id=rid,
        based_on_moment_ids=mids,
        confidence=0.9,
        is_provisional=False,
    )
    assert stance.valence == 0.5
    assert stance.intensity == 0.8
    assert stance.formed_in_reflection_id == rid
    assert stance.based_on_moment_ids == mids
    assert stance.confidence == 0.9
    assert stance.is_provisional is False


def test_entity_stance_stance_text_min_length():
    with pytest.raises(ValidationError):
        EntityStance(agent_id=uuid4(), entity_id=uuid4(), stance_text="")


# ----------------------------- FactEntityLink -----------------------------


@pytest.mark.parametrize("role", ["subject", "object", "context", "mentioned"])
def test_fact_entity_link_allowed_roles(role):
    link = FactEntityLink(
        fact_id=uuid4(),
        entity_id=uuid4(),
        agent_id=uuid4(),
        role=role,
    )
    assert link.role == role
    assert link.confidence == 1.0


def test_fact_entity_link_invalid_role():
    with pytest.raises(ValidationError, match="role"):
        FactEntityLink(
            fact_id=uuid4(),
            entity_id=uuid4(),
            agent_id=uuid4(),
            role="bogus",
        )


def test_fact_entity_link_confidence_bounds():
    with pytest.raises(ValidationError):
        FactEntityLink(
            fact_id=uuid4(),
            entity_id=uuid4(),
            agent_id=uuid4(),
            role="subject",
            confidence=1.1,
        )


def test_fact_entity_link_frozen():
    link = FactEntityLink(
        fact_id=uuid4(),
        entity_id=uuid4(),
        agent_id=uuid4(),
        role="subject",
    )
    with pytest.raises(ValidationError):
        link.role = "object"


# ----------------------------- KeyMomentEntityLink -----------------------------


@pytest.mark.parametrize("inv", ["primary_subject", "present", "mentioned", "evoked"])
def test_key_moment_entity_link_allowed_involvement(inv):
    link = KeyMomentEntityLink(
        key_moment_id=uuid4(),
        entity_id=uuid4(),
        agent_id=uuid4(),
        involvement=inv,
    )
    assert link.involvement == inv
    assert link.valence_toward_entity is None
    assert link.intensity_toward_entity is None


def test_key_moment_entity_link_invalid_involvement():
    with pytest.raises(ValidationError, match="involvement"):
        KeyMomentEntityLink(
            key_moment_id=uuid4(),
            entity_id=uuid4(),
            agent_id=uuid4(),
            involvement="bogus",
        )


def test_key_moment_entity_link_valence_intensity_bounds():
    with pytest.raises(ValidationError):
        KeyMomentEntityLink(
            key_moment_id=uuid4(),
            entity_id=uuid4(),
            agent_id=uuid4(),
            involvement="present",
            valence_toward_entity=-2.0,
        )
    with pytest.raises(ValidationError):
        KeyMomentEntityLink(
            key_moment_id=uuid4(),
            entity_id=uuid4(),
            agent_id=uuid4(),
            involvement="present",
            intensity_toward_entity=1.5,
        )


def test_key_moment_entity_link_full():
    link = KeyMomentEntityLink(
        key_moment_id=uuid4(),
        entity_id=uuid4(),
        agent_id=uuid4(),
        involvement="primary_subject",
        valence_toward_entity=0.3,
        intensity_toward_entity=0.7,
    )
    assert link.valence_toward_entity == 0.3
    assert link.intensity_toward_entity == 0.7


def test_key_moment_entity_link_frozen():
    link = KeyMomentEntityLink(
        key_moment_id=uuid4(),
        entity_id=uuid4(),
        agent_id=uuid4(),
        involvement="present",
    )
    with pytest.raises(ValidationError):
        link.involvement = "evoked"


# ============================ validation.py ============================


def test_finding_severity_values():
    assert FindingSeverity.info == "info"
    assert FindingSeverity.warning == "warning"
    assert FindingSeverity.critical == "critical"
    assert len(list(FindingSeverity)) == 3


def test_finding_type_values():
    assert FindingType.orphan_entity == "orphan_entity"
    assert FindingType.similar_entities == "similar_entities"
    assert FindingType.stale_moment == "stale_moment"
    assert FindingType.quality_metric == "quality_metric"
    assert FindingType.embedding_missing == "embedding_missing"
    assert FindingType.other == "other"
    assert len(list(FindingType)) == 6


def test_resolution_status_values():
    assert ResolutionStatus.fixed == "fixed"
    assert ResolutionStatus.ignored == "ignored"
    assert ResolutionStatus.escalated == "escalated"
    assert len(list(ResolutionStatus)) == 3


def test_divergence_type_values():
    assert DivergenceType.thinking_suppression == "thinking_suppression"
    assert DivergenceType.principle_invocation_in_thinking == "principle_invocation_in_thinking"
    assert DivergenceType.message_entity_gap == "message_entity_gap"
    assert DivergenceType.cognitive_load_spike == "cognitive_load_spike"
    assert DivergenceType.other == "other"
    assert len(list(DivergenceType)) == 5


def test_divergence_severity_values():
    assert DivergenceSeverity.trace == "trace"
    assert DivergenceSeverity.notable == "notable"
    assert DivergenceSeverity.significant == "significant"
    assert DivergenceSeverity.rupture == "rupture"
    assert len(list(DivergenceSeverity)) == 4


def test_validation_finding_minimal_unresolved():
    finding = ValidationFinding(
        agent_id=uuid4(),
        finding_type=FindingType.orphan_entity,
        severity=FindingSeverity.warning,
        target_table="entities",
        target_id=uuid4(),
        detected_by="memory_guardian",
    )
    assert finding.is_resolved is False
    assert finding.resolution is None
    assert finding.resolved_at is None
    assert finding.resolved_by is None
    assert finding.resolution_note is None
    assert finding.details == {}
    assert isinstance(finding.id, UUID)
    assert isinstance(finding.detected_at, datetime)


def test_validation_finding_resolved_when_resolution_set():
    finding = ValidationFinding(
        agent_id=uuid4(),
        finding_type=FindingType.similar_entities,
        severity=FindingSeverity.critical,
        target_table="entities",
        target_id=uuid4(),
        detected_by="memory_guardian",
        resolution=ResolutionStatus.fixed,
        resolved_at=datetime.now(UTC),
        resolved_by="ops",
        resolution_note="merged duplicates",
    )
    assert finding.is_resolved is True
    assert finding.resolution is ResolutionStatus.fixed


def test_validation_finding_with_details():
    details = {"similar_count": 3, "candidates": ["x", "y"]}
    finding = ValidationFinding(
        agent_id=uuid4(),
        finding_type=FindingType.quality_metric,
        severity=FindingSeverity.info,
        target_table="quality_metrics",
        target_id=uuid4(),
        details=details,
        detected_by="auto",
    )
    assert finding.details == details


def test_validation_finding_frozen():
    finding = ValidationFinding(
        agent_id=uuid4(),
        finding_type=FindingType.other,
        severity=FindingSeverity.info,
        target_table="t",
        target_id=uuid4(),
        detected_by="x",
    )
    with pytest.raises(ValidationError):
        finding.severity = FindingSeverity.warning


def test_divergence_event_minimal():
    ev = DivergenceEvent(
        agent_id=uuid4(),
        divergence_type=DivergenceType.message_entity_gap,
        severity=DivergenceSeverity.notable,
    )
    assert ev.session_id is None
    assert ev.key_moment_id is None
    assert ev.thinking_layer is None
    assert ev.message_layer is None
    assert ev.action_layer is None
    assert ev.gliner_signals is None
    assert isinstance(ev.id, UUID)
    assert isinstance(ev.created_at, datetime)


def test_divergence_event_full():
    sid = uuid4()
    kmid = uuid4()
    ev = DivergenceEvent(
        agent_id=uuid4(),
        session_id=sid,
        key_moment_id=kmid,
        divergence_type=DivergenceType.thinking_suppression,
        severity=DivergenceSeverity.rupture,
        thinking_layer={"k": 1},
        message_layer={"m": 2},
        action_layer={"a": 3},
        gliner_signals={"g": 4},
    )
    assert ev.session_id == sid
    assert ev.key_moment_id == kmid
    assert ev.thinking_layer == {"k": 1}
    assert ev.message_layer == {"m": 2}
    assert ev.action_layer == {"a": 3}
    assert ev.gliner_signals == {"g": 4}


def test_divergence_event_frozen():
    ev = DivergenceEvent(
        agent_id=uuid4(),
        divergence_type=DivergenceType.other,
        severity=DivergenceSeverity.trace,
    )
    with pytest.raises(ValidationError):
        ev.severity = DivergenceSeverity.rupture


# ============================ maintenance.py ============================


def test_job_status_values():
    assert JobStatus.pending == "pending"
    assert JobStatus.running == "running"
    assert JobStatus.succeeded == "succeeded"
    assert JobStatus.failed == "failed"
    assert JobStatus.skipped == "skipped"
    assert len(list(JobStatus)) == 5


def test_job_name_values():
    assert JobName.salience_decay == "salience_decay"
    assert JobName.memory_guardian_scan == "memory_guardian_scan"
    assert JobName.mrebel_extract == "mrebel_extract"
    assert JobName.lingvo_enrich == "lingvo_enrich"
    assert JobName.entity_merge == "entity_merge"
    assert JobName.other == "other"
    assert len(list(JobName)) == 6


def test_maintenance_job_default_creation():
    job = MaintenanceJob(job_name=JobName.salience_decay)
    assert job.status is JobStatus.pending
    assert job.is_terminal is False
    assert job.duration_seconds is None
    assert job.agent_id is None
    assert job.payload == {}
    assert job.run_key is None
    assert job.started_at is None
    assert job.finished_at is None
    assert job.error is None
    assert job.result is None
    assert isinstance(job.id, UUID)
    assert isinstance(job.scheduled_at, datetime)


@pytest.mark.parametrize("status", [JobStatus.succeeded, JobStatus.failed, JobStatus.skipped])
def test_maintenance_job_is_terminal_true(status):
    job = MaintenanceJob(job_name=JobName.other, status=status)
    assert job.is_terminal is True


@pytest.mark.parametrize("status", [JobStatus.pending, JobStatus.running])
def test_maintenance_job_is_terminal_false(status):
    job = MaintenanceJob(job_name=JobName.other, status=status)
    assert job.is_terminal is False


def test_maintenance_job_duration_seconds_none_when_unset():
    job = MaintenanceJob(job_name=JobName.other)
    assert job.duration_seconds is None
    job.started_at = datetime.now(UTC)
    assert job.duration_seconds is None
    job.started_at = None
    job.finished_at = datetime.now(UTC)
    assert job.duration_seconds is None


def test_maintenance_job_duration_seconds_computed():
    start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    end = start + timedelta(seconds=5.5)
    job = MaintenanceJob(
        job_name=JobName.mrebel_extract,
        status=JobStatus.succeeded,
        started_at=start,
        finished_at=end,
    )
    assert job.duration_seconds == pytest.approx(5.5)
    assert job.is_terminal is True


def test_maintenance_job_validate_assignment():
    job = MaintenanceJob(job_name=JobName.other)
    job.status = JobStatus.running
    assert job.status is JobStatus.running
    with pytest.raises(ValidationError):
        job.status = "bogus_status"  # type: ignore[assignment]


def test_maintenance_job_full_construction():
    aid = uuid4()
    jid = uuid4()
    job = MaintenanceJob(
        id=jid,
        job_name=JobName.entity_merge,
        agent_id=aid,
        payload={"src": "a", "dst": "b"},
        run_key="run-1",
        status=JobStatus.failed,
        error="boom",
        result={"ok": False},
    )
    assert job.id == jid
    assert job.agent_id == aid
    assert job.payload == {"src": "a", "dst": "b"}
    assert job.run_key == "run-1"
    assert job.error == "boom"
    assert job.result == {"ok": False}
    assert job.is_terminal is True


# ---------------------------------------------------------------------------
# Regression: Session.status and Session.close_reason validate against the
# DB CHECK constraints at construction time via Literal types.
# ---------------------------------------------------------------------------


def test_session_rejects_invalid_status():
    from pydantic import ValidationError as _VE

    from atman.core.models.session import Session

    with pytest.raises(_VE):
        Session(agent_id=uuid4(), status="bogus")  # type: ignore[arg-type]


def test_session_rejects_invalid_close_reason():
    from pydantic import ValidationError as _VE

    from atman.core.models.session import Session

    with pytest.raises(_VE):
        Session(agent_id=uuid4(), close_reason="bogus")  # type: ignore[arg-type]


def test_session_accepts_valid_status_and_close_reason():
    from atman.core.models.session import Session

    s = Session(agent_id=uuid4(), status="completed", close_reason="forced")
    assert s.status == "completed"
    assert s.close_reason == "forced"
