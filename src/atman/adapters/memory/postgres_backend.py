"""
PostgreSQL adapter for Factual Memory.

Implements FactualMemory port using psycopg3 and pgvector.
Supports semantic vector search when an EmbeddingPort is provided;
degrades gracefully to ILIKE text search when the embedding model is
unavailable or raises an error.
"""

import json
import os
import warnings
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

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
        psycopg = None
        dict_row = None  # type: ignore[assignment]
        Jsonb = None
        warnings.warn(
            "psycopg not installed. PostgresFactualMemory requires PostgreSQL support. "
            "Install with: pip install 'psycopg[binary]'",
            ImportWarning,
            stacklevel=2,
        )

from atman.core.models.fact import FactRecord, FactStatus, Relation
from atman.core.ports import FactualMemory
from atman.core.ports.embedding import EmbeddingPort

_FACT_SELECT = """
    SELECT
        f.id,
        f.agent_id,
        f.content,
        f.source,
        f.tags,
        f.created_at,
        f.metadata,
        f.status,
        f.invalidated_at,
        f.invalidation_note,
        f.superseded_by,
        f.disputed_at,
        f.confirmation_count,
        f.last_confirmed_at,
        f.salience,
        COALESCE(
            json_agg(
                json_build_object(
                    'target_id', r.target_id::text,
                    'relation_type', r.relation_type,
                    'created_at', r.created_at,
                    'metadata', r.metadata
                ) ORDER BY r.created_at
            ) FILTER (WHERE r.source_id IS NOT NULL),
            '[]'::json
        ) AS rels
    FROM public.facts f
    LEFT JOIN public.fact_relations r ON r.source_id = f.id
"""


def _vec_str(vec: list[float]) -> str:
    """Serialize a float list to PostgreSQL vector literal '[x,y,z]'."""
    return "[" + ",".join(repr(v) for v in vec) + "]"


def _parse_fact(row: Any) -> FactRecord:
    """Build a FactRecord from a psycopg row (dict-like via RealDictCursor)."""
    rels_raw = row["rels"]
    if isinstance(rels_raw, str):
        rels_raw = json.loads(rels_raw)

    relations = [
        Relation(
            target_id=UUID(r["target_id"]),
            relation_type=r["relation_type"],
            created_at=r["created_at"],
            metadata=r["metadata"] or {},
        )
        for r in (rels_raw or [])
    ]

    return FactRecord(
        id=row["id"],
        agent_id=row["agent_id"],
        content=row["content"],
        source=row["source"],
        tags=list(row["tags"] or []),
        created_at=row["created_at"],
        metadata=row["metadata"] or {},
        status=FactStatus(row["status"]),
        invalidated_at=row["invalidated_at"],
        invalidation_note=row["invalidation_note"] or "",
        superseded_by=row["superseded_by"],
        disputed_at=row["disputed_at"],
        confirmation_count=row["confirmation_count"],
        last_confirmed_at=row["last_confirmed_at"],
        salience=row["salience"],
        relations=relations,
    )


