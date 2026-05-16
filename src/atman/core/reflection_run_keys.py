"""Deterministic reflection job keys and stable UUID derivation."""

from __future__ import annotations

import hashlib
from datetime import datetime
from uuid import UUID, uuid5

from atman.core.clock_impl import ensure_utc

# DNS namespace is arbitrary but stable for uuid5 derivation.
_REFLECTION_UUID_NS = UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
_PATTERN_UUID_NS = UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")
_HEALTH_UUID_NS = UUID("6ba7b812-9dad-11d1-80b4-00c04fd430c8")
_IDENTITY_ANCHOR_SNAPSHOT_NS = UUID("6ba7b813-9dad-11d1-80b4-00c04fd430c8")


def _calendar_day_utc(dt: datetime) -> str:
    d = ensure_utc(dt).date()
    return d.isoformat()


def daily_reflection_run_key_empty_day(calendar_anchor: datetime) -> str:
    """Run key when the day has no experiences to analyze."""
    return f"daily|v1|{_calendar_day_utc(calendar_anchor)}|empty"


def daily_reflection_run_key_no_identity(
    calendar_anchor: datetime, experience_ids: list[UUID]
) -> str:
    """Run key when reflection is skipped because identity is missing."""
    digest = hashlib.sha256(
        "|".join(sorted(str(i) for i in experience_ids)).encode("utf-8")
    ).hexdigest()[:24]
    return f"daily|v1|{_calendar_day_utc(calendar_anchor)}|no_identity|{digest}"


def daily_reflection_run_key_for_identity(calendar_anchor: datetime, identity_id: UUID) -> str:
    """Run key for a normal daily reflection tied to a calendar day and identity."""
    return f"daily|v1|{_calendar_day_utc(calendar_anchor)}|identity|{identity_id}"


def deep_reflection_run_key_empty(since: datetime, until: datetime) -> str:
    """Run key when the deep window has no experiences."""
    s, u = ensure_utc(since).isoformat(), ensure_utc(until).isoformat()
    return f"deep|v1|empty|{s}|{u}"


def deep_reflection_run_key_no_identity(
    since: datetime, until: datetime, experience_ids: list[UUID]
) -> str:
    """Run key when deep reflection is skipped (no identity)."""
    s, u = ensure_utc(since).isoformat(), ensure_utc(until).isoformat()
    digest = hashlib.sha256(
        "|".join(sorted(str(i) for i in experience_ids)).encode("utf-8")
    ).hexdigest()[:24]
    return f"deep|v1|no_identity|{s}|{u}|{digest}"


def deep_reflection_run_key_for_identity(
    since: datetime, until: datetime, identity_id: UUID
) -> str:
    """Run key for deep reflection over a window and identity."""
    s, u = ensure_utc(since).isoformat(), ensure_utc(until).isoformat()
    return f"deep|v1|identity|{identity_id}|{s}|{u}"


def reflection_event_id_for_run_key(run_key: str) -> UUID:
    """Stable event id so upserts and retries address the same row."""
    return uuid5(_REFLECTION_UUID_NS, run_key)


def pattern_id_for_detection_key(detection_key: str) -> UUID:
    """Stable pattern id for idempotent pattern detection."""
    return uuid5(_PATTERN_UUID_NS, detection_key)


def health_assessment_id_for_run_key(run_key: str) -> UUID:
    """Stable health assessment id for the same deep reflection job."""
    return uuid5(_HEALTH_UUID_NS, run_key)


def daily_pattern_detection_key(run_key: str, pattern_type_value: str) -> str:
    """Fingerprint for a single daily pattern slot."""
    return f"pattern|daily|{run_key}|{pattern_type_value}"


def daily_marker_pattern_detection_key(run_key: str, signal_type: str, signal_value: str) -> str:
    """Fingerprint for a per-marker daily pattern slot (one per signal_type+value)."""
    return f"pattern|daily|{run_key}|marker|{signal_type}|{signal_value}"


def daily_divergence_pattern_detection_key(run_key: str, divergence_type: str) -> str:
    """Fingerprint for a per-divergence-type daily pattern slot (R6)."""
    return f"pattern|daily|{run_key}|divergence|{divergence_type}"


def deep_pattern_detection_key(run_key: str, pattern_type_value: str) -> str:
    """Fingerprint for a deep pattern slot (one per pattern type)."""
    return f"pattern|deep|{run_key}|{pattern_type_value}"


def identity_anchor_snapshot_id_for_run_key(run_key: str) -> UUID:
    """Stable :class:`~atman.core.models.identity.IdentitySnapshot` id for a reflection job anchor."""
    return uuid5(_IDENTITY_ANCHOR_SNAPSHOT_NS, run_key)


def reframing_trigger_key(run_key: str, experience_id: UUID) -> str:
    """Stable ``triggered_by`` for deduplicating reframing per job and experience."""
    return f"reflection|{run_key}|reframe|{experience_id}"


def _hour_bucket_utc(dt: datetime) -> str:
    """ISO-formatted UTC hour bucket; minutes/seconds discarded."""
    d = ensure_utc(dt).replace(minute=0, second=0, microsecond=0)
    return d.isoformat()


# PLAYBOOK-START
# id: time-bucketed-hash-idempotency-keys
# category: design-patterns
# title: Time-Bucketed Hash Idempotency Keys for Async Request Queues
# status: draft
#
# Pattern: derive an idempotency key by hashing the normalized request
# payload together with a coarse time bucket (e.g. UTC hour, calendar day).
# Identical requests within the same bucket collapse to one queue entry;
# the bucket boundary acts as a natural rate limit and prevents permanent
# deduplication of legitimately recurring requests.
#
# Why generalizable: async pipelines that accept retried or duplicated
# user/agent input need to be safe under replay without rejecting valid
# follow-ups forever. Pairing content-hash with a time bucket gives
# stateless dedup (no per-request marker store) while still allowing the
# same intent to be re-queued after the window rolls over.
#
# Trade-offs: a request submitted near the bucket boundary may dedup
# against the prior window or skip into the next; bucket size is a
# correctness/usability knob the caller must pick deliberately.
# PLAYBOOK-END
def agent_driven_run_key(level: str, reason: str, when: datetime) -> str:
    """
    Idempotency key for an agent-initiated reflection request.

    Same reason inside the same UTC hour bucket collapses to one request, so
    the agent does not flood the queue with duplicates if it asks twice in a
    short interval.

    Args:
        level: ``"daily"`` or ``"deep"``.
        reason: free-form text from the agent. Whitespace-stripped and lowercased
            before hashing so trivially-different phrasings collide.
        when: timestamp used to assign the hour bucket.
    """
    normalized = " ".join(reason.strip().lower().split())
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
    return f"request|{level}|{_hour_bucket_utc(when)}|{digest}"
