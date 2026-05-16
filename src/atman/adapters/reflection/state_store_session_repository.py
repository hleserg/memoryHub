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
from typing import overload
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

    @overload
    def list_recent_sessions(self, agent_id: UUID, *, limit: int = 10) -> list[Session]: ...

    @overload
    def list_recent_sessions(self, *, limit: int = 10) -> list[Session]: ...

    def list_recent_sessions(
        self, agent_id: UUID | None = None, *, limit: int = 10
    ) -> list[Session]:
        return self._store.list_recent_sessions(self._resolve_agent_id(agent_id), limit=limit)

    @overload
    def get_sessions_in_range(
        self, agent_id: UUID, start: datetime, end: datetime
    ) -> list[Session]: ...

    @overload
    def get_sessions_in_range(self, agent_id: datetime, start: datetime) -> list[Session]: ...

    def get_sessions_in_range(
        self,
        agent_id: UUID | datetime,
        start: datetime,
        end: datetime | None = None,
    ) -> list[Session]:
        """Filter sessions whose ``started_at`` falls in ``[start, end]``.

        Accepts two call shapes for ergonomic use:
          - ``(agent_id, start, end)`` — explicit agent UUID
          - ``(start, end)`` — first arg is range start; uses default ``agent_id``
        """
        if isinstance(agent_id, datetime):
            resolved_agent = self._resolve_agent_id(None)
            range_start = agent_id
            range_end = start
        else:
            resolved_agent = self._resolve_agent_id(agent_id)
            range_start = start
            range_end = end
            if range_end is None:  # pragma: no cover — defensive
                raise ValueError("get_sessions_in_range: end must be provided")
        agent_id = resolved_agent
        start = range_start
        end_val = range_end

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
        (matching the prior :class:`ExperienceViewRepository` mapping). A
        future R2 migration will replace this shim with a session-anchored
        port signature.

        Dedup is **pre-checked** here instead of inferred post-hoc: we read
        the existing experience and short-circuit on a matching
        ``triggered_by``. This is necessary because the underlying
        StateStore implementations disagree on dedup semantics (some
        silently skip the append on collision; others append blindly), so
        post-hoc length comparison would misclassify the outcome.
        """
        existing = self._store.get_experience(session_id)
        if existing is None:
            return ReframingNoteAppendResult.EXPERIENCE_NOT_FOUND
        if note.triggered_by and any(
            n.triggered_by == note.triggered_by for n in existing.experience.reframing_notes
        ):
            return ReframingNoteAppendResult.DUPLICATE_TRIGGERED_BY
        result = self._store.add_reframing_note(session_id, note)
        if result is None:
            return ReframingNoteAppendResult.EXPERIENCE_NOT_FOUND
        return ReframingNoteAppendResult.STORED
