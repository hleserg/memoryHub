"""
ReflectionInputBuilder - pre-summarize KeyMoments before deep reflection.

Prevents unbounded prompt growth by capping the moments fed into a single
reflection pass and grouping them by session for structured context.

Hard limit: at most ``max_moments`` moments (sorted by salience desc).
Excess moments are returned in ``remaining_moments`` for the next cycle.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from uuid import UUID

from atman.core.models.experience import KeyMoment


@dataclass
class SessionSummary:
    """Aggregated view of key moments from one session."""

    session_id: UUID | None
    top_moments: list[KeyMoment]
    """Top-3 moments by salience within this session group."""
    marker_counts: dict[str, int]
    """Counts of structured_markers keys across all moments in the group."""
    total_count: int
    """Total moments in this session group (before truncation to top-3)."""


@dataclass
class ReflectionInput:
    """Pre-processed input ready to feed into the reflection LLM prompt."""

    session_summaries: list[SessionSummary] = field(default_factory=list)
    remaining_moments: list[KeyMoment] = field(default_factory=list)
    """Moments that exceeded max_moments — skip to next reflection cycle."""
    total_selected: int = 0
    total_skipped: int = 0


def _count_markers(moments: list[KeyMoment]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for m in moments:
        if m.structured_markers:
            for key in m.structured_markers:
                counts[key] += 1
    return dict(counts)


def prepare_reflection_input(
    moments: list[KeyMoment],
    max_moments: int = 30,
) -> ReflectionInput:
    """
    Sort moments by salience (desc), cap at ``max_moments``, group by session.

    Returns a :class:`ReflectionInput` whose ``session_summaries`` are ready
    to render into a reflection prompt without further LLM calls.
    """
    sorted_moments = sorted(moments, key=lambda m: m.salience, reverse=True)
    selected = sorted_moments[:max_moments]
    remaining = sorted_moments[max_moments:]

    # Group selected moments by session_id (None → legacy moments without session)
    by_session: dict[UUID | None, list[KeyMoment]] = defaultdict(list)
    for m in selected:
        by_session[m.session_id].append(m)

    summaries: list[SessionSummary] = []
    for session_id, session_moments in by_session.items():
        # Each group is already in salience-desc order (inherited from sorted_moments)
        top_3 = session_moments[:3]
        summaries.append(
            SessionSummary(
                session_id=session_id,
                top_moments=top_3,
                marker_counts=_count_markers(session_moments),
                total_count=len(session_moments),
            )
        )

    # Sort summaries by highest salience moment for deterministic output
    summaries.sort(
        key=lambda s: s.top_moments[0].salience if s.top_moments else 0.0,
        reverse=True,
    )

    return ReflectionInput(
        session_summaries=summaries,
        remaining_moments=remaining,
        total_selected=len(selected),
        total_skipped=len(remaining),
    )
