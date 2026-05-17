"""In-memory MemoryGuardian — scans agent memory for quality issues."""

import threading
from collections import Counter
from datetime import UTC, datetime, timedelta
from uuid import UUID

from typing_extensions import override

from atman.core.models.entity import EntityType
from atman.core.models.validation import (
    FindingSeverity,
    FindingType,
    ResolutionStatus,
    ValidationFinding,
)
from atman.core.ports.divergence_events import DivergenceEventStore
from atman.core.ports.entity_registry import EntityRegistry
from atman.core.ports.entity_stance import EntityStanceStore
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
        divergence_event_store: DivergenceEventStore | None = None,
        entity_stance_store: EntityStanceStore | None = None,
    ) -> None:
        self._entities = entity_registry
        self._facts = factual_memory
        self._store = state_store
        self._embedding = embedding
        # HLE-31: optional sources for Level-C psychological quality metrics.
        # Missing inputs ⇒ the corresponding sub-scan silently emits zero
        # findings instead of crashing, so dev/in-memory deploys without the
        # full pipeline still work.
        self._divergence_events = divergence_event_store
        self._entity_stance = entity_stance_store
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
    def scan_quality_metrics(
        self,
        agent_id: UUID,
        *,
        window_days: int = 7,
        incomplete_coloring_threshold: float = 0.3,
        divergence_pattern_threshold: int = 5,
        stance_too_fast_hours: int = 24,
        stance_too_fast_min_count: int = 3,
    ) -> list[ValidationFinding]:
        """Level-C psychological quality-metric scans (HLE-31)."""
        now = datetime.now(UTC)
        window_start = now - timedelta(days=window_days)
        findings: list[ValidationFinding] = []
        findings.extend(
            self._scan_affect_detector_silent(agent_id, window_start, incomplete_coloring_threshold)
        )
        findings.extend(
            self._scan_divergence_pattern(agent_id, window_start, now, divergence_pattern_threshold)
        )
        findings.extend(
            self._scan_stance_formation_too_fast(
                agent_id,
                window_start,
                stance_too_fast_hours,
                stance_too_fast_min_count,
            )
        )
        return findings

    # ---- Level-C sub-scans (HLE-31) ------------------------------------------

    def _scan_affect_detector_silent(
        self, agent_id: UUID, window_start: datetime, threshold: float
    ) -> list[ValidationFinding]:
        """High incomplete_coloring rate over the window → pipeline silent."""
        if self._store is None:
            return []
        moments = [m for m in self._store.list_key_moments() if _aware(m.when) >= window_start]
        if not moments:
            return []
        incomplete = sum(1 for m in moments if _is_incomplete_coloring(m))
        rate = incomplete / len(moments)
        if rate <= threshold:
            return []
        return [
            ValidationFinding(
                agent_id=agent_id,
                finding_type=FindingType.affect_detector_silent,
                severity=FindingSeverity.warning,
                target_table="key_moments",
                target_id=moments[0].id,
                details={
                    "rate": round(rate, 3),
                    "incomplete": incomplete,
                    "total": len(moments),
                    "threshold": threshold,
                    "window_start": window_start.isoformat(),
                },
                detected_by="memory_guardian",
            )
        ]

    def _scan_divergence_pattern(
        self,
        agent_id: UUID,
        window_start: datetime,
        window_end: datetime,
        threshold: int,
    ) -> list[ValidationFinding]:
        """Same divergence_type ≥ threshold over the window → stable pattern."""
        if self._divergence_events is None:
            return []
        events = self._divergence_events.list_in_range(agent_id, window_start, window_end)
        counts: Counter[str] = Counter(str(e.divergence_type.value) for e in events)
        findings: list[ValidationFinding] = []
        # Deterministic order so repeated scans produce stable finding ids
        # downstream when callers persist via `write_finding`.
        for dtype, count in sorted(counts.items()):
            if count < threshold:
                continue
            sample = next(e for e in events if e.divergence_type.value == dtype)
            findings.append(
                ValidationFinding(
                    agent_id=agent_id,
                    finding_type=FindingType.divergence_pattern,
                    severity=FindingSeverity.warning,
                    target_table="divergence_events",
                    target_id=sample.id,
                    details={
                        "divergence_type": dtype,
                        "count": count,
                        "threshold": threshold,
                        "window_start": window_start.isoformat(),
                    },
                    detected_by="memory_guardian",
                )
            )
        return findings

    def _scan_stance_formation_too_fast(
        self,
        agent_id: UUID,
        window_start: datetime,
        too_fast_hours: int,
        min_count: int,
    ) -> list[ValidationFinding]:
        """Stances formed too close to their evidence moments → premature reflection."""
        if self._entity_stance is None or self._store is None:
            return []
        list_active = getattr(self._entity_stance, "list_active_stances", None)
        if list_active is None:
            return []
        try:
            stances = list_active(agent_id, formed_after=window_start)
        except Exception:
            return []
        too_fast: list[tuple[object, float]] = []
        for stance in stances:
            formed_at = getattr(stance, "formed_at", None)
            moment_ids = list(getattr(stance, "based_on_moment_ids", []) or [])
            if formed_at is None or not moment_ids:
                continue
            if _aware(formed_at) < window_start:
                continue
            moments_when: list[datetime] = []
            for mid in moment_ids:
                m = self._store.get_key_moment(mid)
                if m is not None:
                    moments_when.append(_aware(m.when))
            if not moments_when:
                continue
            earliest = min(moments_when)
            hours = (_aware(formed_at) - earliest).total_seconds() / 3600.0
            if hours < too_fast_hours:
                too_fast.append((stance, hours))
        if len(too_fast) < min_count:
            return []
        sample_stance, sample_hours = too_fast[0]
        return [
            ValidationFinding(
                agent_id=agent_id,
                finding_type=FindingType.stance_formation_too_fast,
                severity=FindingSeverity.warning,
                target_table="entity_stance",
                target_id=sample_stance.id,  # type: ignore[attr-defined]
                details={
                    "fast_stance_count": len(too_fast),
                    "threshold_hours": too_fast_hours,
                    "min_count": min_count,
                    "sample_hours_to_formation": round(sample_hours, 2),
                    "window_start": window_start.isoformat(),
                },
                detected_by="memory_guardian",
            )
        ]

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


def _aware(ts: datetime) -> datetime:
    """Normalise tz-naive timestamps to UTC for comparisons."""
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts


def _is_incomplete_coloring(moment: object) -> bool:
    """KeyMoment.incomplete_coloring flag access — falsey when the field
    is missing on a legacy record so we don't fabricate a signal."""
    return bool(getattr(moment, "incomplete_coloring", False))
