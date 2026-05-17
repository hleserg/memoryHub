"""PostgreSQL adapter for StateStore — v2 (per-agent schemas).

Implements the v2 storage surface introduced by migration 0008:
    - ``agent_N.sessions`` — canonical session rows
    - ``agent_N.key_moments`` — standalone key moments with ``session_id`` FK
    - Session API: create_session / get_session / update_session / list_recent_sessions
    - v2 KeyMoment API: store_key_moment (idempotent upsert), mark_moment_accessed,
      update_moment_structured_markers, find_moments_by_entity

Pre-v2 ``public.key_moments`` is GONE (migration 0008 DROPs it), so the old
adapter that targeted it is replaced wholesale. Identity / Narrative /
Eigenstate operations remain :meth:`NotImplementedError` — those still live
on ``FileStateStore`` for the file deployment path, and Reflection's
identity-snapshot writes still go through that adapter.

Schema is per-agent: each agent owns ``agent_<serial_id>.*`` tables; the
adapter resolves ``serial_id`` once per ``agent_id`` from ``public.agents``
and caches the mapping.
"""

from __future__ import annotations

import os
import warnings
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row
    from psycopg.types.json import Jsonb
else:
    try:
        import psycopg
        from psycopg import sql
        from psycopg.rows import dict_row
        from psycopg.types.json import Jsonb
    except ImportError:
        psycopg = None
        sql = None  # type: ignore[assignment]
        dict_row = None  # type: ignore[assignment]
        Jsonb = None
        warnings.warn(
            "psycopg not installed. PostgresStateStore requires PostgreSQL support. "
            "Install with: pip install 'psycopg[binary]'",
            ImportWarning,
            stacklevel=2,
        )

from atman.core.models import (
    Eigenstate,
    ExperienceRecord,
    Identity,
    IdentitySnapshot,
    KeyMoment,
    NarrativeDocument,
    ReframingNote,
)
from atman.core.models.session import Session
from atman.core.ports.state_store import ExperienceQuery, StateStore


