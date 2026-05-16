"""
PostgreSQL adapter for EntityStanceStore.

Implements the EntityStanceStore port using psycopg3, persisting stances
in the per-agent schema ``agent_<serial_id>.entity_stance`` table.

Supersession-chain semantics mirror :class:`InMemoryEntityStanceStore`:
writing a new stance for ``(agent_id, entity_id)`` automatically marks
the existing active stance as superseded inside a single transaction.

The schema is looked up either from a provided ``serial_id`` or by
resolving the agent's UUID via ``public.agents.serial_id``.
"""

import os
import warnings
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

if TYPE_CHECKING:
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row
else:
    try:
        import psycopg
        from psycopg import sql
        from psycopg.rows import dict_row
    except ImportError:
        psycopg = None
        sql = None  # type: ignore[assignment]
        dict_row = None  # type: ignore[assignment]
        warnings.warn(
            "psycopg not installed. PostgresEntityStanceStore requires PostgreSQL support. "
            "Install with: pip install 'psycopg[binary]'",
            ImportWarning,
            stacklevel=2,
        )

from atman.core.models.entity import EntityStance
from atman.core.ports.entity_stance import EntityStanceStore


def _row_to_stance(row: Any) -> EntityStance:
    """Build an EntityStance from a psycopg dict row."""
    based_on = row.get("based_on_moment_ids") or []
    return EntityStance(
        id=row["id"],
        agent_id=row["agent_id"],
        entity_id=row["entity_id"],
        stance_text=row["stance_text"],
        valence=row["valence"],
        intensity=row["intensity"],
        formed_at=row["formed_at"],
        formed_in_reflection_id=row["formed_in_reflection_id"],
        based_on_moment_ids=list(based_on),
        superseded_at=row["superseded_at"],
        superseded_by=row["superseded_by"],
        confidence=row["confidence"],
        is_provisional=row["is_provisional"],
    )


