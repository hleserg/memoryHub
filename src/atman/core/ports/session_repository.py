"""SessionRepository — Reflection-side view of sessions + key moments + reframing notes.

Replaces ExperienceRepository as part of Этап 18 (REFLECTION_FUTURE.md §3).
The new contract is built around the v2 storage model where:

  - ``Session`` is the canonical persisted unit (was: ``SessionExperience``).
  - ``KeyMoment`` is a first-class record with its own ``session_id`` FK
    (was: nested inside ``SessionExperience.key_moment_ids``).
  - ``ReframingNote`` is anchored to the session by ``session_id`` (was:
    by the legacy ``experience_id``, which equalled ``session_id`` in
    compat shimming).

Reflection Engine consumers only ever need to: read a session's
metadata + its key moments, iterate sessions in a time window, and
append reframing notes after the reflection finishes. The port surface
is intentionally small — anything else (entity stance, validation
findings, divergence events) is wired through its own port.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from atman.core.models.experience import KeyMoment, ReframingNote, ReframingNoteAppendResult
from atman.core.models.session import Session


@runtime_checkable
class SessionRepository(Protocol):
    """Read sessions + their key moments and append reframing notes.

    Implementations: :class:`StateStoreSessionRepository` (adapter over any
    :class:`StateStore`), or a direct DB-backed implementation for
    deployments that don't go through :class:`StateStore`.
    """

    def get_session(self, session_id: UUID) -> Session | None:
        """Return the persisted Session row by id, or None when absent."""
        ...

    def list_recent_sessions(self, agent_id: UUID, *, limit: int = 10) -> list[Session]:
        """List the most recent sessions for ``agent_id``, newest first."""
        ...

    def get_sessions_in_range(
        self, agent_id: UUID, start: datetime, end: datetime
    ) -> list[Session]:
        """Sessions started in the closed interval ``[start, end]`` (UTC)."""
        ...

    def get_key_moments_for_session(self, session_id: UUID) -> list[KeyMoment]:
        """All key moments belonging to a single session, in insertion order."""
        ...

    def get_key_moments_in_range(self, start: datetime, end: datetime) -> list[KeyMoment]:
        """Key moments whose ``when`` falls in ``[start, end]`` (UTC).

        Used by reflection batching to bound the prompt size when a single
        session is large or when a daily window spans many short sessions.
        """
        ...

    def add_reframing_note(
        self, session_id: UUID, note: ReframingNote
    ) -> ReframingNoteAppendResult:
        """Append a reframing note to the session.

        The note's ``triggered_by`` provides natural idempotency — repeated
        appends with the same trigger return :attr:`ReframingNoteAppendResult.
        DUPLICATE_TRIGGERED_BY` and do not duplicate the row.
        """
        ...