def _row_to_session(row: Any) -> Session:
    return Session(
        id=row["id"],
        agent_id=row["agent_id"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        status=row["status"],
        identity_snapshot_id=row["identity_snapshot_id"],
        close_reason=row["close_reason"],
        agent_recap=row["agent_recap"],
        restart_reason=row["restart_reason"] or "",
        user_language=row["user_language"] or "ru",
        overall_tone=row["overall_tone"],
        key_insight=row["key_insight"],
        unexamined_fact_refs=list(row["unexamined_fact_refs"] or []),
    )


def _row_to_key_moment(row: Any) -> KeyMoment:
    """Build a KeyMoment from a v2 agent_N.key_moments row.

    Note: the DB column ``embedding`` (halfvec(1024)) is intentionally NOT
    propagated into the in-memory KeyMoment model — the domain model treats
    embeddings as a search-side concern owned by the embedding adapter. The
    DB row may carry an embedding for vector search; reads here drop it.
    """
    from atman.core.models.experience import EmotionalDepth, FeltSense

    return KeyMoment(
        id=row["id"],
        session_id=row["session_id"],
        what_happened=row["what_happened"],
        how_i_felt=FeltSense(
            emotional_valence=row["emotional_valence"],
            emotional_intensity=row["emotional_intensity"],
            depth=EmotionalDepth(row["depth"]),
        ),
        why_it_matters=row["why_it_matters"] or "",
        values_touched=list(row["values_touched"] or []),
        principles_confirmed=list(row["principles_confirmed"] or []),
        principles_questioned=list(row["principles_questioned"] or []),
        what_changed=row["what_changed"] or "",
        when=row["recorded_at"],
        salience=float(row["salience"]),
        salience_at=row["salience_at"],
        last_accessed_at=row["last_accessed_at"],
        access_count=int(row["access_count"]),
        incomplete_coloring=bool(row["incomplete_coloring"]),
        recorded_by=row["recorded_by"] or "session_manager",
        identity_snapshot_id=row["identity_snapshot_id"],
        importance=float(row["importance"]),
        fact_refs=list(row["fact_refs"] or []),
        structured_markers=row["structured_markers"],
        structured_markers_version=row["structured_markers_version"],
    )


class PostgresStateStore(StateStore):
    """PostgreSQL implementation of StateStore — v2 per-agent schemas.

    Reads database URL from (in order):
      1. ``db_url`` constructor argument
      2. ``ATMAN_DB_URL`` environment variable
      3. ``DATABASE_URL`` environment variable
      4. ``postgresql://atman@localhost:5432/atman`` (default)

    Schema resolution:
      - Pass ``serial_id`` directly to skip the public.agents lookup.
      - Otherwise the adapter resolves ``serial_id`` per ``agent_id`` on
        first use and caches the mapping for the lifetime of the instance.

    Operations implemented:
      - Session: create / get / update / list_recent
      - KeyMoment: create, get, list (by session or all), store (upsert),
        mark_moment_accessed, update_moment_structured_markers, store_key_moments
        (legacy plural for backward compat with the InMemory contract)

    NOT implemented (raise ``NotImplementedError``):
      - Experience operations (the v1 ``ExperienceRecord`` model — use
        :class:`ExperienceViewRepository` or follow Этап 18 migration)
      - Identity / Narrative / Eigenstate (still served by FileStateStore
        in the file-deployment path; deferred for this adapter)
    """

    def __init__(
        self,
        db_url: str | None = None,
        *,
        serial_id: int | None = None,
    ) -> None:
        if psycopg is None:
            raise ImportError("psycopg not installed. Install with: pip install 'psycopg[binary]'")

        self._db_url = (
            db_url
            or os.environ.get("ATMAN_DB_URL")
            or os.environ.get("DATABASE_URL")
            or "postgresql://atman@localhost:5432/atman"
        )
        self._conn: psycopg.Connection[Any] | None = None
        self._fixed_serial_id: int | None = serial_id
        self._serial_cache: dict[UUID, int] = {}

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _get_conn(self) -> psycopg.Connection[Any]:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(self._db_url, row_factory=dict_row)  # type: ignore[arg-type]
        return self._conn

    def close(self) -> None:
        if self._conn is not None and not self._conn.closed:
            self._conn.close()

    def __enter__(self) -> PostgresStateStore:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Schema resolution
    # ------------------------------------------------------------------

    def _resolve_serial_id(self, agent_id: UUID) -> int:
        if self._fixed_serial_id is not None:
            return self._fixed_serial_id
        cached = self._serial_cache.get(agent_id)
        if cached is not None:
            return cached
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT serial_id FROM public.agents WHERE id = %(agent_id)s",
                {"agent_id": agent_id},
            )
            row = cur.fetchone()
        if row is None:
            raise LookupError(f"Agent {agent_id} not found in public.agents")
        serial_id = int(row["serial_id"])
        self._serial_cache[agent_id] = serial_id
        return serial_id

    def _schema_ident(self, agent_id: UUID) -> sql.Identifier:
        return sql.Identifier(f"agent_{self._resolve_serial_id(agent_id)}")

    def _list_agent_schemas(self, cur: Any) -> list[str]:
        """Return per-agent schema names (agent_<serial_id>), excluding stray matches."""
        cur.execute(
            """
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name ~ '^agent_[0-9]+$'
            """
        )
        return [r["schema_name"] for r in cur.fetchall()]

    def _resolve_schema_for_session(self, session_id: UUID) -> sql.Identifier | None:
        """Locate the agent schema that owns a given session_id.

        For multi-agent registries — scans agent_% schemas until a hit.
        Single-agent deployments construct with a fixed ``serial_id`` and
        skip this scan.
        """
        if self._fixed_serial_id is not None:
            return sql.Identifier(f"agent_{self._fixed_serial_id}")
        conn = self._get_conn()
        with conn.cursor() as cur:
            for schema_name in self._list_agent_schemas(cur):
                q = sql.SQL("SELECT 1 FROM {s}.sessions WHERE id = %(sid)s").format(
                    s=sql.Identifier(schema_name)
                )
                # Swallow UndefinedTable: some agent_% schemas (backup,
                # archive, test fixtures, or partially-migrated agents)
                # may not have the v2 sessions table yet — skip them rather
                # than aborting the whole scan.
                try:
                    cur.execute(q, {"sid": session_id})
                except psycopg.errors.UndefinedTable:
                    conn.rollback()
                    continue
                if cur.fetchone() is not None:
                    return sql.Identifier(schema_name)
        return None

    def _resolve_schema_for_moment(self, moment_id: UUID) -> sql.Identifier | None:
        """Same idea as `_resolve_schema_for_session` but for key_moments rows."""
        if self._fixed_serial_id is not None:
            return sql.Identifier(f"agent_{self._fixed_serial_id}")
        conn = self._get_conn()
        with conn.cursor() as cur:
            for schema_name in self._list_agent_schemas(cur):
                q = sql.SQL("SELECT 1 FROM {s}.key_moments WHERE id = %(mid)s").format(
                    s=sql.Identifier(schema_name)
                )
                # See _resolve_schema_for_session for rationale.
                try:
                    cur.execute(q, {"mid": moment_id})
                except psycopg.errors.UndefinedTable:
                    conn.rollback()
                    continue
                if cur.fetchone() is not None:
                    return sql.Identifier(schema_name)
        return None

    # ------------------------------------------------------------------
    # Session operations (v2)
    # ------------------------------------------------------------------

    def create_session(self, session: Session) -> Session:
        schema = self._schema_ident(session.agent_id)
        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            q = sql.SQL(
                """
                INSERT INTO {s}.sessions (
                    id, agent_id, started_at, ended_at, status, identity_snapshot_id,
                    close_reason, agent_recap, restart_reason, user_language,
                    overall_tone, key_insight, unexamined_fact_refs
                ) VALUES (
                    %(id)s, %(agent_id)s, %(started_at)s, %(ended_at)s, %(status)s,
                    %(identity_snapshot_id)s, %(close_reason)s, %(agent_recap)s,
                    %(restart_reason)s, %(user_language)s, %(overall_tone)s,
                    %(key_insight)s, %(unexamined_fact_refs)s
                )
                """
            ).format(s=schema)
            cur.execute(
                q,
                {
                    "id": session.id,
                    "agent_id": session.agent_id,
                    "started_at": session.started_at,
                    "ended_at": session.ended_at,
                    "status": session.status,
                    "identity_snapshot_id": session.identity_snapshot_id,
                    "close_reason": session.close_reason,
                    "agent_recap": session.agent_recap,
                    "restart_reason": session.restart_reason,
                    "user_language": session.user_language,
                    "overall_tone": session.overall_tone,
                    "key_insight": session.key_insight,
                    "unexamined_fact_refs": list(session.unexamined_fact_refs),
                },
            )
        return session

    def get_session(self, session_id: UUID) -> Session | None:
        schema = self._resolve_schema_for_session(session_id)
        if schema is None:
            return None
        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            q = sql.SQL(
                """
                SELECT id, agent_id, started_at, ended_at, status, identity_snapshot_id,
                       close_reason, agent_recap, restart_reason, user_language,
                       overall_tone, key_insight, unexamined_fact_refs
                FROM {s}.sessions WHERE id = %(sid)s
                """
            ).format(s=schema)
            cur.execute(q, {"sid": session_id})
            row = cur.fetchone()
        return _row_to_session(row) if row else None

    def update_session(self, session: Session) -> Session:
        schema = self._schema_ident(session.agent_id)
        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            q = sql.SQL(
                """
                UPDATE {s}.sessions
                SET ended_at = %(ended_at)s,
                    status = %(status)s,
                    identity_snapshot_id = %(identity_snapshot_id)s,
                    close_reason = %(close_reason)s,
                    agent_recap = %(agent_recap)s,
                    restart_reason = %(restart_reason)s,
                    user_language = %(user_language)s,
                    overall_tone = %(overall_tone)s,
                    key_insight = %(key_insight)s,
                    unexamined_fact_refs = %(unexamined_fact_refs)s
                WHERE id = %(id)s
                """
            ).format(s=schema)
            cur.execute(
                q,
                {
                    "id": session.id,
                    "ended_at": session.ended_at,
                    "status": session.status,
                    "identity_snapshot_id": session.identity_snapshot_id,
                    "close_reason": session.close_reason,
                    "agent_recap": session.agent_recap,
                    "restart_reason": session.restart_reason,
                    "user_language": session.user_language,
                    "overall_tone": session.overall_tone,
                    "key_insight": session.key_insight,
                    "unexamined_fact_refs": list(session.unexamined_fact_refs),
                },
            )
        return session

    def list_recent_sessions(self, agent_id: UUID, *, limit: int = 10) -> list[Session]:
        schema = self._schema_ident(agent_id)
        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            q = sql.SQL(
                """
                SELECT id, agent_id, started_at, ended_at, status, identity_snapshot_id,
                       close_reason, agent_recap, restart_reason, user_language,
                       overall_tone, key_insight, unexamined_fact_refs
                FROM {s}.sessions
                WHERE agent_id = %(aid)s
                ORDER BY started_at DESC
                LIMIT %(lim)s
                """
            ).format(s=schema)
            cur.execute(q, {"aid": agent_id, "lim": limit})
            rows = cur.fetchall()
        return [_row_to_session(r) for r in rows]

    def list_sessions_in_range(
        self,
        agent_id: UUID,
        start: datetime,
        end: datetime,
    ) -> list[Session]:
        """HLE-59: native ranged SQL query using the ``started_at`` index.

        Overrides the port default so high-volume agents don't fall through
        to ``list_recent_sessions(limit=10_000_000)``, which would
        materialise the full session table and sort it. Inclusive on both
        bounds to match the in-memory / file adapters and the prior
        ``StateStoreSessionRepository.get_sessions_in_range`` semantics.
        Postgres ``timestamptz`` columns return UTC-aware datetimes, so the
        ``ensure_utc`` normalisation the in-memory / file paths need is
        redundant here.
        """
        schema = self._schema_ident(agent_id)
        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            q = sql.SQL(
                """
                SELECT id, agent_id, started_at, ended_at, status, identity_snapshot_id,
                       close_reason, agent_recap, restart_reason, user_language,
                       overall_tone, key_insight, unexamined_fact_refs
                FROM {s}.sessions
                WHERE agent_id = %(aid)s
                  AND started_at BETWEEN %(start)s AND %(end)s
                ORDER BY started_at DESC
                """
            ).format(s=schema)
            cur.execute(q, {"aid": agent_id, "start": start, "end": end})
            rows = cur.fetchall()
        return [_row_to_session(r) for r in rows]

    # ------------------------------------------------------------------
    # KeyMoment operations (v2 — agent_N.key_moments)
    # ------------------------------------------------------------------

    def _insert_moment_rows(
        self,
        cur: Any,
        schema: sql.Identifier,
        moment: KeyMoment,
        agent_id: UUID,
        on_conflict_upsert: bool = False,
    ) -> None:
        """INSERT a key moment row inside the caller's transaction."""
        params = {
            "id": moment.id,
            "session_id": moment.session_id,
            "agent_id": agent_id,
            "what_happened": moment.what_happened,
            "emotional_valence": moment.how_i_felt.emotional_valence,
            "emotional_intensity": moment.how_i_felt.emotional_intensity,
            "depth": moment.how_i_felt.depth.value,
            "why_it_matters": moment.why_it_matters,
            "values_touched": list(moment.values_touched),
            "principles_confirmed": list(moment.principles_confirmed),
            "principles_questioned": list(moment.principles_questioned),
            "what_changed": moment.what_changed,
            "recorded_at": moment.when,
            "salience": moment.salience,
            "salience_at": moment.salience_at,
            "last_accessed_at": moment.last_accessed_at,
            "access_count": moment.access_count,
            "incomplete_coloring": moment.incomplete_coloring,
            "recorded_by": moment.recorded_by,
            "identity_snapshot_id": moment.identity_snapshot_id,
            "importance": moment.importance,
            "fact_refs": list(moment.fact_refs),
            "structured_markers": (
                Jsonb(moment.structured_markers) if moment.structured_markers else None
            ),
            "structured_markers_version": moment.structured_markers_version,
        }
        conflict_clause = (
            "ON CONFLICT (id) DO UPDATE SET "
            "salience = EXCLUDED.salience, salience_at = EXCLUDED.salience_at, "
            "last_accessed_at = EXCLUDED.last_accessed_at, "
            "access_count = EXCLUDED.access_count, "
            "structured_markers = EXCLUDED.structured_markers, "
            "structured_markers_version = EXCLUDED.structured_markers_version"
            if on_conflict_upsert
            else ""
        )
        q = sql.SQL(
            """
            INSERT INTO {s}.key_moments (
                id, session_id, agent_id, what_happened,
                emotional_valence, emotional_intensity, depth, why_it_matters,
                values_touched, principles_confirmed, principles_questioned,
                what_changed, recorded_at, salience, salience_at,
                last_accessed_at, access_count, incomplete_coloring,
                recorded_by, identity_snapshot_id, importance, fact_refs,
                structured_markers, structured_markers_version
            ) VALUES (
                %(id)s, %(session_id)s, %(agent_id)s, %(what_happened)s,
                %(emotional_valence)s, %(emotional_intensity)s, %(depth)s,
                %(why_it_matters)s, %(values_touched)s, %(principles_confirmed)s,
                %(principles_questioned)s, %(what_changed)s, %(recorded_at)s,
                %(salience)s, %(salience_at)s, %(last_accessed_at)s, %(access_count)s,
                %(incomplete_coloring)s, %(recorded_by)s, %(identity_snapshot_id)s,
                %(importance)s, %(fact_refs)s, %(structured_markers)s,
                %(structured_markers_version)s
            )
            """  # nosec B608
            + conflict_clause
        ).format(s=schema)
        cur.execute(q, params)

    def create_key_moment(self, key_moment: KeyMoment) -> KeyMoment:
        """Create a new key moment. Raises ValueError on duplicate id."""
        if key_moment.session_id is None:
            raise ValueError(
                f"PostgresStateStore.create_key_moment: KeyMoment {key_moment.id} "
                f"is missing session_id (required by v2 schema)."
            )
        # Resolve agent from the moment's session — sessions table is the
        # only place that links session_id → agent_id authoritatively.
        existing = self.get_session(key_moment.session_id)
        if existing is None:
            raise ValueError(
                f"PostgresStateStore.create_key_moment: session {key_moment.session_id} not found"
            )
        schema = self._schema_ident(existing.agent_id)
        conn = self._get_conn()
        try:
            with conn.transaction(), conn.cursor() as cur:
                self._insert_moment_rows(
                    cur, schema, key_moment, existing.agent_id, on_conflict_upsert=False
                )
        except psycopg.errors.UniqueViolation as exc:
            raise ValueError(f"KeyMoment {key_moment.id} already exists") from exc
        return key_moment

    def store_key_moment(self, moment: KeyMoment) -> KeyMoment:
        """Idempotent upsert — replaces existing record or inserts new (v2 API)."""
        if moment.session_id is None:
            raise ValueError(
                f"PostgresStateStore.store_key_moment: KeyMoment {moment.id} "
                f"is missing session_id (required by v2 schema)."
            )
        existing = self.get_session(moment.session_id)
        if existing is None:
            raise ValueError(
                f"PostgresStateStore.store_key_moment: session {moment.session_id} not found"
            )
        schema = self._schema_ident(existing.agent_id)
        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            self._insert_moment_rows(
                cur, schema, moment, existing.agent_id, on_conflict_upsert=True
            )
        return moment

    def store_key_moments(self, session_id: UUID, moments: list[KeyMoment]) -> None:
        """Store multiple key moments for a session (idempotent upsert each)."""
        for m in moments:
            if m.session_id is None:
                m.session_id = session_id
            self.store_key_moment(m)

    def get_key_moment(self, moment_id: UUID) -> KeyMoment | None:
        schema = self._resolve_schema_for_moment(moment_id)
        if schema is None:
            return None
        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            q = sql.SQL("SELECT * FROM {s}.key_moments WHERE id = %(mid)s").format(s=schema)
            cur.execute(q, {"mid": moment_id})
            row = cur.fetchone()
        return _row_to_key_moment(row) if row else None

    def list_key_moments(self, session_id: UUID | None = None) -> list[KeyMoment]:
        if session_id is None:
            # Without a session filter, single-agent registries can list all
            # moments in their schema; multi-agent registries cannot know
            # which schema to scan without a probe — return empty rather
            # than scanning every agent.
            if self._fixed_serial_id is None:
                return []
            schema = sql.Identifier(f"agent_{self._fixed_serial_id}")
            conn = self._get_conn()
            with conn.transaction(), conn.cursor() as cur:
                q = sql.SQL("SELECT * FROM {s}.key_moments ORDER BY recorded_at ASC").format(
                    s=schema
                )
                cur.execute(q)
                rows = cur.fetchall()
            return [_row_to_key_moment(r) for r in rows]
        return self.get_key_moments_for_session(session_id)

    def get_key_moments_for_session(self, session_id: UUID) -> list[KeyMoment]:
        schema = self._resolve_schema_for_session(session_id)
        if schema is None:
            return []
        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            q = sql.SQL(
                "SELECT * FROM {s}.key_moments WHERE session_id = %(sid)s ORDER BY recorded_at ASC"
            ).format(s=schema)
            cur.execute(q, {"sid": session_id})
            rows = cur.fetchall()
        return [_row_to_key_moment(r) for r in rows]

    def mark_moment_accessed(self, moment_id: UUID) -> None:
        schema = self._resolve_schema_for_moment(moment_id)
        if schema is None:
            return
        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            q = sql.SQL(
                """
                UPDATE {s}.key_moments
                SET last_accessed_at = NOW(),
                    access_count = access_count + 1
                WHERE id = %(mid)s
                """
            ).format(s=schema)
            cur.execute(q, {"mid": moment_id})

    def update_moment_structured_markers(
        self, moment_id: UUID, markers: dict, version: str
    ) -> None:
        schema = self._resolve_schema_for_moment(moment_id)
        if schema is None:
            return
        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            q = sql.SQL(
                """
                UPDATE {s}.key_moments
                SET structured_markers = %(markers)s,
                    structured_markers_version = %(version)s
                WHERE id = %(mid)s
                """
            ).format(s=schema)
            cur.execute(q, {"markers": Jsonb(markers), "version": version, "mid": moment_id})

    def find_moments_by_entity(self, entity_id: UUID, *, limit: int = 20) -> list[KeyMoment]:
        """Find key moments linked to an entity via agent_N.key_moment_entities.

        Requires the registry to be bound to a fixed serial_id (single-agent
        deployments) — for multi-agent registries the caller must use the
        appropriate per-agent instance.
        """
        if self._fixed_serial_id is None:
            return []
        schema = sql.Identifier(f"agent_{self._fixed_serial_id}")
        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            q = sql.SQL(
                """
                SELECT km.*
                FROM {s}.key_moments km
                JOIN {s}.key_moment_entities kme
                  ON kme.key_moment_id = km.id
                WHERE kme.entity_id = %(eid)s
                ORDER BY km.recorded_at DESC
                LIMIT %(lim)s
                """
            ).format(s=schema)
            cur.execute(q, {"eid": entity_id, "lim": limit})
            rows = cur.fetchall()
        return [_row_to_key_moment(r) for r in rows]

    # ------------------------------------------------------------------
    # Not implemented — served by FileStateStore today (Identity/Narrative/Eigenstate)
    # ------------------------------------------------------------------

    def create_experience(self, record: ExperienceRecord) -> ExperienceRecord:
        raise NotImplementedError(
            "Experience operations are not implemented in PostgresStateStore v2. "
            "Use SessionRepository (Этап 18) or the legacy FileStateStore for "
            "ExperienceRecord-based flows."
        )

    def get_experience(self, experience_id: UUID) -> ExperienceRecord | None:
        raise NotImplementedError("Experience operations not implemented in PostgresStateStore")

    def add_reframing_note(
        self, experience_id: UUID, note: ReframingNote
    ) -> ExperienceRecord | None:
        raise NotImplementedError("Experience operations not implemented in PostgresStateStore")

    def mark_accessed(self, experience_id: UUID) -> ExperienceRecord | None:
        raise NotImplementedError("Experience operations not implemented in PostgresStateStore")

    def search_experiences(
        self, query: ExperienceQuery | None = None, limit: int = 10
    ) -> list[ExperienceRecord]:
        raise NotImplementedError("Experience operations not implemented in PostgresStateStore")

    def list_recent_experiences(self, limit: int = 10) -> list[ExperienceRecord]:
        raise NotImplementedError("Experience operations not implemented in PostgresStateStore")

    def load_identity(self, agent_id: UUID) -> Identity | None:
        raise NotImplementedError("Identity operations not implemented in PostgresStateStore")

    def save_identity(self, identity: Identity, expected_version: str | None = None) -> Identity:
        raise NotImplementedError("Identity operations not implemented in PostgresStateStore")

    def create_identity_snapshot(self, snapshot: IdentitySnapshot) -> IdentitySnapshot:
        raise NotImplementedError("Identity operations not implemented in PostgresStateStore")

    def list_identity_snapshots(self, identity_id: UUID, limit: int = 10) -> list[IdentitySnapshot]:
        raise NotImplementedError("Identity operations not implemented in PostgresStateStore")

    def load_narrative(self, identity_id: UUID) -> NarrativeDocument | None:
        raise NotImplementedError("Narrative operations not implemented in PostgresStateStore")

    def save_narrative(
        self,
        narrative: NarrativeDocument,
        expected_version: str | None = None,
        expected_updated_at: datetime | None = None,
    ) -> NarrativeDocument:
        raise NotImplementedError("Narrative operations not implemented in PostgresStateStore")

    def archive_narrative(self, narrative_id: UUID, reason: str) -> None:
        raise NotImplementedError("Narrative operations not implemented in PostgresStateStore")

    def list_archived_narratives(
        self, identity_id: UUID, limit: int = 10
    ) -> list[tuple[NarrativeDocument, str, datetime]]:
        raise NotImplementedError("Narrative operations not implemented in PostgresStateStore")

    def save_eigenstate(self, eigenstate: Eigenstate) -> Eigenstate:
        raise NotImplementedError("Eigenstate operations not implemented in PostgresStateStore")

    def load_latest_eigenstate(
        self,
        session_id: UUID | None = None,
        identity_id: UUID | None = None,
    ) -> Eigenstate | None:
        raise NotImplementedError("Eigenstate operations not implemented in PostgresStateStore")
