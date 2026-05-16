"""
PostgreSQL-based storage for reflection content.

Reflections live in per-agent schemas ``agent_{serial_id}.reflections`` (not public).
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
    from psycopg.rows import class_row
    from psycopg.types.json import Jsonb
else:
    try:
        import psycopg
        from psycopg import sql
        from psycopg.rows import class_row
        from psycopg.types.json import Jsonb
    except ImportError:
        psycopg = None
        sql = None
        class_row = None
        Jsonb = None
        warnings.warn(
            "psycopg not installed. ReflectionStore requires PostgreSQL support. "
            "Install with: pip install psycopg[binary]",
            ImportWarning,
            stacklevel=2,
        )

from atman.adapters.storage.postgres_agent_schema import AgentSchemaResolver
from atman.reflection.models import ReflectionEvent, ReflectionLevel

_REFLECTION_COLUMNS = """
    id, agent_id, level, created_at, session_id, period_start, period_end,
    content, summary, experience_refs, reframing_note_ids,
    model_provider, model_name, schema_version, metadata
"""


class ReflectionStore:
    """
    PostgreSQL storage for reflection content in ``agent_{N}.reflections``.

    Reads database configuration from environment:
    - ATMAN_DB_URL (default: postgresql://atman@localhost:5432/atman)
    - ATMAN_CURRENT_AGENT (optional UUID string; used when agent_id is not passed)
    """

    def __init__(
        self,
        db_url: str | None = None,
        *,
        fixed_serial_id: int | None = None,
    ) -> None:
        if psycopg is None:
            raise ImportError(
                "psycopg is required for ReflectionStore. Install with: pip install psycopg[binary]"
            )

        self.db_url = db_url or os.environ.get(
            "ATMAN_DB_URL", "postgresql://atman@localhost:5432/atman"
        )
        self._conn: psycopg.Connection[Any] | None = None
        self._closed = False
        self._schema_resolver = AgentSchemaResolver(fixed_serial_id=fixed_serial_id)

    def connect(self) -> None:
        """Establish database connection."""
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(self.db_url)

    def close(self) -> None:
        """Close database connection."""
        if self._conn is not None and not self._conn.closed:
            self._conn.close()
        self._closed = True

    def __enter__(self) -> ReflectionStore:
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        self.close()

    def __del__(self) -> None:
        if hasattr(self, "_closed") and not self._closed:
            warnings.warn(
                "ReflectionStore was not closed properly. "
                "Use 'with ReflectionStore() as store:' or call close() explicitly.",
                ResourceWarning,
                stacklevel=2,
            )

    def _require_conn(self) -> psycopg.Connection[Any]:
        if self._conn is None or self._conn.closed:
            raise RuntimeError("Database connection not established. Call connect() first.")
        return self._conn

    def _agent_uuid_from_env(self) -> UUID | None:
        raw = os.environ.get("ATMAN_CURRENT_AGENT")
        if not raw:
            return None
        return UUID(raw)

    def _schema_for_agent(self, agent_id: UUID) -> Any:
        conn = self._require_conn()
        return self._schema_resolver.schema_ident_for_connection(conn, agent_id)

    def _resolve_schema_for_session(self, session_id: UUID) -> Any | None:
        conn = self._require_conn()
        fixed = self._schema_resolver.fixed_schema_ident()
        if fixed is not None:
            return fixed
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT schema_name
                FROM information_schema.schemata
                WHERE schema_name ~ '^agent_[0-9]+$'
                """
            )
            for row in cur.fetchall():
                schema_name = row[0]
                q = sql.SQL("SELECT 1 FROM {s}.sessions WHERE id = %s").format(
                    s=sql.Identifier(schema_name)
                )
                try:
                    cur.execute(q, [session_id])
                except psycopg.errors.UndefinedTable:
                    conn.rollback()
                    continue
                if cur.fetchone() is not None:
                    return sql.Identifier(schema_name)
        return None

    def add(self, event: ReflectionEvent) -> ReflectionEvent:
        conn = self._require_conn()
        schema = self._schema_for_agent(event.agent_id)
        query = sql.SQL(
            """
            INSERT INTO {schema}.reflections (
                agent_id, level, created_at, session_id, period_start, period_end,
                content, summary, experience_refs, reframing_note_ids,
                model_provider, model_name, schema_version, metadata
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """
        ).format(schema=schema)

        with conn.cursor() as cur:
            cur.execute(
                query,
                [
                    str(event.agent_id),
                    event.level.value,
                    event.created_at,
                    str(event.session_id) if event.session_id else None,
                    event.period_start,
                    event.period_end,
                    event.content,
                    event.summary,
                    event.experience_refs,
                    event.reframing_note_ids,
                    event.model_provider,
                    event.model_name,
                    event.schema_version,
                    Jsonb(event.metadata),
                ],
            )
            result = cur.fetchone()
            if result:
                event.id = result[0]

        conn.commit()
        return event

    def get(self, reflection_id: int, *, agent_id: UUID | None = None) -> ReflectionEvent | None:
        """Load by id from ``agent_{N}.reflections``; pass ``agent_id`` or set ``ATMAN_CURRENT_AGENT``."""
        conn = self._require_conn()
        resolved_agent = agent_id or self._agent_uuid_from_env()
        if resolved_agent is None:
            raise ValueError("agent_id is required for get() when ATMAN_CURRENT_AGENT is unset")
        schema = self._schema_for_agent(resolved_agent)
        query = sql.SQL("SELECT {cols} FROM {schema}.reflections WHERE id = %s").format(
            cols=sql.SQL(_REFLECTION_COLUMNS), schema=schema
        )

        with conn.cursor(row_factory=class_row(ReflectionEvent)) as cur:
            cur.execute(query, [reflection_id])
            row = cur.fetchone()
        conn.commit()
        return row

    def list_by_session(
        self, session_id: UUID, *, agent_id: UUID | None = None
    ) -> list[ReflectionEvent]:
        """List reflections for a session; pass ``agent_id`` to skip cross-schema scan."""
        conn = self._require_conn()
        if agent_id is not None:
            schema = self._schema_for_agent(agent_id)
        else:
            schema = self._resolve_schema_for_session(session_id)
        if schema is None:
            conn.commit()
            return []

        query = sql.SQL(
            """
            SELECT {cols}
            FROM {schema}.reflections
            WHERE session_id = %s
            ORDER BY created_at DESC
            """
        ).format(cols=sql.SQL(_REFLECTION_COLUMNS), schema=schema)

        with conn.cursor(row_factory=class_row(ReflectionEvent)) as cur:
            cur.execute(query, [str(session_id)])
            rows = cur.fetchall()
        conn.commit()
        return rows

    def list_recent(self, agent_id: UUID, limit: int = 10) -> list[ReflectionEvent]:
        conn = self._require_conn()
        schema = self._schema_for_agent(agent_id)
        query = sql.SQL(
            """
            SELECT {cols}
            FROM {schema}.reflections
            WHERE agent_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """
        ).format(cols=sql.SQL(_REFLECTION_COLUMNS), schema=schema)

        with conn.cursor(row_factory=class_row(ReflectionEvent)) as cur:
            cur.execute(query, [str(agent_id), limit])
            rows = cur.fetchall()
        conn.commit()
        return rows

    def list_by_level(
        self, agent_id: UUID, level: ReflectionLevel, since: datetime | None = None
    ) -> list[ReflectionEvent]:
        conn = self._require_conn()
        schema = self._schema_for_agent(agent_id)
        if since:
            query = sql.SQL(
                """
                SELECT {cols}
                FROM {schema}.reflections
                WHERE agent_id = %s AND level = %s AND created_at >= %s
                ORDER BY created_at DESC
                """
            ).format(cols=sql.SQL(_REFLECTION_COLUMNS), schema=schema)
            params: list[Any] = [str(agent_id), level.value, since]
        else:
            query = sql.SQL(
                """
                SELECT {cols}
                FROM {schema}.reflections
                WHERE agent_id = %s AND level = %s
                ORDER BY created_at DESC
                """
            ).format(cols=sql.SQL(_REFLECTION_COLUMNS), schema=schema)
            params = [str(agent_id), level.value]

        with conn.cursor(row_factory=class_row(ReflectionEvent)) as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        conn.commit()
        return rows
