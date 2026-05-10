"""
PostgreSQL-based storage for reflection content.

This module provides persistent storage for reflections using PostgreSQL.
Requires psycopg2 and a configured database connection.
"""

import os
import warnings
from datetime import datetime
from typing import Any
from uuid import UUID

try:
    import psycopg
    from psycopg import sql
    from psycopg.rows import class_row
except ImportError:
    psycopg = None  # type: ignore[assignment]
    warnings.warn(
        "psycopg not installed. ReflectionStore requires PostgreSQL support. "
        "Install with: pip install psycopg[binary]",
        ImportWarning,
        stacklevel=2,
    )

from atman.reflection.models import ReflectionEvent, ReflectionLevel


class ReflectionStore:
    """
    PostgreSQL-based storage for reflection content.

    Reads database configuration from environment:
    - ATMAN_DB_URL (default: postgresql://atman@localhost:5432/atman)
    - ATMAN_CURRENT_AGENT (required for RLS policy)

    Example:
        with ReflectionStore() as store:
            event = ReflectionEvent(
                agent_id=agent_uuid,
                level=ReflectionLevel.DAILY,
                content="I noticed a pattern...",
                model_provider="ollama",
                model_name="qwen3:14b",
            )
            stored = store.add(event)
    """

    def __init__(self, db_url: str | None = None) -> None:
        """
        Initialize ReflectionStore with database connection.

        Args:
            db_url: PostgreSQL connection URL. If None, reads from ATMAN_DB_URL env var.

        Raises:
            ImportError: If psycopg is not installed
            ValueError: If db_url is not provided and ATMAN_DB_URL is not set
        """
        if psycopg is None:
            raise ImportError(
                "psycopg is required for ReflectionStore. "
                "Install with: pip install psycopg[binary]"
            )

        self.db_url = db_url or os.environ.get(
            "ATMAN_DB_URL", "postgresql://atman@localhost:5432/atman"
        )
        self._conn: psycopg.Connection[Any] | None = None
        self._closed = False

    def connect(self) -> None:
        """Establish database connection."""
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(self.db_url)

    def close(self) -> None:
        """Close database connection."""
        if self._conn is not None and not self._conn.closed:
            self._conn.close()
        self._closed = True

    def __enter__(self) -> "ReflectionStore":
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        """Context manager exit."""
        self.close()

    def __del__(self) -> None:
        """Destructor to warn about unclosed connection."""
        if hasattr(self, "_closed") and not self._closed:
            warnings.warn(
                "ReflectionStore was not closed properly. "
                "Use 'with ReflectionStore() as store:' or call close() explicitly.",
                ResourceWarning,
                stacklevel=2,
            )

    def _get_agent_context(self) -> str | None:
        """Get current agent ID from environment for RLS policy."""
        return os.environ.get("ATMAN_CURRENT_AGENT")

    def add(self, event: ReflectionEvent) -> ReflectionEvent:
        """
        Add a reflection event to storage.

        Args:
            event: ReflectionEvent to store

        Returns:
            ReflectionEvent with assigned ID

        Raises:
            RuntimeError: If database connection is not established
        """
        if self._conn is None or self._conn.closed:
            raise RuntimeError("Database connection not established. Call connect() first.")

        agent_id = self._get_agent_context()
        if agent_id:
            self._conn.execute(
                sql.SQL("SET LOCAL atman.current_agent = %s"),
                [agent_id],
            )

        query = sql.SQL("""
            INSERT INTO public.reflections (
                agent_id, level, created_at, session_id, period_start, period_end,
                content, summary, experience_refs, reframing_note_ids,
                model_provider, model_name, schema_version, metadata
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """)

        with self._conn.cursor() as cur:
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
                    event.metadata,
                ],
            )
            result = cur.fetchone()
            if result:
                event.id = result[0]

        self._conn.commit()
        return event

    def get(self, reflection_id: int) -> ReflectionEvent | None:
        """
        Get a reflection by ID.

        Args:
            reflection_id: Primary key ID

        Returns:
            ReflectionEvent if found, None otherwise
        """
        if self._conn is None or self._conn.closed:
            raise RuntimeError("Database connection not established. Call connect() first.")

        agent_id = self._get_agent_context()
        if agent_id:
            self._conn.execute(
                sql.SQL("SET LOCAL atman.current_agent = %s"),
                [agent_id],
            )

        query = sql.SQL("""
            SELECT id, agent_id, level, created_at, session_id, period_start, period_end,
                   content, summary, experience_refs, reframing_note_ids,
                   model_provider, model_name, schema_version, metadata
            FROM public.reflections
            WHERE id = %s
        """)

        with self._conn.cursor(row_factory=class_row(ReflectionEvent)) as cur:
            cur.execute(query, [reflection_id])
            return cur.fetchone()

    def list_by_session(self, session_id: UUID) -> list[ReflectionEvent]:
        """
        List all reflections for a specific session.

        Args:
            session_id: Session UUID

        Returns:
            List of ReflectionEvent objects
        """
        if self._conn is None or self._conn.closed:
            raise RuntimeError("Database connection not established. Call connect() first.")

        agent_id = self._get_agent_context()
        if agent_id:
            self._conn.execute(
                sql.SQL("SET LOCAL atman.current_agent = %s"),
                [agent_id],
            )

        query = sql.SQL("""
            SELECT id, agent_id, level, created_at, session_id, period_start, period_end,
                   content, summary, experience_refs, reframing_note_ids,
                   model_provider, model_name, schema_version, metadata
            FROM public.reflections
            WHERE session_id = %s
            ORDER BY created_at DESC
        """)

        with self._conn.cursor(row_factory=class_row(ReflectionEvent)) as cur:
            cur.execute(query, [str(session_id)])
            return cur.fetchall()

    def list_recent(self, agent_id: UUID, limit: int = 10) -> list[ReflectionEvent]:
        """
        List recent reflections for an agent.

        Args:
            agent_id: Agent UUID
            limit: Maximum number of reflections to return

        Returns:
            List of ReflectionEvent objects, most recent first
        """
        if self._conn is None or self._conn.closed:
            raise RuntimeError("Database connection not established. Call connect() first.")

        context_agent_id = self._get_agent_context()
        if context_agent_id:
            self._conn.execute(
                sql.SQL("SET LOCAL atman.current_agent = %s"),
                [context_agent_id],
            )

        query = sql.SQL("""
            SELECT id, agent_id, level, created_at, session_id, period_start, period_end,
                   content, summary, experience_refs, reframing_note_ids,
                   model_provider, model_name, schema_version, metadata
            FROM public.reflections
            WHERE agent_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        """)

        with self._conn.cursor(row_factory=class_row(ReflectionEvent)) as cur:
            cur.execute(query, [str(agent_id), limit])
            return cur.fetchall()

    def list_by_level(
        self, agent_id: UUID, level: ReflectionLevel, since: datetime | None = None
    ) -> list[ReflectionEvent]:
        """
        List reflections for an agent at a specific level.

        Args:
            agent_id: Agent UUID
            level: Reflection level to filter by
            since: Optional start time filter

        Returns:
            List of ReflectionEvent objects
        """
        if self._conn is None or self._conn.closed:
            raise RuntimeError("Database connection not established. Call connect() first.")

        context_agent_id = self._get_agent_context()
        if context_agent_id:
            self._conn.execute(
                sql.SQL("SET LOCAL atman.current_agent = %s"),
                [context_agent_id],
            )

        if since:
            query = sql.SQL("""
                SELECT id, agent_id, level, created_at, session_id, period_start, period_end,
                       content, summary, experience_refs, reframing_note_ids,
                       model_provider, model_name, schema_version, metadata
                FROM public.reflections
                WHERE agent_id = %s AND level = %s AND created_at >= %s
                ORDER BY created_at DESC
            """)
            params = [str(agent_id), level.value, since]
        else:
            query = sql.SQL("""
                SELECT id, agent_id, level, created_at, session_id, period_start, period_end,
                       content, summary, experience_refs, reframing_note_ids,
                       model_provider, model_name, schema_version, metadata
                FROM public.reflections
                WHERE agent_id = %s AND level = %s
                ORDER BY created_at DESC
            """)
            params = [str(agent_id), level.value]

        with self._conn.cursor(row_factory=class_row(ReflectionEvent)) as cur:
            cur.execute(query, params)
            return cur.fetchall()