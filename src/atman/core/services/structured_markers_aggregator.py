"""
StructuredMarkersAggregator — emit ``PatternCandidate`` from KeyMoment markers.

Pure aggregation over ``KeyMoment.structured_markers`` (LLM-annotated signals
like ``cognitive_load``, ``boundary_event``, ``trust_signal``, ``agency_level``,
``growth_indicator``). When ≥ ``min_count`` moments in the window share the
same ``signal_type`` → ``signal_value`` we record a daily-level
:class:`~atman.core.models.reflection.PatternCandidate` through the
existing :class:`~atman.core.ports.reflection.PatternStore` using
:func:`~atman.core.reflection_run_keys.daily_marker_pattern_detection_key`
for idempotency.

This service is intentionally LLM-free: it summarizes what the linguistic
analyzer already produced. Interpretation is left to other reflection
sub-services (e.g. ``EntityStanceFormulator``).
"""

from __future__ import annotations

from collections import defaultdict

from atman.core.models.experience import KeyMoment
from atman.core.models.reflection import (
    PatternCandidate,
    PatternStatus,
    PatternType,
    ReflectionLevel,
)
from atman.core.ports.reflection import PatternStore
from atman.core.reflection_run_keys import daily_marker_pattern_detection_key

DEFAULT_MIN_COUNT: int = 5

# Mapping of structured_markers signal types → reflection PatternType.
# Unmapped signal types fall back to BEHAVIOR (the conservative default).
_SIGNAL_PATTERN_TYPE: dict[str, PatternType] = {
    "cognitive_load": PatternType.COGNITIVE,
    "agency_level": PatternType.COGNITIVE,
    "growth_indicator": PatternType.VALUE_BASED,
    "boundary_event": PatternType.RELATIONAL,
    "trust_signal": PatternType.RELATIONAL,
}


def _normalize_value(value: object) -> str | None:
    """Return a stable scalar key for a marker value, or None to skip."""
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float | str):
        s = str(value).strip()
        return s or None
    # Skip nested dicts/lists — too noisy for fingerprint-based aggregation.
    return None


def _pattern_type_for(signal_type: str) -> PatternType:
    return _SIGNAL_PATTERN_TYPE.get(signal_type, PatternType.BEHAVIOR)


def aggregate_structured_markers(
    moments: list[KeyMoment],
    *,
    min_count: int = DEFAULT_MIN_COUNT,
) -> list[tuple[str, str, list[KeyMoment]]]:
    """
    Group moments by (signal_type, signal_value); keep groups with ≥ ``min_count``.

    Returns a list of ``(signal_type, signal_value, moments)`` for downstream
    persistence. Pure, deterministic; safe to call in tests.
    """
    if min_count <= 0:
        raise ValueError("min_count must be >= 1")

    buckets: dict[tuple[str, str], list[KeyMoment]] = defaultdict(list)
    for moment in moments:
        markers = moment.structured_markers or {}
        for signal_type, raw_value in markers.items():
            value_key = _normalize_value(raw_value)
            if value_key is None:
                continue
            buckets[(signal_type, value_key)].append(moment)

    out: list[tuple[str, str, list[KeyMoment]]] = []
    # Stable ordering for deterministic snapshots/tests.
    for signal_type, value_key in sorted(buckets.keys()):
        bucket_moments = buckets[(signal_type, value_key)]
        if len(bucket_moments) >= min_count:
            # Stable moment ordering by `when` then id.
            bucket_moments.sort(key=lambda m: (m.when, str(m.id)))
            out.append((signal_type, value_key, bucket_moments))
    return out


class StructuredMarkersAggregator:
    """
    Aggregate ``KeyMoment.structured_markers`` into daily ``PatternCandidate``s.

    Used by :class:`~atman.core.services.reflection_service.DailyReflectionService`
    after primary pattern detection. Persistence is idempotent per
    ``(run_key, signal_type, signal_value)`` via
    :meth:`PatternStore.save_with_detection_key`.
    """

    def __init__(
        self,
        pattern_store: PatternStore,
        *,
        min_count: int = DEFAULT_MIN_COUNT,
    ) -> None:
        self.pattern_store = pattern_store
        self.min_count = min_count

    def analyze(self, moments: list[KeyMoment], *, run_key: str) -> list[PatternCandidate]:
        """
        Persist one :class:`PatternCandidate` per qualifying marker bucket.

        Returns the list of stored patterns (after dedup via detection key).
        """
        if not moments or not run_key:
            return []

        stored: list[PatternCandidate] = []
        groups = aggregate_structured_markers(moments, min_count=self.min_count)
        for signal_type, signal_value, bucket_moments in groups:
            description = (
                f"structured_markers signal '{signal_type}'='{signal_value}' "
                f"observed in {len(bucket_moments)} moments today"
            )
            candidate = PatternCandidate(
                pattern_type=_pattern_type_for(signal_type),
                status=PatternStatus.CANDIDATE,
                description=description,
                based_on_moment_ids=[m.id for m in bucket_moments],
                detected_by=ReflectionLevel.DAILY,
                # Marker-level patterns are deterministic aggregates, not LLM
                # judgements — keep confidence modest so they don't dominate
                # higher-level synthesis until corroborated by Deep.
                confidence=0.6,
            )
            detection_key = daily_marker_pattern_detection_key(run_key, signal_type, signal_value)
            stored.append(self.pattern_store.save_with_detection_key(detection_key, candidate))
        return stored
