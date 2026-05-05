"""Pydantic models for on-disk session fixtures and LLM tool I/O."""

from __future__ import annotations

import json
import re
import zlib
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator

from atman.core.models.experience import EmotionalDepth
from atman.core.models.session import KeyMomentInput, SessionEvent


class SessionFixtureMetadata(BaseModel):
    """Session-level metadata (planning / narrative arc)."""

    session_number: int = Field(ge=1, description="1-based index in the corpus")
    theme: str = Field(min_length=1, description="Short theme slug or label")
    duration_seconds: int = Field(ge=60, le=86400, description="Approximate session length")
    narrative_arc: str = Field(
        min_length=1, description="One sentence: emotional trajectory of the session"
    )


class FixtureEventRecord(BaseModel):
    """One raw session event as stored in JSON (no session_id — injected when replaying)."""

    event_type: str = Field(min_length=1)
    description: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("description")
    @classmethod
    def strip_description(cls, v: str) -> str:
        t = v.strip()
        if not t:
            raise ValueError("description cannot be empty")
        return t


class KeyMomentFixtureRecord(BaseModel):
    """Key moment fields aligned with :class:`KeyMomentInput` (depth as string in JSON)."""

    what_happened: str = Field(min_length=1)
    emotional_valence: float = Field(ge=-1.0, le=1.0)
    emotional_intensity: float = Field(ge=0.0, le=1.0)
    depth: EmotionalDepth
    why_it_matters: str = Field(min_length=1)
    values_touched: list[str] = Field(default_factory=list)
    principles_confirmed: list[str] = Field(default_factory=list)
    principles_questioned: list[str] = Field(default_factory=list)
    what_changed: str = Field(default="")
    incomplete_coloring: bool = False

    @field_validator(
        "what_happened",
        "why_it_matters",
        "what_changed",
        mode="before",
    )
    @classmethod
    def strip_text(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator("values_touched", "principles_confirmed", "principles_questioned")
    @classmethod
    def normalize_str_list(cls, v: list[str]) -> list[str]:
        return [x.strip() for x in v if isinstance(x, str) and x.strip()]


class ExpectedSessionOutcome(BaseModel):
    """Expected result after :meth:`~atman.core.services.session_manager.SessionManager.finish_session`."""

    overall_emotional_tone: float = Field(ge=-1.0, le=1.0)
    key_insight: str = Field(min_length=1)
    alignment_check: bool = True


class SessionFixtureDocument(BaseModel):
    """Full per-session fixture file (matches issue #141 shape)."""

    metadata: SessionFixtureMetadata
    events: list[FixtureEventRecord] = Field(min_length=3, max_length=5)
    key_moments: list[KeyMomentFixtureRecord] = Field(min_length=2, max_length=3)
    expected_session_outcome: ExpectedSessionOutcome


class SessionSkeletonItem(BaseModel):
    """One row from the skeleton pass — corpus-level planning."""

    session_number: int = Field(ge=1)
    theme: str = Field(min_length=1)
    narrative_arc: str = Field(min_length=1)
    key_values: list[str] = Field(min_length=1, description="Values to weave into this session")
    key_principles: list[str] = Field(
        default_factory=list,
        description="Principles to confirm, question, or echo across events",
    )


class SkeletonPassOutput(BaseModel):
    """Tool output: planned skeleton for all sessions."""

    sessions: list[SessionSkeletonItem] = Field(min_length=1, max_length=32)


def theme_to_slug(theme: str, session_number: int | None = None) -> str:
    """Derive filesystem slug from theme (``session_NN_<slug>.json``)."""
    s = theme.lower().strip()
    ascii_slug = re.sub(r"[^a-z0-9]+", "_", s)
    ascii_slug = re.sub(r"_+", "_", ascii_slug).strip("_")
    if ascii_slug:
        return ascii_slug[:80]
    # Cyrillic or other scripts: stable short ASCII name
    crc = zlib.crc32(theme.encode("utf-8")) & 0xFFFFFFFF
    if session_number is not None:
        return f"{session_number:02d}_{crc:08x}"
    return f"{crc:08x}"


def coerce_metadata_str(d: dict[str, Any]) -> dict[str, str]:
    """``SessionEvent`` requires ``dict[str, str]``."""
    out: dict[str, str] = {}
    for k, v in d.items():
        key = str(k).strip()
        if not key:
            continue
        if isinstance(v, str):
            out[key] = v
        else:
            out[key] = json.dumps(v, ensure_ascii=False)
    return out


def fixture_events_to_session_events(
    records: list[FixtureEventRecord], session_id: UUID
) -> list[SessionEvent]:
    """Validate fixture events as :class:`SessionEvent` instances."""
    result: list[SessionEvent] = []
    for r in records:
        result.append(
            SessionEvent(
                session_id=session_id,
                event_type=r.event_type.strip(),
                description=r.description,
                metadata=coerce_metadata_str(dict(r.metadata)),
            )
        )
    return result


def fixture_moments_to_key_moment_inputs(
    records: list[KeyMomentFixtureRecord],
) -> list[KeyMomentInput]:
    """Validate key moments as :class:`KeyMomentInput` instances."""
    return [
        KeyMomentInput(
            what_happened=m.what_happened,
            emotional_valence=m.emotional_valence,
            emotional_intensity=m.emotional_intensity,
            depth=m.depth,
            why_it_matters=m.why_it_matters,
            values_touched=list(m.values_touched),
            principles_confirmed=list(m.principles_confirmed),
            principles_questioned=list(m.principles_questioned),
            what_changed=m.what_changed,
            incomplete_coloring=m.incomplete_coloring,
        )
        for m in records
    ]


def validate_fixture_document(doc: SessionFixtureDocument) -> None:
    """
    Validate domain models and intra-session coherence.

    Raises ``ValueError`` with a human-readable reason if validation fails.
    """
    sid = uuid4()
    fixture_events_to_session_events(doc.events, sid)
    kms = fixture_moments_to_key_moment_inputs(doc.key_moments)
    _check_weighted_tone(kms, doc.expected_session_outcome.overall_emotional_tone)
    _check_principles_prefixed_in_events(doc.events, doc.key_moments)
    _ = kms  # constructed for side-effect validation


def weighted_mean_valence(moments: list[KeyMomentInput]) -> float:
    """Intensity-weighted average valence (same formula as issue #141)."""
    if not moments:
        return 0.0
    num = sum(m.emotional_valence * m.emotional_intensity for m in moments)
    den = sum(m.emotional_intensity for m in moments)
    if den <= 0:
        return 0.0
    return num / den


def _check_weighted_tone(moments: list[KeyMomentInput], expected: float) -> None:
    computed = weighted_mean_valence(moments)
    if abs(computed - expected) > 0.1 + 1e-9:
        raise ValueError(
            f"expected_session_outcome.overall_emotional_tone={expected:.3f} inconsistent "
            f"with intensity-weighted mean valence of key moments ({computed:.3f}); "
            "allowed delta is 0.1"
        )


def norm_token(s: str) -> str:
    normalized = s.lower().replace("_", " ")
    # Treat punctuation/dashes as separators so LLM phrasing variants still match.
    normalized = re.sub(r"[^\w]+", " ", normalized, flags=re.UNICODE)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _event_blob(events: list[FixtureEventRecord]) -> str:
    parts: list[str] = []
    for e in events:
        parts.append(norm_token(e.description))
        parts.append(norm_token(e.event_type))
        for _k, v in e.metadata.items():
            parts.append(norm_token(str(v)))
    return " ".join(parts)


def _check_principles_prefixed_in_events(
    events: list[FixtureEventRecord],
    moments: list[KeyMomentFixtureRecord],
) -> None:
    """Each ``principles_questioned`` must appear in event text *before* its moment segment."""
    n_e = len(events)
    n_m = len(moments)
    if n_m == 0:
        return
    for mi, km in enumerate(moments):
        cutoff = max(1, int((mi + 1) * n_e / n_m))
        prefix = events[:cutoff]
        blob = _event_blob(prefix)
        for pq in km.principles_questioned:
            needle = norm_token(pq)
            if not needle:
                continue
            # Long abstract principles are often paraphrased by the model.
            # Keep this as a best-effort guard, not a hard blocker for >5 tokens.
            if len(needle.split()) > 5:
                continue
            if not _principle_mentioned_in_blob(needle, blob):
                raise ValueError(
                    f"principles_questioned item {pq!r} for key moment {mi + 1} must be "
                    f"mentioned in an earlier event (checked first {cutoff} events)"
                )


def _principle_mentioned_in_blob(needle: str, blob: str) -> bool:
    """Allow lightweight paraphrase matching for principle strings."""
    if needle in blob:
        return True
    needle_tokens = [t for t in needle.split() if len(t) >= 3]
    if len(needle_tokens) < 2:
        return False
    matched = sum(1 for token in needle_tokens if token in blob)
    # Require at least two meaningful tokens and half of principle tokens.
    return matched >= 2 and matched >= (len(needle_tokens) + 1) // 2
