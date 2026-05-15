"""
ExperienceViewRepository — compat adapter bridging new sessions+key_moments to Reflection Engine.

After migration 0008, agent_N.experiences is gone. Reflection Engine still expects
ExperienceRepository (get/get_all/get_by_session/get_recent/get_in_range/update/add_reframing_note).

This adapter builds virtual SessionExperience objects from the new tables:
  - experience_id ≡ session_id (1:1 mapping — one experience per session)
  - key_moments loaded via state_store.get_key_moments_for_session()
  - add_reframing_note writes to reframing_notes with session_id (not experience_id)

Remove this adapter when Reflection Engine migrates to SessionRepository contract
(see docs/architecture/REFLECTION_FUTURE.md).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from atman.core.models.experience import (
    ReframingNote,
    ReframingNoteAppendResult,
    SessionExperience,
)
from atman.core.models.session import Session
from atman.core.ports.state_store import StateStore


def _build_session_experience(session: Session, moments_for_session: list) -> SessionExperience:
    """Build a virtual SessionExperience from a Session + its KeyMoments."""
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
    fact_refs = list(dict.fromkeys(fact_refs))  # dedup preserving order

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
        id=session.id,  # experience_id == session_id in compat layer
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
        overall_tone=session.overall_tone,
        key_insight=session.key_insight,
    )


class ExperienceViewRepository:
    """
    Builds virtual SessionExperience objects from sessions + key_moments.

    Implements ExperienceRepository protocol so Reflection Engine needs no changes.
    experience_id is treated as session_id throughout this adapter.
    """

    def __init__(self, state_store: StateStore) -> None:
        self._store = state_store

    def _get_all_sessions(self) -> list[Session]:
        """Collect all sessions via state_store (fallback: scan key moments for session_ids)."""
        sessions = []
        seen: set[UUID] = set()
        for km in self._store.list_key_moments():
            if km.session_id and km.session_id not in seen:
                seen.add(km.session_id)
                s = self._store.get_session(km.session_id)
                if s:
                    sessions.append(s)
        return sessions

    def get(self, experience_id: UUID) -> SessionExperience | None:
        """Get virtual experience (= session) by ID."""
        session = self._store.get_session(experience_id)
        if session is None:
            return None
        moments = self._store.get_key_moments_for_session(experience_id)
        return _build_session_experience(session, moments)

    def get_all(self) -> list[SessionExperience]:
        """Get all virtual experiences."""
        sessions = self._get_all_sessions()
        result = []
        for session in sessions:
            moments = self._store.get_key_moments_for_session(session.id)
            if moments:  # only sessions that have key moments
                result.append(_build_session_experience(session, moments))
        result.sort(key=lambda e: e.timestamp, reverse=True)
        return result

    def get_by_session(self, session_id: UUID) -> list[SessionExperience]:
        """Get all experiences from a session (returns 0 or 1 item in compat layer)."""
        exp = self.get(session_id)
        return [exp] if exp else []

    def get_recent(self, limit: int = 10) -> list[SessionExperience]:
        """Get most recent virtual experiences."""
        return self.get_all()[:limit]

    def get_in_range(self, start: datetime, end: datetime) -> list[SessionExperience]:
        """Get virtual experiences within a date range."""
        return [e for e in self.get_all() if start <= e.timestamp <= end]

    def update(self, experience: SessionExperience) -> None:
        """Update session from virtual experience (noop for compat — sessions update via state_store)."""

    def add_reframing_note(
        self, experience_id: UUID, note: ReframingNote
    ) -> ReframingNoteAppendResult:
        """
        Append a reframing note. In compat layer, experience_id == session_id.
        Writes to state_store.add_reframing_note (which targets the experience record).
        """
        result = self._store.add_reframing_note(experience_id, note)
        if result is None:
            return ReframingNoteAppendResult.EXPERIENCE_NOT_FOUND
        return ReframingNoteAppendResult.STORED