class PostgresEntityStanceStore(EntityStanceStore):
    """
    PostgreSQL implementation of EntityStanceStore.

    Stances live in per-agent schemas: ``agent_<serial_id>.entity_stance``.
    The serial_id is resolved once per agent from ``public.agents`` and
    cached, or can be supplied directly via ``serial_id`` to avoid the
    lookup.

    Reads database URL from (in order):
      1. ``db_url`` constructor argument
      2. ``ATMAN_DB_URL`` environment variable
      3. ``DATABASE_URL`` environment variable
      4. ``postgresql://atman@localhost:5432/atman`` (default)

    Example::

        with PostgresEntityStanceStore(db_url=..., serial_id=1) as store:
            stance = store.write_stance(agent_id, entity_id, "trusts deeply",
                                        valence=0.8, intensity=0.6)
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

    def _get_conn(self) -> "psycopg.Connection[Any]":
        """Get or create database connection."""
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(self._db_url, row_factory=dict_row)  # type: ignore[arg-type]
        return self._conn

    def close(self) -> None:
        """Close database connection."""
        if self._conn is not None and not self._conn.closed:
            self._conn.close()

    def __enter__(self) -> "PostgresEntityStanceStore":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Schema resolution
    # ------------------------------------------------------------------

    def _resolve_serial_id(self, agent_id: UUID) -> int:
        """Resolve serial_id for agent_id, with caching."""
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

    def _schema_ident(self, agent_id: UUID) -> "sql.Identifier":
        """Return a psycopg sql.Identifier for the agent's schema."""
        serial_id = self._resolve_serial_id(agent_id)
        return sql.Identifier(f"agent_{serial_id}")

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def get_current_stance(self, agent_id: UUID, entity_id: UUID) -> EntityStance | None:
        """Return the active (not superseded) stance, or None."""
        schema = self._schema_ident(agent_id)
        query = sql.SQL(
            """
            SELECT id, agent_id, entity_id, stance_text, valence, intensity,
                   formed_at, formed_in_reflection_id, based_on_moment_ids,
                   superseded_at, superseded_by, confidence, is_provisional
            FROM {schema}.entity_stance
            WHERE agent_id = %(agent_id)s
              AND entity_id = %(entity_id)s
              AND superseded_at IS NULL
            LIMIT 1
            """
        ).format(schema=schema)

        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(query, {"agent_id": agent_id, "entity_id": entity_id})
            row = cur.fetchone()
        if row is None:
            return None
        return _row_to_stance(row)

    def get_stance_history(self, agent_id: UUID, entity_id: UUID) -> list[EntityStance]:
        """Return all stances for entity, newest first."""
        schema = self._schema_ident(agent_id)
        query = sql.SQL(
            """
            SELECT id, agent_id, entity_id, stance_text, valence, intensity,
                   formed_at, formed_in_reflection_id, based_on_moment_ids,
                   superseded_at, superseded_by, confidence, is_provisional
            FROM {schema}.entity_stance
            WHERE agent_id = %(agent_id)s
              AND entity_id = %(entity_id)s
            ORDER BY formed_at DESC
            """
        ).format(schema=schema)

        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(query, {"agent_id": agent_id, "entity_id": entity_id})
            rows = cur.fetchall()
        return [_row_to_stance(r) for r in rows]

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def write_stance(
        self,
        agent_id: UUID,
        entity_id: UUID,
        stance_text: str,
        *,
        valence: float | None = None,
        intensity: float | None = None,
        formed_in_reflection_id: UUID | None = None,
        based_on_moment_ids: list[UUID] | None = None,
        confidence: float | None = None,
        is_provisional: bool = True,
    ) -> EntityStance:
        """Create new stance, superseding any existing active stance."""
        schema = self._schema_ident(agent_id)
        new_id = uuid4()
        moment_ids: list[UUID] = list(based_on_moment_ids or [])

        supersede_sql = sql.SQL(
            """
            UPDATE {schema}.entity_stance
               SET superseded_at = NOW(),
                   superseded_by = %(new_id)s
             WHERE agent_id = %(agent_id)s
               AND entity_id = %(entity_id)s
               AND superseded_at IS NULL
            """
        ).format(schema=schema)

        insert_sql = sql.SQL(
            """
            INSERT INTO {schema}.entity_stance (
                id, agent_id, entity_id, stance_text, valence, intensity,
                formed_in_reflection_id, based_on_moment_ids,
                confidence, is_provisional
            )
            VALUES (
                %(id)s, %(agent_id)s, %(entity_id)s, %(stance_text)s,
                %(valence)s, %(intensity)s,
                %(formed_in_reflection_id)s, %(based_on_moment_ids)s,
                %(confidence)s, %(is_provisional)s
            )
            RETURNING id, agent_id, entity_id, stance_text, valence, intensity,
                      formed_at, formed_in_reflection_id, based_on_moment_ids,
                      superseded_at, superseded_by, confidence, is_provisional
            """
        ).format(schema=schema)

        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(
                supersede_sql,
                {"new_id": new_id, "agent_id": agent_id, "entity_id": entity_id},
            )
            cur.execute(
                insert_sql,
                {
                    "id": new_id,
                    "agent_id": agent_id,
                    "entity_id": entity_id,
                    "stance_text": stance_text,
                    "valence": valence,
                    "intensity": intensity,
                    "formed_in_reflection_id": formed_in_reflection_id,
                    "based_on_moment_ids": moment_ids,
                    "confidence": confidence,
                    "is_provisional": is_provisional,
                },
            )
            row = cur.fetchone()
        if row is None:
            raise RuntimeError("INSERT INTO entity_stance returned no row")
        return _row_to_stance(row)

    def supersede_stance(self, stance_id: UUID, *, superseded_by_id: UUID) -> None:
        """Mark a stance as superseded. Silent no-op if not found."""
        # We don't know which agent's schema the stance lives in, so search
        # every known per-agent schema. To keep the call site cheap, we look
        # up the schema list once via information_schema.
        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """
                SELECT schema_name
                FROM information_schema.schemata
                WHERE schema_name LIKE 'agent_%'
                """
            )
            schemas = [r["schema_name"] for r in cur.fetchall()]

            for schema_name in schemas:
                query = sql.SQL(
                    """
                    UPDATE {schema}.entity_stance
                       SET superseded_at = NOW(),
                           superseded_by = %(superseded_by_id)s
                     WHERE id = %(stance_id)s
                    """
                ).format(schema=sql.Identifier(schema_name))
                cur.execute(
                    query,
                    {"stance_id": stance_id, "superseded_by_id": superseded_by_id},
                )
                if cur.rowcount > 0:
                    return

    def list_active_stances(
        self,
        agent_id: UUID,
        *,
        formed_after: datetime | None = None,
        limit: int = 50,
    ) -> list[EntityStance]:
        """List all active stances for the agent, newest first."""
        schema = self._schema_ident(agent_id)
        if formed_after is not None:
            query = sql.SQL(
                """
                SELECT id, agent_id, entity_id, stance_text, valence, intensity,
                       formed_at, formed_in_reflection_id, based_on_moment_ids,
                       superseded_at, superseded_by, confidence, is_provisional
                FROM {schema}.entity_stance
                WHERE agent_id = %(agent_id)s
                  AND superseded_at IS NULL
                  AND formed_at > %(formed_after)s
                ORDER BY formed_at DESC
                LIMIT %(limit)s
                """
            ).format(schema=schema)
        else:
            query = sql.SQL(
                """
                SELECT id, agent_id, entity_id, stance_text, valence, intensity,
                       formed_at, formed_in_reflection_id, based_on_moment_ids,
                       superseded_at, superseded_by, confidence, is_provisional
                FROM {schema}.entity_stance
                WHERE agent_id = %(agent_id)s
                  AND superseded_at IS NULL
                ORDER BY formed_at DESC
                LIMIT %(limit)s
                """
            ).format(schema=schema)

        params: dict[str, Any] = {"agent_id": agent_id, "limit": limit}
        if formed_after is not None:
            params["formed_after"] = formed_after

        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return [_row_to_stance(r) for r in rows]
