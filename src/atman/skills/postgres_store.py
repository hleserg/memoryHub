"""PostgreSQL SkillStore implementation.

Uses public.skills and public.skill_invocations (created by migration 0015).
Follows the same psycopg3 + dict_row pattern as PostgresFactualMemory.

RLS isolation:
    Both ``public.skills`` and ``public.skill_invocations`` use
    ``FORCE ROW LEVEL SECURITY`` with policy ``agent_id = current_setting(
    'atman.current_agent')``. ALL queries — read and write — must run on a
    connection where the session variable has been set, otherwise:

    * ``SELECT`` returns 0 rows
    * ``UPDATE`` affects 0 rows silently
    * ``INSERT`` is rejected by the policy

    To avoid silent corruption, this store binds to a single ``agent_id`` at
    construction time (same pattern as :class:`PostgresEntityStanceStore`) and
    every method funnels through :meth:`_conn`, which sets the session variable
    before yielding the connection. ``agent_id`` parameters on individual
    methods exist for parity with :class:`InMemorySkillStore` and are validated
    against the bound agent.
"""

from __future__ import annotations

import json
import warnings
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID, uuid4

from atman.skills.models import Skill, SkillInvocation, SkillKind, SkillOrigin, SkillStatus

if TYPE_CHECKING:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
else:
    try:
        import psycopg
        from psycopg.rows import dict_row
        from psycopg.types.json import Jsonb
    except ImportError:
        psycopg = None  # type: ignore[assignment]
        dict_row = None  # type: ignore[assignment]
        Jsonb = None  # type: ignore[assignment]
        warnings.warn(
            "psycopg not installed. PostgresSkillStore requires PostgreSQL support. "
            "Install with: pip install 'psycopg[binary]'",
            ImportWarning,
            stacklevel=2,
        )


def _now() -> datetime:
    return datetime.now(UTC)


