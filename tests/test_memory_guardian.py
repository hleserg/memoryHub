"""Tests for InMemoryMemoryGuardian scans + finding lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from atman.adapters.memory.in_memory_entity_registry import InMemoryEntityRegistry
from atman.adapters.memory.in_memory_memory_guardian import InMemoryMemoryGuardian
from atman.adapters.storage.in_memory_state_store import InMemoryStateStore
from atman.core.models.entity import EntityType
from atman.core.models.experience import EmotionalDepth, FeltSense, KeyMoment
from atman.core.models.validation import (
    FindingSeverity,
    FindingType,
    ResolutionStatus,
    ValidationFinding,
)


def _make_finding(agent_id) -> ValidationFinding:
    return ValidationFinding(
        agent_id=agent_id,
        finding_type=FindingType.orphan_entity,
        severity=FindingSeverity.warning,
        target_table="entities",
        target_id=uuid4(),
        details={},
        detected_by="memory_guardian",
    )


def test_scan_orphan_entities_flags_singletons() -> None:
    reg = InMemoryEntityRegistry()
    agent = uuid4()
    reg.resolve_or_create(agent, "Alice", EntityType.person)
    reg.resolve_or_create(agent, "Bob", EntityType.person)
    # Touch Alice so mention_count > 1 → not an orphan
    alices = reg.find_by_name(agent, "Alice")
    reg.update_last_seen(alices[0].id)
    guardian = InMemoryMemoryGuardian(entity_registry=reg)
    findings = guardian.scan_orphan_entities(agent)
    assert len(findings) == 1
    assert findings[0].finding_type is FindingType.orphan_entity
    assert findings[0].details["canonical_name"] == "Bob"


def test_scan_orphan_entities_returns_empty_without_registry() -> None:
    g = InMemoryMemoryGuardian()
    assert g.scan_orphan_entities(uuid4()) == []


def test_scan_merge_candidates_finds_high_similarity_pair() -> None:
    # Bypass L2 dedup by inserting entities directly into the registry's storage,
    # because resolve_or_create would merge near-duplicates at threshold 0.85.
    # In production, merge candidates arise from entities embedded post-hoc,
    # via independent code paths, or under different historical thresholds.
    from atman.core.models.entity import Entity

    reg = InMemoryEntityRegistry()
    agent = uuid4()
    a = Entity(
        agent_id=agent,
        canonical_name="ProjectX",
        entity_type=EntityType.topic,
        embedding=[1.0, 0.0, 0.0],
    )
    b = Entity(
        agent_id=agent,
        canonical_name="Project-X",
        entity_type=EntityType.topic,
        embedding=[0.99, 0.01, 0.0],
    )
    other = Entity(
        agent_id=agent,
        canonical_name="Other",
        entity_type=EntityType.topic,
        embedding=[0.0, 1.0, 0.0],
    )
    reg._entities[a.id] = a
    reg._entities[b.id] = b
    reg._entities[other.id] = other
    reg._aliases.setdefault(a.id, [])
    reg._aliases.setdefault(b.id, [])
    reg._aliases.setdefault(other.id, [])

    guardian = InMemoryMemoryGuardian(entity_registry=reg)
    findings = guardian.scan_merge_candidates(agent, similarity_threshold=0.92)
    assert len(findings) == 1
    assert findings[0].finding_type is FindingType.similar_entities
    assert findings[0].details["similarity"] >= 0.92


def test_scan_merge_candidates_skips_different_types() -> None:
    reg = InMemoryEntityRegistry()
    agent = uuid4()
    reg.resolve_or_create(agent, "Alice", EntityType.person, embedding=[1.0, 0.0])
    reg.resolve_or_create(agent, "Apple", EntityType.organization, embedding=[1.0, 0.0])
    guardian = InMemoryMemoryGuardian(entity_registry=reg)
    findings = guardian.scan_merge_candidates(agent)
    assert findings == []


def test_scan_stale_moments_flags_low_salience_old_moments() -> None:
    store = InMemoryStateStore()
    long_ago = datetime.now(UTC) - timedelta(days=120)
    m = KeyMoment(
        what_happened="x",
        how_i_felt=FeltSense(
            emotional_valence=0.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
        ),
        why_it_matters="why",
        salience=0.02,
        last_accessed_at=long_ago,
    )
    store.store_key_moment(m)
    guardian = InMemoryMemoryGuardian(state_store=store)
    findings = guardian.scan_stale_moments(uuid4(), days_threshold=90)
    assert len(findings) == 1
    assert findings[0].finding_type is FindingType.stale_moment


def test_scan_stale_moments_skips_recent_or_high_salience() -> None:
    store = InMemoryStateStore()
    # recent
    m1 = KeyMoment(
        what_happened="a",
        how_i_felt=FeltSense(
            emotional_valence=0.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
        ),
        why_it_matters="why",
        salience=0.02,
        last_accessed_at=datetime.now(UTC) - timedelta(days=1),
    )
    # old but high salience
    m2 = KeyMoment(
        what_happened="b",
        how_i_felt=FeltSense(
            emotional_valence=0.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
        ),
        why_it_matters="why",
        salience=0.9,
        last_accessed_at=datetime.now(UTC) - timedelta(days=200),
    )
    store.store_key_moment(m1)
    store.store_key_moment(m2)
    guardian = InMemoryMemoryGuardian(state_store=store)
    assert guardian.scan_stale_moments(uuid4()) == []


def test_scan_embedding_gaps_flags_missing_embeddings() -> None:
    reg = InMemoryEntityRegistry()
    agent = uuid4()
    reg.resolve_or_create(agent, "Bob", EntityType.person)
    reg.resolve_or_create(agent, "honesty", EntityType.core_value)  # values are exempt
    reg.resolve_or_create(agent, "AcmeCo", EntityType.organization, embedding=[0.1, 0.2])
    guardian = InMemoryMemoryGuardian(entity_registry=reg)
    findings = guardian.scan_embedding_gaps(agent)
    assert len(findings) == 1
    assert findings[0].details["canonical_name"] == "Bob"


def test_write_and_get_unresolved() -> None:
    agent = uuid4()
    guardian = InMemoryMemoryGuardian()
    f1 = _make_finding(agent)
    f2 = _make_finding(agent)
    guardian.write_finding(f1)
    guardian.write_finding(f2)
    unresolved = guardian.get_unresolved(agent)
    assert {f.id for f in unresolved} == {f1.id, f2.id}


def test_get_unresolved_filters_by_severity() -> None:
    agent = uuid4()
    guardian = InMemoryMemoryGuardian()
    f = _make_finding(agent)
    f_critical = f.model_copy(update={"id": uuid4(), "severity": FindingSeverity.critical})
    guardian.write_finding(f)
    guardian.write_finding(f_critical)
    crit = guardian.get_unresolved(agent, severity="critical")
    assert len(crit) == 1
    assert crit[0].id == f_critical.id


def test_resolve_finding_marks_resolved() -> None:
    agent = uuid4()
    guardian = InMemoryMemoryGuardian()
    f = _make_finding(agent)
    guardian.write_finding(f)
    updated = guardian.resolve_finding(
        f.id, resolution="fixed", resolved_by="reflection", note="merged"
    )
    assert updated is not None
    assert updated.is_resolved
    assert updated.resolution is ResolutionStatus.fixed
    assert updated.resolved_by == "reflection"
    # gone from unresolved
    assert guardian.get_unresolved(agent) == []


def test_resolve_finding_unknown_id_returns_none() -> None:
    guardian = InMemoryMemoryGuardian()
    assert guardian.resolve_finding(uuid4(), resolution="fixed", resolved_by="x") is None


def test_resolve_finding_unknown_resolution_falls_back_to_escalated() -> None:
    agent = uuid4()
    guardian = InMemoryMemoryGuardian()
    f = _make_finding(agent)
    guardian.write_finding(f)
    updated = guardian.resolve_finding(f.id, resolution="bogus", resolved_by="x")
    assert updated is not None
    assert updated.resolution is ResolutionStatus.escalated
