"""
DivergenceAggregator — Daily reflection on ``divergence_events``.

Reads divergence events (thinking ↔ message ↔ action splits) for the UTC
day and:

* groups by ``divergence_type``; emits a daily ``PatternCandidate``
  (``pattern_type=BEHAVIOR``) when a type recurs ≥ ``min_count`` times;
* surfaces any ``severity='rupture'`` event in a free-text observation
  the caller can append to ``ReflectionEvent.key_insight``, regardless
  of the per-type aggregation threshold (ruptures are always notable).

This is pure aggregation — no LLM call. Idempotent persistence via
:func:`~atman.core.reflection_run_keys.daily_divergence_pattern_detection_key`.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from uuid import UUID

from atman.core.models.reflection import (
    PatternCandidate,
    PatternStatus,
    PatternType,
    ReflectionLevel,
)
from atman.core.models.validation import DivergenceEvent, DivergenceSeverity
from atman.core.ports.divergence_events import DivergenceEventStore
from atman.core.ports.reflection import PatternStore
from atman.core.reflection_run_keys import daily_divergence_pattern_detection_key

DEFAULT_MIN_COUNT: int = 3


def aggregate_divergence_events(
    events: list[DivergenceEvent],
    *,
    min_count: int = DEFAULT_MIN_COUNT,
) -> list[tuple[str, list[DivergenceEvent]]]:
    """Group events by ``divergence_type``; keep groups with ≥ ``min_count``."""
    if min_count <= 0:
        raise ValueError("min_count must be >= 1")
    buckets: dict[str, list[DivergenceEvent]] = defaultdict(list)
    for ev in events:
        buckets[ev.divergence_type.value].append(ev)
    out: list[tuple[str, list[DivergenceEvent]]] = []
    for div_type in sorted(buckets.keys()):
        bucket = buckets[div_type]
        if len(bucket) >= min_count:
            bucket.sort(key=lambda e: (e.created_at, str(e.id)))
            out.append((div_type, bucket))
    return out


def collect_rupture_observations(events: list[DivergenceEvent]) -> list[str]:
    """One short text line per ``severity='rupture'`` event, time-ordered."""
    ruptures = [e for e in events if e.severity == DivergenceSeverity.rupture]
    ruptures.sort(key=lambda e: (e.created_at, str(e.id)))
    return [
        f"divergence rupture '{e.divergence_type.value}' at {e.created_at.isoformat()}"
        for e in ruptures
    ]


class DivergenceAggregator:
    """
    Daily aggregation of :class:`DivergenceEvent` into ``PatternCandidate`` rows.

    Decoupled from ``DailyReflectionService`` so a missing store / failed
    fetch leaves the rest of reflection running.
    """

    def __init__(
        self,
        event_store: DivergenceEventStore,
        pattern_store: PatternStore,
        *,
        min_count: int = DEFAULT_MIN_COUNT,
    ) -> None:
        self.event_store = event_store
        self.pattern_store = pattern_store
        self.min_count = min_count

    def analyze(
        self,
        *,
        agent_id: UUID,
        start: datetime,
        end: datetime,
        run_key: str,
    ) -> tuple[list[PatternCandidate], list[str]]:
        """
        Returns ``(patterns_stored, rupture_observations)``.

        ``patterns_stored`` contains the canonical persisted patterns (after
        idempotent dedup); ``rupture_observations`` is a list of short text
        lines that should be appended to ``ReflectionEvent.key_insight``.
        """
        if not run_key:
            return ([], [])
        try:
            events = self.event_store.list_in_range(agent_id, start, end)
        except Exception:
            # Aggregator never fails the surrounding reflection.
            return ([], [])

        if not events:
            return ([], [])

        ruptures = collect_rupture_observations(events)

        stored: list[PatternCandidate] = []
        for div_type, bucket in aggregate_divergence_events(events, min_count=self.min_count):
            description = f"divergence '{div_type}' recurring ({len(bucket)}x today)"
            candidate = PatternCandidate(
                pattern_type=PatternType.BEHAVIOR,
                status=PatternStatus.CANDIDATE,
                description=description,
                based_on_moment_ids=[
                    ev.key_moment_id for ev in bucket if ev.key_moment_id is not None
                ],
                detected_by=ReflectionLevel.DAILY,
                confidence=0.6,
            )
            detection_key = daily_divergence_pattern_detection_key(run_key, div_type)
            stored.append(self.pattern_store.save_with_detection_key(detection_key, candidate))
        return (stored, ruptures)
