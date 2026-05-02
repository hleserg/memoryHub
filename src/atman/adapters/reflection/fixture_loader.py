"""
JSON fixtures for reflection demos/CLI.

Anchors experience timestamps into the current UTC calendar day so
`get_in_range(start_of_today, now)` and daily windows include fixture data.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from atman.core.models.experience import SessionExperience
from atman.core.models.identity import Identity


def reflection_fixtures_dir() -> Path:
    """Directory containing `experiences.json` and `identity.json`."""
    return Path(__file__).resolve().parents[4] / "fixtures" / "reflection"


def load_reflection_session_experiences(
    *,
    experiences_path: Path | None = None,
) -> list[SessionExperience]:
    """Load session experiences from JSON (fixtures/reflection/experiences.json)."""
    path = experiences_path or reflection_fixtures_dir() / "experiences.json"
    with path.open(encoding="utf-8") as f:
        raw = json.load(f)
    return [SessionExperience.model_validate(item) for item in raw]


def load_reflection_identity(*, identity_path: Path | None = None) -> Identity:
    """Load identity from JSON (fixtures/reflection/identity.json)."""
    path = identity_path or reflection_fixtures_dir() / "identity.json"
    with path.open(encoding="utf-8") as f:
        return Identity.model_validate(json.load(f))


def anchor_session_experiences_to_utc_day_window(
    experiences: list[SessionExperience],
    *,
    interval_end: datetime | None = None,
) -> list[SessionExperience]:
    """
    Spread timestamps strictly inside [start of UTC day, interval_end].

    Used so CLI deep/daily queries that use "today" still see fixture rows.
    """
    end = interval_end or datetime.now(UTC)
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    else:
        end = end.astimezone(UTC)
    start = end.replace(hour=0, minute=0, second=0, microsecond=0)
    if not experiences:
        return []
    if end <= start:
        return [exp.model_copy(update={"timestamp": end}) for exp in experiences]

    span_seconds = (end - start).total_seconds()
    n = len(experiences)
    out: list[SessionExperience] = []
    for i, exp in enumerate(experiences):
        offset = (span_seconds * (i + 1)) / (n + 1)
        ts = min(start + timedelta(seconds=offset), end)
        out.append(exp.model_copy(update={"timestamp": ts}))
    return out
