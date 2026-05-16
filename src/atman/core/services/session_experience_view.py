"""
Bridge helper: build a virtual :class:`SessionExperience` from a
:class:`Session` plus its :class:`KeyMoment` list.

Used while Reflection Engine consumes :class:`SessionExperience`-shaped DTOs
internally but reads raw sessions + moments through :class:`SessionRepository`.
When ``ReflectionModel`` is itself migrated to accept ``(Session, moments)``
directly (see ``REFLECTION_FUTURE.md``), this helper becomes obsolete and
can be deleted along with ``adapters/reflection_compat/``.
"""

from __future__ import annotations

from uuid import UUID

from atman.core.models.experience import KeyMoment, SessionExperience
from atman.core.models.session import Session


def build_session_experience(
    session: Session,
    moments_for_session: list[KeyMoment],
) -> SessionExperience:
    """Synthesize a :class:`SessionExperience` from a session + its moments."""
    moment_ids = [m.id for m in moments_for_session]

    avg_intensity = 0.5
    has_profound = False
    if moments_for_session:
        avg_intensity = sum(m.how_i_felt.emotional_intensity for m in moments_for_session) / len(
            moments_for_session
        )
        has_profound = any(m.how_i_felt.depth.value == "profound" for m in moments_for_session)

    fact_refs: list[UUID] = []
    for m in moments_for_session:
        fact_refs.extend(m.fact_refs)
    fact_refs = list(dict.fromkeys(fact_refs))

    overall_salience = max(m.salience for m in moments_for_session) if moments_for_session else 0.5
    overall_importance = (
        max(m.importance for m in moments_for_session) if moments_for_session else 0.5
    )
    last_accessed = (
        max(m.last_accessed_at for m in moments_for_session)
        if moments_for_session
        else session.started_at
    )
    access_count = sum(m.access_count for m in moments_for_session)
    incomplete = any(m.incomplete_coloring for m in moments_for_session)

    return SessionExperience(
        id=session.id,
        session_id=session.id,
        timestamp=session.started_at,
        key_moment_ids=moment_ids,
        unexamined_fact_refs=list(session.unexamined_fact_refs),
        close_reason=session.close_reason,  # type: ignore[arg-type]
        agent_recap=session.agent_recap,
        restart_reason=session.restart_reason,
        user_language=session.user_language,
        recorded_by="session_manager",
        identity_snapshot_id=session.identity_snapshot_id,
        importance=overall_importance,
        salience=overall_salience,
        last_accessed_at=last_accessed,
        access_count=access_count,
        avg_emotional_intensity=avg_intensity,
        has_profound_moment=has_profound,
        incomplete_coloring=incomplete,
        fact_refs=fact_refs,
    )