def _row_to_skill(row: dict) -> Skill:
    return Skill(
        id=row["id"],
        agent_id=row["agent_id"],
        entity_id=row["entity_id"],
        name=row["name"],
        description=row.get("description", "") or "",
        version=row["version"],
        kind=SkillKind(row["kind"]),
        status=SkillStatus(row["status"]),
        origin=SkillOrigin(row["origin"]),
        core=row["core"],
        session_scoped=row["session_scoped"],
        user_pinned=row["user_pinned"],
        auto_pinned=row["auto_pinned"],
        invocations_count=row["invocations_count"],
        success_count=row["success_count"],
        failure_count=row["failure_count"],
        last_used_at=row.get("last_used_at"),
        sessions_since_use=row["sessions_since_use"],
        revision_needed=row["revision_needed"],
        revision_priority=row["revision_priority"],
        last_revised_at=row.get("last_revised_at"),
        manifest_inferred=row["manifest_inferred"],
        skill_root=Path(row["skill_root"]),
        manifest_path=Path(row["manifest_path"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _row_to_invocation(row: dict) -> SkillInvocation:
    def _load_list(val: Any) -> list[str]:
        if isinstance(val, list):
            return val
        if isinstance(val, str):
            return json.loads(val)
        return []

    return SkillInvocation(
        id=row["id"],
        skill_id=row["skill_id"],
        agent_id=row["agent_id"],
        session_id=row["session_id"],
        started_at=row["started_at"],
        ended_at=row.get("ended_at"),
        preliminary_status=row.get("preliminary_status"),
        final_status=row.get("final_status"),
        agent_marker=row.get("agent_marker"),
        agent_marker_note=row.get("agent_marker_note"),
        user_feedback_hints=_load_list(row.get("user_feedback_hints", [])),
        behavioral_hints=_load_list(row.get("behavioral_hints", [])),
        exit_code=row.get("exit_code"),
        input_context_summary=row.get("input_context_summary"),
        output_summary=row.get("output_summary"),
        processed_at=row.get("processed_at"),
    )


class PostgresSkillStore:
    """PostgreSQL-backed skill store, bound to a single ``agent_id``.

    Every query runs on a connection where ``atman.current_agent`` is set to
    the bound agent, satisfying the ``FORCE ROW LEVEL SECURITY`` policies on
    ``public.skills`` and ``public.skill_invocations``.
    """

    def __init__(self, db_url: str, agent_id: UUID | None = None) -> None:
        if psycopg is None:
            raise RuntimeError("psycopg not installed; cannot use PostgresSkillStore")
        self._db_url = db_url
        # When agent_id is None the store can only execute lookups by name/id
        # that supply their own agent_id; write methods that depend on the
        # bound agent will raise. We keep agent_id optional only to preserve
        # legacy construction sites; new callers should always pass it.
        self._bound_agent_id = agent_id

    # ── Connection management ─────────────────────────────────────────────────

    def _agent_for(self, agent_id: UUID | None) -> UUID:
        """Resolve the agent for a query: explicit > bound. Raises if neither."""
        if agent_id is not None:
            if self._bound_agent_id is not None and agent_id != self._bound_agent_id:
                raise ValueError(
                    f"PostgresSkillStore is bound to agent {self._bound_agent_id}, "
                    f"but query passed agent {agent_id}"
                )
            return agent_id
        if self._bound_agent_id is None:
            raise RuntimeError(
                "PostgresSkillStore method requires an agent_id but the store "
                "was not bound at construction. Pass agent_id=... to __init__."
            )
        return self._bound_agent_id

    @contextmanager
    def _conn(self, agent_id: UUID | None = None) -> Generator[Any, None, None]:
        """Open a connection with the RLS session variable set for the agent.

        All read/write queries on ``public.skills`` and ``public.skill_invocations``
        MUST go through this context manager. Using a raw ``psycopg.connect`` will
        return 0 rows / silently no-op due to ``FORCE ROW LEVEL SECURITY``.
        """
        scoped_agent = self._agent_for(agent_id)
        with psycopg.connect(self._db_url, row_factory=cast(Any, dict_row)) as conn:
            conn.execute(
                "SELECT set_config('atman.current_agent', %s, true)",
                [str(scoped_agent)],
            )
            yield conn

    def _resolve_agent_for_skill(self, skill_id: UUID) -> UUID:
        """Return the agent that owns a skill, using the bound agent for RLS.

        When the store is bound to a single agent (production path), this is a
        cheap lookup. When the store is bound to None and an unknown ``skill_id``
        comes in, we have no way to access the row under RLS, so we raise.
        """
        if self._bound_agent_id is None:
            raise RuntimeError(
                "PostgresSkillStore: skill-id-only operations require the store "
                "to be bound to an agent. Pass agent_id=... to __init__."
            )
        return self._bound_agent_id

    # ── Skill CRUD ────────────────────────────────────────────────────────────

    def save_skill(self, skill: Skill) -> None:
        with self._conn(skill.agent_id) as conn:
            conn.execute(
                """
                INSERT INTO public.skills (
                    id, agent_id, entity_id, name, description, version,
                    kind, status, origin,
                    core, session_scoped, user_pinned, auto_pinned,
                    invocations_count, success_count, failure_count,
                    last_used_at, sessions_since_use,
                    revision_needed, revision_priority, last_revised_at,
                    manifest_inferred, skill_root, manifest_path,
                    created_at, updated_at
                ) VALUES (
                    %(id)s, %(agent_id)s, %(entity_id)s, %(name)s, %(description)s,
                    %(version)s, %(kind)s, %(status)s, %(origin)s,
                    %(core)s, %(session_scoped)s, %(user_pinned)s, %(auto_pinned)s,
                    %(invocations_count)s, %(success_count)s, %(failure_count)s,
                    %(last_used_at)s, %(sessions_since_use)s,
                    %(revision_needed)s, %(revision_priority)s, %(last_revised_at)s,
                    %(manifest_inferred)s, %(skill_root)s, %(manifest_path)s,
                    %(created_at)s, %(updated_at)s
                )
                ON CONFLICT (agent_id, name) DO UPDATE SET
                    description = EXCLUDED.description,
                    version = EXCLUDED.version,
                    kind = EXCLUDED.kind,
                    status = EXCLUDED.status,
                    origin = EXCLUDED.origin,
                    core = EXCLUDED.core,
                    session_scoped = EXCLUDED.session_scoped,
                    user_pinned = EXCLUDED.user_pinned,
                    auto_pinned = EXCLUDED.auto_pinned,
                    invocations_count = EXCLUDED.invocations_count,
                    success_count = EXCLUDED.success_count,
                    failure_count = EXCLUDED.failure_count,
                    last_used_at = EXCLUDED.last_used_at,
                    sessions_since_use = EXCLUDED.sessions_since_use,
                    revision_needed = EXCLUDED.revision_needed,
                    revision_priority = EXCLUDED.revision_priority,
                    last_revised_at = EXCLUDED.last_revised_at,
                    manifest_inferred = EXCLUDED.manifest_inferred,
                    skill_root = EXCLUDED.skill_root,
                    manifest_path = EXCLUDED.manifest_path,
                    updated_at = EXCLUDED.updated_at
                """,
                {
                    "id": skill.id,
                    "agent_id": skill.agent_id,
                    "entity_id": skill.entity_id,
                    "name": skill.name,
                    "description": skill.description,
                    "version": skill.version,
                    "kind": skill.kind.value,
                    "status": skill.status.value,
                    "origin": skill.origin.value,
                    "core": skill.core,
                    "session_scoped": skill.session_scoped,
                    "user_pinned": skill.user_pinned,
                    "auto_pinned": skill.auto_pinned,
                    "invocations_count": skill.invocations_count,
                    "success_count": skill.success_count,
                    "failure_count": skill.failure_count,
                    "last_used_at": skill.last_used_at,
                    "sessions_since_use": skill.sessions_since_use,
                    "revision_needed": skill.revision_needed,
                    "revision_priority": skill.revision_priority,
                    "last_revised_at": skill.last_revised_at,
                    "manifest_inferred": skill.manifest_inferred,
                    "skill_root": str(skill.skill_root),
                    "manifest_path": str(skill.manifest_path),
                    "created_at": skill.created_at,
                    "updated_at": skill.updated_at,
                },
            )

    def get_skill_by_name(self, agent_id: UUID, name: str) -> Skill | None:
        with self._conn(agent_id) as conn:
            row = conn.execute(
                "SELECT * FROM public.skills WHERE agent_id = %s AND name = %s",
                [agent_id, name],
            ).fetchone()
        return _row_to_skill(row) if row else None

    def get_skill_by_id(self, skill_id: UUID) -> Skill | None:
        agent_id = self._resolve_agent_for_skill(skill_id)
        with self._conn(agent_id) as conn:
            row = conn.execute(
                "SELECT * FROM public.skills WHERE id = %s",
                [skill_id],
            ).fetchone()
        return _row_to_skill(cast(Any, row)) if row else None

    def list_pinned(self, agent_id: UUID) -> list[Skill]:
        with self._conn(agent_id) as conn:
            rows = conn.execute(
                """
                SELECT * FROM public.skills
                WHERE agent_id = %s AND status = 'active'
                  AND (user_pinned = true OR auto_pinned = true)
                ORDER BY name
                """,
                [agent_id],
            ).fetchall()
        return [_row_to_skill(r) for r in rows]

    def list_by_status(self, agent_id: UUID, status: SkillStatus) -> list[Skill]:
        with self._conn(agent_id) as conn:
            rows = conn.execute(
                "SELECT * FROM public.skills WHERE agent_id = %s AND status = %s ORDER BY name",
                [agent_id, status.value],
            ).fetchall()
        return [_row_to_skill(r) for r in rows]

    def list_active_on_demand(self, agent_id: UUID) -> list[Skill]:
        with self._conn(agent_id) as conn:
            rows = conn.execute(
                """
                SELECT * FROM public.skills
                WHERE agent_id = %s AND status = 'active'
                  AND user_pinned = false AND auto_pinned = false
                ORDER BY name
                """,
                [agent_id],
            ).fetchall()
        return [_row_to_skill(r) for r in rows]

    def update_skill_status(self, skill_id: UUID, status: SkillStatus) -> None:
        agent_id = self._resolve_agent_for_skill(skill_id)
        with self._conn(agent_id) as conn:
            conn.execute(
                "UPDATE public.skills SET status = %s, updated_at = %s WHERE id = %s",
                [status.value, _now(), skill_id],
            )

    def update_pinning(
        self,
        skill_id: UUID,
        *,
        auto_pinned: bool | None = None,
        user_pinned: bool | None = None,
    ) -> None:
        parts = []
        params: list[Any] = []
        if auto_pinned is not None:
            parts.append("auto_pinned = %s")
            params.append(auto_pinned)
        if user_pinned is not None:
            parts.append("user_pinned = %s")
            params.append(user_pinned)
        if not parts:
            return
        parts.append("updated_at = %s")
        params.append(_now())
        params.append(skill_id)
        agent_id = self._resolve_agent_for_skill(skill_id)
        with self._conn(agent_id) as conn:
            conn.execute(
                f"UPDATE public.skills SET {', '.join(parts)} WHERE id = %s",  # nosec B608
                params,
            )

    def update_stats(
        self,
        skill_id: UUID,
        *,
        success_delta: int = 0,
        failure_delta: int = 0,
        last_used_at: datetime | None = None,
    ) -> None:
        agent_id = self._resolve_agent_for_skill(skill_id)
        with self._conn(agent_id) as conn:
            conn.execute(
                """
                UPDATE public.skills SET
                    success_count = success_count + %s,
                    failure_count = failure_count + %s,
                    last_used_at = COALESCE(%s, last_used_at),
                    updated_at = %s
                WHERE id = %s
                """,
                [success_delta, failure_delta, last_used_at, _now(), skill_id],
            )

    def bump_sessions_since_use(self, agent_id: UUID, exclude_skill_ids: set[UUID]) -> None:
        with self._conn(agent_id) as conn:
            if exclude_skill_ids:
                conn.execute(
                    """
                    UPDATE public.skills SET
                        sessions_since_use = sessions_since_use + 1,
                        updated_at = %s
                    WHERE agent_id = %s
                      AND (user_pinned = true OR auto_pinned = true)
                      AND id != ALL(%s)
                    """,
                    [_now(), agent_id, list(exclude_skill_ids)],
                )
            else:
                conn.execute(
                    """
                    UPDATE public.skills SET
                        sessions_since_use = sessions_since_use + 1,
                        updated_at = %s
                    WHERE agent_id = %s
                      AND (user_pinned = true OR auto_pinned = true)
                    """,
                    [_now(), agent_id],
                )

    def set_revision_needed(self, skill_id: UUID, priority_bump: int = 1) -> None:
        agent_id = self._resolve_agent_for_skill(skill_id)
        with self._conn(agent_id) as conn:
            conn.execute(
                """
                UPDATE public.skills SET
                    revision_needed = true,
                    revision_priority = revision_priority + %s,
                    updated_at = %s
                WHERE id = %s
                """,
                [priority_bump, _now(), skill_id],
            )

    def reset_sessions_since_use(self, skill_id: UUID) -> None:
        agent_id = self._resolve_agent_for_skill(skill_id)
        with self._conn(agent_id) as conn:
            conn.execute(
                "UPDATE public.skills SET sessions_since_use = 0, updated_at = %s WHERE id = %s",
                [_now(), skill_id],
            )

    # ── Invocation log ────────────────────────────────────────────────────────

    def create_invocation(
        self,
        skill_id: UUID,
        agent_id: UUID,
        session_id: UUID,
        input_context_summary: str | None = None,
    ) -> UUID:
        inv_id = uuid4()
        now = _now()
        with self._conn(agent_id) as conn:
            conn.execute(
                """
                INSERT INTO public.skill_invocations
                    (id, skill_id, agent_id, session_id, started_at,
                     preliminary_status, input_context_summary)
                VALUES (%s, %s, %s, %s, %s, 'executing', %s)
                """,
                [inv_id, skill_id, agent_id, session_id, now, input_context_summary],
            )
            conn.execute(
                """
                UPDATE public.skills SET
                    invocations_count = invocations_count + 1,
                    sessions_since_use = 0,
                    last_used_at = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                [now, now, skill_id],
            )
        return inv_id

    def set_preliminary_status(
        self,
        invocation_id: UUID,
        status: str,
        exit_code: int | None = None,
        output_summary: str | None = None,
    ) -> None:
        # invocation operations always run in the bound agent's RLS scope
        with self._conn() as conn:
            conn.execute(
                """
                UPDATE public.skill_invocations SET
                    preliminary_status = %s,
                    exit_code = %s,
                    output_summary = %s,
                    ended_at = %s
                WHERE id = %s
                """,
                [status, exit_code, output_summary, _now(), invocation_id],
            )

    def write_agent_marker(self, invocation_id: UUID, marker: str, note: str | None) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE public.skill_invocations SET agent_marker = %s, agent_marker_note = %s WHERE id = %s",
                [marker, note, invocation_id],
            )

    def append_behavioral_hint(self, invocation_id: UUID, hint: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE public.skill_invocations SET behavioral_hints = behavioral_hints || %s WHERE id = %s",
                [Jsonb([hint]), invocation_id],
            )

    def append_user_feedback_hint(self, invocation_id: UUID, hint: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE public.skill_invocations SET user_feedback_hints = user_feedback_hints || %s WHERE id = %s",
                [Jsonb([hint]), invocation_id],
            )

    def get_unprocessed_invocations(
        self, agent_id: UUID, session_id: UUID
    ) -> list[SkillInvocation]:
        with self._conn(agent_id) as conn:
            rows = conn.execute(
                """
                SELECT * FROM public.skill_invocations
                WHERE agent_id = %s AND session_id = %s AND processed_at IS NULL
                ORDER BY started_at
                """,
                [agent_id, session_id],
            ).fetchall()
        return [_row_to_invocation(cast(Any, r)) for r in rows]

    def set_final_status(self, invocation_id: UUID, final_status: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE public.skill_invocations SET final_status = %s WHERE id = %s",
                [final_status, invocation_id],
            )

    def mark_processed(self, invocation_id: UUID) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE public.skill_invocations SET processed_at = %s WHERE id = %s",
                [_now(), invocation_id],
            )