class PostgresFactualMemory(FactualMemory):
    """
    PostgreSQL implementation of FactualMemory using psycopg3.

    Supports semantic vector search via pgvector when an EmbeddingPort is
    provided. If the embedding model is unavailable or raises an error,
    falls back to ILIKE text search transparently.

    Reads database URL from (in order):
      1. ``db_url`` constructor argument
      2. ``ATMAN_DB_URL`` environment variable
      3. ``DATABASE_URL`` environment variable
      4. ``postgresql://atman@localhost:5432/atman`` (default)

    RLS context is read from ``ATMAN_CURRENT_AGENT`` environment variable
    (same pattern as ReflectionStore).

    Example::

        with PostgresFactualMemory(embedding=OllamaEmbeddingAdapter()) as mem:
            fact = mem.add_fact(FactRecord(
                agent_id=agent_uuid,
                content="User prefers concise answers",
                source="session_2026_05_10",
                tags=["preference", "communication"],
            ))
    """

    def __init__(
        self,
        db_url: str | None = None,
        *,
        embedding: EmbeddingPort | None = None,
    ) -> None:
        if psycopg is None:
            raise ImportError(
                "psycopg is required for PostgresFactualMemory. "
                "Install with: pip install 'psycopg[binary]'"
            )
        self.db_url = (
            db_url
            or os.environ.get("ATMAN_DB_URL")
            or os.environ.get("DATABASE_URL")
            or "postgresql://atman@localhost:5432/atman"
        )
        self._embedding = embedding
        self._conn: psycopg.Connection[Any] | None = None
        self._closed = False

    # ── Connection management ─────────────────────────────────────────────────

    def connect(self) -> None:
        """Open a database connection."""
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(
                self.db_url,
                row_factory=cast(Any, dict_row),
            )

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None and not self._conn.closed:
            self._conn.close()
        self._closed = True

    def __enter__(self) -> "PostgresFactualMemory":
        self.connect()
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def __del__(self) -> None:
        if hasattr(self, "_closed") and not self._closed:
            warnings.warn(
                "PostgresFactualMemory was not closed. "
                "Use 'with PostgresFactualMemory() as mem:' or call close().",
                ResourceWarning,
                stacklevel=2,
            )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _require_conn(self) -> "psycopg.Connection[Any]":
        if self._conn is None or self._conn.closed:
            raise RuntimeError("Database connection not established. Call connect() first.")
        return self._conn

    def _set_agent_context(self, conn: "psycopg.Connection[Any]") -> None:
        """Set RLS session variable if ATMAN_CURRENT_AGENT is configured.

        Uses set_config(..., true) instead of SET LOCAL because PostgreSQL
        does not accept parameterized placeholders in SET commands.
        """
        agent_id = os.environ.get("ATMAN_CURRENT_AGENT")
        if agent_id:
            conn.execute(
                "SELECT set_config('atman.current_agent', %s, true)",
                [agent_id],
            )

    def _try_embed(self, text: str) -> list[float] | None:
        """Try to embed text; return None on any failure (graceful degradation)."""
        if self._embedding is None:
            return None
        try:
            return self._embedding.embed(text)
        except Exception as exc:
            warnings.warn(
                f"Embedding failed ({type(exc).__name__}: {exc}); falling back to text search.",
                RuntimeWarning,
                stacklevel=3,
            )
            return None

    def _load_rows(
        self,
        cur: Any,
        where_sql: str,
        params: list[Any],
        order_sql: str,
        limit: int | None = None,
    ) -> list[FactRecord]:
        """Run SELECT + LEFT JOIN fact_relations and parse results."""
        query = _FACT_SELECT + f" WHERE {where_sql} GROUP BY f.id ORDER BY {order_sql}"
        if limit is not None:
            query += " LIMIT %s"
            params = [*list(params), limit]
        cur.execute(query, params)
        return [_parse_fact(row) for row in cur.fetchall()]

    def _insert_relation(
        self,
        cur: Any,
        source_id: UUID,
        target_id: UUID,
        relation_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        cur.execute(
            """
            INSERT INTO public.fact_relations
                (source_id, target_id, relation_type, metadata)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            [str(source_id), str(target_id), relation_type, Jsonb(metadata or {})],
        )

    # ── FactualMemory port ────────────────────────────────────────────────────

    def add_fact(self, record: FactRecord) -> FactRecord:
        """Insert a fact and its pre-populated relations into the database."""
        conn = self._require_conn()
        self._set_agent_context(conn)

        agent_id = record.agent_id or UUID(os.environ.get("ATMAN_CURRENT_AGENT", ""))
        embedding_vec = self._try_embed(record.content)
        embedding_sql = _vec_str(embedding_vec) if embedding_vec else None

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO public.facts (
                    id, agent_id, content, source, tags, created_at, metadata,
                    status, invalidated_at, invalidation_note, superseded_by,
                    disputed_at, confirmation_count, last_confirmed_at, salience,
                    embedding
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s::halfvec
                )
                """,
                [
                    str(record.id),
                    str(agent_id),
                    record.content,
                    record.source,
                    list(record.tags),
                    record.created_at,
                    Jsonb(record.metadata),
                    record.status.value,
                    record.invalidated_at,
                    record.invalidation_note,
                    str(record.superseded_by) if record.superseded_by else None,
                    record.disputed_at,
                    record.confirmation_count,
                    record.last_confirmed_at,
                    record.salience,
                    embedding_sql,
                ],
            )
            for rel in record.relations:
                self._insert_relation(
                    cur, record.id, rel.target_id, rel.relation_type, rel.metadata
                )

        conn.commit()
        stored = record.model_copy(deep=True)
        stored.agent_id = agent_id
        return stored

    def get_fact(self, fact_id: UUID) -> FactRecord | None:
        """Retrieve a fact by ID including its relations."""
        conn = self._require_conn()
        self._set_agent_context(conn)

        with conn.cursor() as cur:
            rows = self._load_rows(cur, "f.id = %s", [str(fact_id)], "f.created_at DESC")

        conn.commit()
        return rows[0] if rows else None

    def search(
        self,
        query: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
        *,
        include_invalidated: bool = False,
    ) -> list[FactRecord]:
        """
        Search facts by text query and/or tags.

        Uses vector similarity search when an EmbeddingPort is available and
        the embedding call succeeds. Falls back to ILIKE text search otherwise.
        """
        conn = self._require_conn()
        self._set_agent_context(conn)

        conditions: list[str] = []
        params: list[Any] = []

        if not include_invalidated:
            conditions.append("f.status = 'active'")

        if tags:
            conditions.append("f.tags @> %s::text[]")
            params.append(list(tags))

        # Determine search mode
        vec: list[float] | None = None
        if query:
            vec = self._try_embed(query)

        if query and vec is not None:
            # Vector search — cosine distance, NULLs sort last naturally
            order_sql = f"f.embedding <=> '{_vec_str(vec)}'::halfvec"
        elif query:
            # Text fallback
            conditions.append("f.content ILIKE %s")
            params.append(f"%{query}%")
            order_sql = "f.created_at DESC"
        else:
            order_sql = "f.created_at DESC"

        where_sql = " AND ".join(conditions) if conditions else "TRUE"

        with conn.cursor() as cur:
            rows = self._load_rows(cur, where_sql, params, order_sql, limit)

        conn.commit()
        return rows

    def invalidate_fact(
        self,
        fact_id: UUID,
        *,
        status: FactStatus | None = None,
        note: str = "",
        superseded_by: UUID | None = None,
    ) -> FactRecord | None:
        """Mark a fact as invalidated and optionally link to its replacement."""
        conn = self._require_conn()
        self._set_agent_context(conn)

        new_status = (status or FactStatus.INVALIDATED).value
        now = datetime.now(UTC)

        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE public.facts
                SET status = %s::fact_status,
                    invalidation_note = %s,
                    invalidated_at = %s,
                    superseded_by = %s
                WHERE id = %s
                RETURNING id
                """,
                [
                    new_status,
                    note,
                    now,
                    str(superseded_by) if superseded_by else None,
                    str(fact_id),
                ],
            )
            if cur.fetchone() is None:
                conn.commit()
                return None

            if superseded_by is not None:
                self._insert_relation(cur, fact_id, superseded_by, "superseded_by")
                self._insert_relation(cur, superseded_by, fact_id, "supersedes")

        conn.commit()
        return self.get_fact(fact_id)

    def list_invalidated(self, since: datetime | None = None) -> list[FactRecord]:
        """Return all non-ACTIVE facts, optionally filtered by invalidation time."""
        conn = self._require_conn()
        self._set_agent_context(conn)

        conditions = ["f.status != 'active'"]
        params: list[Any] = []

        if since is not None:
            conditions.append("f.invalidated_at >= %s")
            params.append(since)

        where_sql = " AND ".join(conditions)

        with conn.cursor() as cur:
            rows = self._load_rows(
                cur,
                where_sql,
                params,
                "COALESCE(f.invalidated_at, f.created_at) DESC",
            )

        conn.commit()
        return rows

    def confirm_fact(self, fact_id: UUID) -> bool:
        """Increment confirmation count and raise salience."""
        conn = self._require_conn()
        self._set_agent_context(conn)

        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE public.facts
                SET confirmation_count = confirmation_count + 1,
                    last_confirmed_at  = NOW(),
                    salience           = LEAST(1.0, salience + 0.1)
                WHERE id = %s AND status = 'active'
                RETURNING id
                """,
                [str(fact_id)],
            )
            found = cur.fetchone() is not None

        conn.commit()
        return found

    def decay_stale_facts(self, before: datetime, decay_factor: float = 0.5) -> int:
        """Multiply salience by decay_factor for active facts not confirmed since `before`."""
        conn = self._require_conn()
        self._set_agent_context(conn)

        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE public.facts
                SET salience = GREATEST(0.0, salience * %s)
                WHERE status = 'active'
                  AND (last_confirmed_at IS NULL OR last_confirmed_at < %s)
                """,
                [decay_factor, before],
            )
            count = cur.rowcount

        conn.commit()
        return count

    def link(self, source_id: UUID, target_id: UUID, relation_type: str) -> bool:
        """Create a directed relation between two facts."""
        conn = self._require_conn()
        self._set_agent_context(conn)

        with conn.cursor() as cur:
            # Verify both facts exist (FK will enforce, but we want False not an exception)
            cur.execute(
                "SELECT COUNT(*) FROM public.facts WHERE id = ANY(%s)",
                [[str(source_id), str(target_id)]],
            )
            row = cur.fetchone()
            if row is None or row["count"] < 2:
                conn.commit()
                return False

            self._insert_relation(cur, source_id, target_id, relation_type)

        conn.commit()
        return True

    def list_recent(self, limit: int = 10) -> list[FactRecord]:
        """Return the most recently created facts."""
        conn = self._require_conn()
        self._set_agent_context(conn)

        with conn.cursor() as cur:
            rows = self._load_rows(cur, "TRUE", [], "f.created_at DESC", limit)

        conn.commit()
        return rows

    # ------------------------------------------------------------------
    # Entity-link operations (v2 — agent_N.fact_entities, migration 0007)
    # ------------------------------------------------------------------

    def _agent_schema(self, agent_id: UUID) -> str | None:
        """Return ``agent_<serial_id>`` schema name, or None if not registered."""
        conn = self._require_conn()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT serial_id FROM public.agents WHERE id = %s",
                [str(agent_id)],
            )
            row = cur.fetchone()
        if row is None:
            return None
        if isinstance(row, dict):
            serial_id = row.get("serial_id")
        else:
            serial_id = row[0]
        return f"agent_{serial_id}" if serial_id is not None else None

    def add_fact_with_entities(
        self,
        record: FactRecord,
        entities: list[tuple[UUID, str]],
    ) -> FactRecord:
        """Insert a fact and its entity links in a single transaction."""
        stored = self.add_fact(record)
        if not entities:
            return stored

        agent_id = stored.agent_id
        if agent_id is None:
            return stored
        schema = self._agent_schema(agent_id)
        if schema is None:
            return stored

        conn = self._require_conn()
        with conn.cursor() as cur:
            for entity_id, role in entities:
                cur.execute(
                    f"INSERT INTO {schema}.fact_entities "  # type: ignore[arg-type]
                    "(fact_id, entity_id, agent_id, role) "
                    "VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT (fact_id, entity_id, role) DO NOTHING",
                    [str(stored.id), str(entity_id), str(agent_id), role],
                )
        conn.commit()
        return stored

    def find_facts_by_entity(
        self,
        entity_id: UUID,
        roles: list[str] | None = None,
        *,
        limit: int = 20,
    ) -> list[FactRecord]:
        """Return facts linked to ``entity_id``, optionally filtered by role.

        Requires ``ATMAN_CURRENT_AGENT`` to be set so the per-agent schema
        can be located; returns ``[]`` otherwise.
        """
        agent_id_str = os.environ.get("ATMAN_CURRENT_AGENT")
        if not agent_id_str:
            return []
        schema = self._agent_schema(UUID(agent_id_str))
        if schema is None:
            return []

        conn = self._require_conn()
        self._set_agent_context(conn)

        params: list[Any] = [str(entity_id)]
        role_clause = ""
        if roles:
            role_clause = "AND fe.role = ANY(%s)"
            params.append(list(roles))
        params.append(limit)

        with conn.cursor() as cur:
            fact_ids_sql = (
                f"SELECT fe.fact_id FROM {schema}.fact_entities fe "
                f"WHERE fe.entity_id = %s {role_clause} LIMIT %s"
            )
            cur.execute(fact_ids_sql, params)  # type: ignore[arg-type]
            rows = cur.fetchall()
        fact_ids = [(row["fact_id"] if isinstance(row, dict) else row[0]) for row in rows]
        if not fact_ids:
            return []

        with conn.cursor() as cur:
            facts = self._load_rows(
                cur,
                "f.id = ANY(%s)",
                [fact_ids],
                "f.created_at DESC",
                limit,
            )
        conn.commit()
        return facts
