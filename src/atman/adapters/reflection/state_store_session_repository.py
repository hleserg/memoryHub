"""StateStoreSessionRepository — adapt any :class:`StateStore` to :class:`SessionRepository`.

This is the bridge between the storage port (`StateStore`) and the Reflection
Engine's read-side port (`SessionRepository`) introduced by Этап 18
(REFLECTION_FUTURE.md §3). It replaces :class:`ExperienceViewRepository` —
instead of synthesising virtual :class:`SessionExperience` objects, the new
adapter exposes :class:`Session` + :class:`KeyMoment` directly, which is what
the rewritten reflection services consume.

Reframing notes: ``add_reframing_note`` writes to a per-session list inside the
StateStore. The :class:`StateStore` base port grew a matching
``store_reframing_note(session_id, note)`` method (see migration commit) so all
adapters that already implement Session persistence can record notes without
needing to invent an ``ExperienceRecord`` shell.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from atman.core.models.experience import KeyMoment, ReframingNote, ReframingNoteAppendResult
from atman.core.models.session import Session
from atman.core.ports.state_store import StateStore


class StateStoreSessionRepository:
    """Implements :class:`SessionRepository` over any :class:`StateStore`.

    Each method delegates to the matching StateStore call. Sessions and
    key moments are read live (no caching) so reflection sees consistent
    state across the run.
    """

    def __init__(
        self,
        state_store: StateStore,
        *,
        agent_id: UUID | None = None,
    ) -> None:
        """Wire a StateStore as a SessionRepository.

        Parameters
        ----------
        state_store:
            The underlying storage adapter (InMemoryStateStore, FileStateStore,
            PostgresStateStore — anything implementing the v2 Session API).
        agent_id:
            Optional default agent filter used by :meth:`list_recent_sessions`
            and :meth:`get_sessions_in_range`. When the caller doesn't pass
            an agent_id, this default is used. Single-agent deployments
            should set it once at construction.
        """
        self._store = state_store
        self._default_agent_id = agent_id

    def _resolve_agent_id(self, agent_id: UUID | None) -> UUID:
        if agent_id is not None:
            return agent_id
        if self._default_agent_id is not None:
            return self._default_agent_id
        raise ValueError(
            "StateStoreSessionRepository: no agent_id provided and no default "
            "agent_id was set at construction time."
        )

    def get_session(self, session_id: UUID) -> Session | None:
        return self._store.get_session(session_id)

    def list_recent_sessions(
        self, agent_id: UUID | None = None, *, limit: int = 10
    ) -> list[Session]:
        return self._store.list_recent_sessions(self._resolve_agent_id(agent_id), limit=limit)

    def get_sessions_in_range(
        self,
        agent_id_or_start: UUID | datetime,
        start_or_end: datetime,
        end: datetime | None = None,
    ) -> list[Session]:
        """Filter sessions whose ``started_at`` falls in ``[start, end]``.

        Accepts two call shapes for ergonomic use:
          - ``(agent_id, start, end)`` — explicit
          - ``(start, end)`` — uses the constructor-time default agent_id
        """
        if isinstance(agent_id_or_start, datetime):
            agent_id = self._resolve_agent_id(None)
            start = agent_id_or_start
            end_val = start_or_end
        else:
            agent_id = self._resolve_agent_id(agent_id_or_start)
            start = start_or_end
            end_val = end  # type: ignore[assignment]
            if end_val is None:  # pragma: no cover — defensive
                raise ValueError("get_sessions_in_range: end must be provided")

        # Pull a generous window via list_recent_sessions; filter by range.
        # For deployments where sessions/day is high this should become a
        # native query on the StateStore — but in-memory and file adapters
        # don't have one yet, so we filter client-side.
        candidates = self._store.list_recent_sessions(agent_id, limit=10_000)
        return [s for s in candidates if start <= s.started_at <= end_val]

    def get_key_moments_for_session(self, session_id: UUID) -> list[KeyMoment]:
        return self._store.get_key_moments_for_session(session_id)

    def get_key_moments_in_range(self, start: datetime, end: datetime) -> list[KeyMoment]:
        moments = self._store.list_key_moments()
        return [m for m in moments if start <= m.when <= end]

    def add_reframing_note(
        self, session_id: UUID, note: ReframingNote
    ) -> ReframingNoteAppendResult:
        """Append a reframing note to the session.

        Compat shim: under v2 the legacy ``experience_id`` argument on
        :meth:`StateStore.add_reframing_note` is treated as ``session_id``
        (matching the prior :class:`ExperienceViewRepository` mapping). When
        the StateStore returns ``None`` it means no experience record exists
        for this session yet — which is the normal case for fresh sessions
        that finished without going through the legacy experience flow. We
        report :attr:`ReframingNoteAppendResult.EXPERIENCE_NOT_FOUND` so
        Reflection logs the outcome explicitly. A future migration of
        ``StateStore.add_reframing_note`` to a session-anchored signature
        will replace this shim.
        """
        result = self._store.add_reframing_note(session_id, note)
        if result is None:
            return ReframingNoteAppendResult.EXPERIENCE_NOT_FOUND
        # Check for the duplicate-trigger contract: the in-memory and file
        # stores keep the existing note rather than appending when
        # `triggered_by` collides.
        if note.triggered_by:
            triggers = [
                n.triggered_by
                for n in result.experience.reframing_notes
                if n.triggered_by == note.triggered_by
            ]
            if len(triggers) > 1:
                return ReframingNoteAppendResult.DUPLICATE_TRIGGERED_BY
        return ReframingNoteAppendResult.STORED
