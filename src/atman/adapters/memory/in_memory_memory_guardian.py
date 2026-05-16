"""In-memory MemoryGuardian — scans agent memory for quality issues."""

import threading
from datetime import UTC, datetime
from uuid import UUID

from typing_extensions import override

from atman.core.models.entity import EntityType
from atman.core.models.validation import (
    FindingSeverity,
    FindingType,
    ResolutionStatus,
    ValidationFinding,
)
from atman.core.ports.entity_registry import EntityRegistry
from atman.core.ports.memory_backend import FactualMemory
from atman.core.ports.memory_guardian import MemoryGuardian
from atman.core.ports.state_store import StateStore


class InMemoryMemoryGuardian(MemoryGuardian):
    """Thread-safe in-memory MemoryGuardian for tests and local runs.

    Stores findings in a dict. Scan methods read live state from the
    injected EntityRegistry, FactualMemory, and StateStore — they detect
    quality issues but do not write findings themselves; the worker is
    expected to call `write_finding` for each returned candidate.
    """

    def __init__(
        self,
        entity_registry: EntityRegistry | None = None,
        factual_memory: FactualMemory | None = None,
        state_store: StateStore | None = None,
        *,
        embedding: object | None = None,
    ) -> None:
        self._entities = entity_registry
        self._facts = factual_memory
        self._store = state_store
        self._embedding = embedding
        self._findings: dict[UUID, ValidationFinding] = {}
        self._lock = threading.Lock()

    @override
    def scan_orphan_entities(self, agent_id: UUID) -> list[ValidationFinding]:
        """Find entities with no linked facts or key_moments.

        Without a fact-by-entity / moment-by-entity index, the in-memory
        adapter approximates this as "entities with mention_count == 1
        and no aliases" — entities that were resolved as L3_new and never
        seen again.
        """
        if self._entities is None:
            return []
        findings: list[ValidationFinding] = []
        for entity in self._entities.list_entities(agent_id, limit=10_000):
            if entity.mention_count > 1:
                continue
            findings.append(
                ValidationFinding(
                    agent_id=agent_id,
                    finding_type=FindingType.orphan_entity,
                    severity=FindingSeverity.warning,
                    target_table="entities",
                    target_id=entity.id,
                    details={
                        "canonical_name": entity.canonical_name,
                        "entity_type": entity.entity_type.value,
                        "mention_count": entity.mention_count,
                    },
                    detected_by="memory_guardian",
                )
            )
        return findings

    @override
    def scan_merge_candidates(
        self,
        agent_id: UUID,
        *,
        similarity_threshold: float = 0.92,
    ) -> list[ValidationFinding]:
        """Find entity pairs with high embedding similarity that may be duplicates."""
        if self._entities is None:
            return []
        entities = self._entities.list_entities(agent_id, limit=10_000)
        with_embedding = [e for e in entities if e.embedding is not None]
        findings: list[ValidationFinding] = []
        # O(n²) pair scan — acceptable for in-memory dev/test sizes
        for i, a in enumerate(with_embedding):
            for b in with_embedding[i + 1 :]:
                if a.entity_type != b.entity_type:
                    continue
                score = _cosine(a.embedding, b.embedding)  # type: ignore[arg-type]
                if score < similarity_threshold:
                    continue
                # Use the lower of the two ids as target so paired runs are stable.
                target_id = a.id if str(a.id) < str(b.id) else b.id
                other_id = b.id if target_id == a.id else a.id
                findings.append(
                    ValidationFinding(
                        agent_id=agent_id,
                        finding_type=FindingType.similar_entities,
                        severity=FindingSeverity.warning,
                        target_table="entities",
                        target_id=target_id,
                        details={
                            "candidate_pair": [str(target_id), str(other_id)],
                            "similarity": round(score, 4),
                            "threshold": similarity_threshold,
                        },
                        detected_by="memory_guardian",
                    )
                )
        return findings

    @override
    def scan_stale_moments(
        self,
        agent_id: UUID,
        *,
        days_threshold: int = 90,
    ) -> list[ValidationFinding]:
        """Find key_moments with very low salience that haven't been accessed."""
        if self._store is None:
            return []
        now = datetime.now(UTC)
        findings: list[ValidationFinding] = []
        for moment in self._store.list_key_moments():
            last_accessed = moment.last_accessed_at
            if last_accessed.tzinfo is None:
                last_accessed = last_accessed.replace(tzinfo=UTC)
            days = (now - last_accessed).total_seconds() / 86400.0
            if days < days_threshold:
                continue
            if moment.salience > 0.05:
                continue
            findings.append(
                ValidationFinding(
                    agent_id=agent_id,
                    finding_type=FindingType.stale_moment,
                    severity=FindingSeverity.info,
                    target_table="key_moments",
                    target_id=moment.id,
                    details={
                        "salience": moment.salience,
                        "days_since_accessed": round(days, 1),
                        "threshold_days": days_threshold,
                    },
                    detected_by="memory_guardian",
                )
            )
        return findings

    @override
    def scan_embedding_gaps(self, agent_id: UUID) -> list[ValidationFinding]:
        """Find entities and key_moments missing embeddings."""
        findings: list[ValidationFinding] = []
        if self._entities is not None:
            for entity in self._entities.list_entities(agent_id, limit=10_000):
                # Skip enumerations that don't need embeddings (values/principles
                # are short labels, not entities to vector-search against).
                if entity.entity_type in {EntityType.core_value, EntityType.principle}:
                    continue
                if entity.embedding is not None:
                    continue
                findings.append(
                    ValidationFinding(
                        agent_id=agent_id,
                        finding_type=FindingType.embedding_missing,
                        severity=FindingSeverity.info,
                        target_table="entities",
                        target_id=entity.id,
                        details={"canonical_name": entity.canonical_name},
                        detected_by="memory_guardian",
                    )
                )
        return findings

    @override
    def write_finding(self, finding: ValidationFinding) -> ValidationFinding:
        """Persist a finding."""
        with self._lock:
            self._findings[finding.id] = finding
        return finding

    @override
    def get_unresolved(
        self,
        agent_id: UUID,
        severity: str | None = None,
    ) -> list[ValidationFinding]:
        """Get unresolved findings, optionally filtered by severity."""
        with self._lock:
            results = [
                f
                for f in self._findings.values()
                if f.agent_id == agent_id
                and not f.is_resolved
                and (severity is None or f.severity.value == severity)
            ]
        results.sort(key=lambda f: f.detected_at, reverse=True)
        return results

    @override
    def resolve_finding(
        self,
        finding_id: UUID,
        *,
        resolution: str,
        resolved_by: str,
        note: str = "",
    ) -> ValidationFinding | None:
        """Mark a finding as resolved (creates a new frozen instance with resolution set)."""
        try:
            res = ResolutionStatus(resolution)
        except ValueError:
            res = ResolutionStatus.escalated
        with self._lock:
            existing = self._findings.get(finding_id)
            if existing is None:
                return None
            updated = existing.model_copy(
                update={
                    "resolution": res,
                    "resolved_at": datetime.now(UTC),
                    "resolved_by": resolved_by,
                    "resolution_note": note or None,
                }
            )
            self._findings[finding_id] = updated
        return updated


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity for embedding pairs (defensive against zero vectors)."""
    import math

    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0
