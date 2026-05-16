"""
PostgreSQL adapter for EntityRegistry.

Implements the EntityRegistry port using psycopg3, persisting entities and
aliases in per-agent schemas (``agent_<serial_id>.entities`` and
``agent_<serial_id>.entity_aliases``).

Resolution semantics mirror :class:`InMemoryEntityRegistry`:
  L1 — exact (case-insensitive) match on canonical_name or known alias.
  L2 — cosine similarity of provided embedding against stored halfvec
       embeddings; succeeds when similarity ≥ 0.85.
  L3 — no match found; a new Entity is inserted.

The schema is looked up either from a provided ``serial_id`` or by
resolving the agent's UUID via ``public.agents.serial_id`` (the lookup is
cached per agent).
"""

from __future__ import annotations

import os
import warnings
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
            "psycopg not installed. PostgresEntityRegistry requires PostgreSQL support. "
            "Install with: pip install 'psycopg[binary]'",
            ImportWarning,
            stacklevel=2,
        )

from atman.core.models.entity import Entity, EntityAlias, EntityType, ResolutionMethod
from atman.core.ports.entity_registry import EntityRegistry

_DEFAULT_EMBEDDING_THRESHOLD = 0.85


def _vec_str(vec: list[float]) -> str:
    """Serialize a float list to PostgreSQL vector literal '[x,y,z]'."""
    return "[" + ",".join(repr(v) for v in vec) + "]"


def _row_to_entity(row: Any) -> Entity:
    """Build an Entity from a psycopg dict row."""
    metadata = row.get("metadata") or {}
    embedding_raw = row.get("embedding")
    embedding: list[float] | None
    if embedding_raw is None:
        embedding = None
    elif isinstance(embedding_raw, list):
        embedding = [float(v) for v in embedding_raw]
    else:
        # halfvec returns as string like '[1.0,2.0,...]'
        text = str(embedding_raw).strip().strip("[]")
        embedding = [float(v) for v in text.split(",")] if text else None

    return Entity(
        id=row["id"],
        agent_id=row["agent_id"],
        canonical_name=row["canonical_name"],
        entity_type=EntityType(row["entity_type"]),
        description=row.get("description"),
        first_seen_at=row["first_seen_at"],
        last_seen_at=row["last_seen_at"],
        mention_count=row["mention_count"],
        needs_disambiguation=row["needs_disambiguation"],
        embedding=embedding,
        schema_version=row.get("schema_version") or "atman-1.0",
        metadata=dict(metadata),
    )


def _row_to_alias(row: Any) -> EntityAlias:
    """Build an EntityAlias from a psycopg dict row."""
    return EntityAlias(
        id=row["id"],
        entity_id=row["entity_id"],
        agent_id=row["agent_id"],
        alias_text=row["alias_text"],
        learned_from_fact_id=row.get("learned_from_fact_id"),
        learned_at=row["learned_at"],
    )


class PostgresEntityRegistry(EntityRegistry):
    """
    PostgreSQL implementation of EntityRegistry.

    Entities live in per-agent schemas: ``agent_<serial_id>.entities`` and
    ``agent_<serial_id>.entity_aliases``. The serial_id is resolved once per
    agent from ``public.agents`` and cached, or can be supplied directly via
    ``serial_id`` to avoid the lookup.

    Reads database URL from (in order):
      1. ``db_url`` constructor argument
      2. ``ATMAN_DB_URL`` environment variable
      3. ``DATABASE_URL`` environment variable
      4. ``postgresql://atman@localhost:5432/atman`` (default)

    Example::

        with PostgresEntityRegistry(db_url=..., serial_id=1) as reg:
            entity, method = reg.resolve_or_create(
                agent_id, "Alice", EntityType.person, alias_text="Al"
            )
    """

    def __init__(
        self,
        db_url: str | None = None,
        *,
        serial_id: int | None = None,
        embedding_threshold: float = _DEFAULT_EMBEDDING_THRESHOLD,
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
        self._embedding_threshold = embedding_threshold

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _get_conn(self) -> psycopg.Connection[Any]:
        """Get or create database connection."""
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(self._db_url, row_factory=dict_row)  # type: ignore[arg-type]
        return self._conn

    def close(self) -> None:
        """Close database connection."""
        if self._conn is not None and not self._conn.closed:
            self._conn.close()

    def __enter__(self) -> PostgresEntityRegistry:
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

    def _schema_ident(self, agent_id: UUID) -> sql.Identifier:
        """Return a psycopg sql.Identifier for the agent's schema."""
        serial_id = self._resolve_serial_id(agent_id)
        return sql.Identifier(f"agent_{serial_id}")

    def _resolve_schema_for_entity(self, entity_id: UUID) -> sql.Identifier | None:
        """Locate the agent schema that owns the given entity_id.

        Searches every ``agent_%`` schema's entities table. Returns the
        sql.Identifier on first hit, or None when the entity does not exist.
        """
        conn = self._get_conn()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT schema_name
                FROM information_schema.schemata
                WHERE schema_name LIKE 'agent_%'
                """
            )
            schemas = [r["schema_name"] for r in cur.fetchall()]

            for schema_name in schemas:
                query = sql.SQL("SELECT 1 FROM {schema}.entities WHERE id = %(entity_id)s").format(
                    schema=sql.Identifier(schema_name)
                )
                cur.execute(query, {"entity_id": entity_id})
                if cur.fetchone() is not None:
                    return sql.Identifier(schema_name)
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _entity_select_sql(schema: sql.Identifier) -> sql.Composed:
        return sql.SQL(
            """
            SELECT id, agent_id, canonical_name, entity_type, description,
                   first_seen_at, last_seen_at, mention_count,
                   needs_disambiguation, embedding, schema_version, metadata
            FROM {schema}.entities
            """
        ).format(schema=schema)

    def _fetch_entity(
        self,
        cur: Any,
        schema: sql.Identifier,
        entity_id: UUID,
    ) -> Entity | None:
        query = sql.SQL("{select} WHERE id = %(entity_id)s").format(
            select=self._entity_select_sql(schema)
        )
        cur.execute(query, {"entity_id": entity_id})
        row = cur.fetchone()
        return _row_to_entity(row) if row is not None else None

    def _find_by_exact(
        self,
        cur: Any,
        schema: sql.Identifier,
        agent_id: UUID,
        name: str,
        entity_type: EntityType | None,
    ) -> Entity | None:
        """L1: case-insensitive match on canonical_name or alias_text."""
        needle = name.strip()
        lowered = needle.lower()

        type_filter = sql.SQL("")
        params: dict[str, Any] = {
            "agent_id": agent_id,
            "needle": needle,
            "lowered": lowered,
        }
        if entity_type is not None:
            type_filter = sql.SQL(" AND e.entity_type = %(entity_type)s")
            params["entity_type"] = entity_type.value

        query = sql.SQL(
            """
            SELECT e.id, e.agent_id, e.canonical_name, e.entity_type,
                   e.description, e.first_seen_at, e.last_seen_at,
                   e.mention_count, e.needs_disambiguation, e.embedding,
                   e.schema_version, e.metadata
            FROM {schema}.entities e
            WHERE e.agent_id = %(agent_id)s
              AND e.canonical_name ILIKE %(needle)s
              {type_filter}
            LIMIT 1
            """
        ).format(schema=schema, type_filter=type_filter)
        cur.execute(query, params)
        row = cur.fetchone()
        if row is not None:
            return _row_to_entity(row)

        alias_query = sql.SQL(
            """
            SELECT e.id, e.agent_id, e.canonical_name, e.entity_type,
                   e.description, e.first_seen_at, e.last_seen_at,
                   e.mention_count, e.needs_disambiguation, e.embedding,
                   e.schema_version, e.metadata
            FROM {schema}.entities e
            JOIN {schema}.entity_aliases a ON a.entity_id = e.id
            WHERE e.agent_id = %(agent_id)s
              AND a.alias_text = %(lowered)s
              {type_filter}
            LIMIT 1
            """
        ).format(schema=schema, type_filter=type_filter)
        cur.execute(alias_query, params)
        row = cur.fetchone()
        return _row_to_entity(row) if row is not None else None

    def _find_by_embedding(
        self,
        cur: Any,
        schema: sql.Identifier,
        agent_id: UUID,
        embedding: list[float],
        entity_type: EntityType | None,
    ) -> Entity | None:
        """L2: nearest neighbour by cosine distance; gated by threshold."""
        vec_literal = _vec_str(embedding)
        type_filter = sql.SQL("")
        params: dict[str, Any] = {"agent_id": agent_id}
        if entity_type is not None:
            type_filter = sql.SQL(" AND entity_type = %(entity_type)s")
            params["entity_type"] = entity_type.value

        # NOTE: halfvec literal is embedded directly because PostgreSQL does
        # not accept parameterised values for halfvec casts in all versions;
        # this mirrors the pattern in postgres_backend.PostgresFactualMemory.
        query = sql.SQL(
            """
            SELECT id, agent_id, canonical_name, entity_type, description,
                   first_seen_at, last_seen_at, mention_count,
                   needs_disambiguation, embedding, schema_version, metadata,
                   (embedding <=> '{vec}'::halfvec) AS distance
            FROM {schema}.entities
            WHERE agent_id = %(agent_id)s
              AND embedding IS NOT NULL
              {type_filter}
            ORDER BY embedding <=> '{vec}'::halfvec
            LIMIT 1
            """
        ).format(
            schema=schema,
            type_filter=type_filter,
            vec=sql.SQL(vec_literal),  # type: ignore[arg-type]
        )
        cur.execute(query, params)
        row = cur.fetchone()
        if row is None:
            return None
        distance = float(row["distance"])
        similarity = 1.0 - distance
        if similarity < self._embedding_threshold:
            return None
        return _row_to_entity(row)

    def _insert_alias(
        self,
        cur: Any,
        schema: sql.Identifier,
        entity_id: UUID,
        agent_id: UUID,
        alias_text: str,
        learned_from_fact_id: UUID | None,
    ) -> EntityAlias:
        """Insert (or fetch existing) alias, returning the persisted row."""
        normalised = alias_text.strip().lower()

        insert_sql = sql.SQL(
            """
            INSERT INTO {schema}.entity_aliases
                (entity_id, agent_id, alias_text, learned_from_fact_id)
            VALUES
                (%(entity_id)s, %(agent_id)s, %(alias_text)s, %(learned_from_fact_id)s)
            ON CONFLICT (entity_id, alias_text) DO NOTHING
            RETURNING id, entity_id, agent_id, alias_text,
                      learned_from_fact_id, learned_at
            """
        ).format(schema=schema)
        cur.execute(
            insert_sql,
            {
                "entity_id": entity_id,
                "agent_id": agent_id,
                "alias_text": normalised,
                "learned_from_fact_id": learned_from_fact_id,
            },
        )
        row = cur.fetchone()
        if row is not None:
            return _row_to_alias(row)

        # Duplicate — fetch the pre-existing alias row.
        select_sql = sql.SQL(
            """
            SELECT id, entity_id, agent_id, alias_text,
                   learned_from_fact_id, learned_at
            FROM {schema}.entity_aliases
            WHERE entity_id = %(entity_id)s AND alias_text = %(alias_text)s
            """
        ).format(schema=schema)
        cur.execute(
            select_sql,
            {"entity_id": entity_id, "alias_text": normalised},
        )
        existing = cur.fetchone()
        if existing is None:  # pragma: no cover — defensive
            raise RuntimeError(
                f"Alias upsert failed and no existing row found for entity {entity_id}"
            )
        return _row_to_alias(existing)

    # ------------------------------------------------------------------
    # EntityRegistry port
    # ------------------------------------------------------------------

    def resolve_or_create(
        self,
        agent_id: UUID,
        canonical_name: str,
        entity_type: EntityType,
        *,
        description: str | None = None,
        embedding: list[float] | None = None,
        alias_text: str | None = None,
        learned_from_fact_id: UUID | None = None,
    ) -> tuple[Entity, ResolutionMethod]:
        schema = self._schema_ident(agent_id)
        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            # L1 — canonical / alias exact match
            candidates = [canonical_name]
            if alias_text:
                candidates.append(alias_text)
            for candidate in candidates:
                hit = self._find_by_exact(cur, schema, agent_id, candidate, entity_type)
                if hit is not None:
                    if alias_text and alias_text.strip().lower() != hit.canonical_name.lower():
                        self._insert_alias(
                            cur,
                            schema,
                            hit.id,
                            hit.agent_id,
                            alias_text,
                            learned_from_fact_id,
                        )
                    return hit, ResolutionMethod.L1_exact

            # L2 — embedding similarity
            if embedding is not None:
                near = self._find_by_embedding(cur, schema, agent_id, embedding, entity_type)
                if near is not None:
                    if alias_text and alias_text.strip().lower() != near.canonical_name.lower():
                        self._insert_alias(
                            cur,
                            schema,
                            near.id,
                            near.agent_id,
                            alias_text,
                            learned_from_fact_id,
                        )
                    return near, ResolutionMethod.L2_embedding

            # L3 — create new entity
            new_entity = Entity(
                agent_id=agent_id,
                canonical_name=canonical_name,
                entity_type=entity_type,
                description=description,
                embedding=embedding,
            )
            embedding_literal = _vec_str(new_entity.embedding) if new_entity.embedding else None

            insert_sql = sql.SQL(
                """
                INSERT INTO {schema}.entities (
                    id, agent_id, canonical_name, entity_type, embedding,
                    description, first_seen_at, last_seen_at, mention_count,
                    needs_disambiguation, schema_version, metadata
                )
                VALUES (
                    %(id)s, %(agent_id)s, %(canonical_name)s, %(entity_type)s,
                    %(embedding)s::halfvec,
                    %(description)s, %(first_seen_at)s, %(last_seen_at)s,
                    %(mention_count)s, %(needs_disambiguation)s,
                    %(schema_version)s, %(metadata)s
                )
                RETURNING id, agent_id, canonical_name, entity_type, description,
                          first_seen_at, last_seen_at, mention_count,
                          needs_disambiguation, embedding, schema_version, metadata
                """
            ).format(schema=schema)
            cur.execute(
                insert_sql,
                {
                    "id": new_entity.id,
                    "agent_id": new_entity.agent_id,
                    "canonical_name": new_entity.canonical_name,
                    "entity_type": new_entity.entity_type.value,
                    "embedding": embedding_literal,
                    "description": new_entity.description,
                    "first_seen_at": new_entity.first_seen_at,
                    "last_seen_at": new_entity.last_seen_at,
                    "mention_count": new_entity.mention_count,
                    "needs_disambiguation": new_entity.needs_disambiguation,
                    "schema_version": new_entity.schema_version,
                    "metadata": Jsonb(new_entity.metadata),
                },
            )
            row = cur.fetchone()
            if row is None:  # pragma: no cover — defensive
                raise RuntimeError("INSERT INTO entities returned no row")
            created = _row_to_entity(row)

            if alias_text and alias_text.strip().lower() != created.canonical_name.strip().lower():
                self._insert_alias(
                    cur,
                    schema,
                    created.id,
                    created.agent_id,
                    alias_text,
                    learned_from_fact_id,
                )

            return created, ResolutionMethod.L3_new

    def get_entity(self, entity_id: UUID) -> Entity | None:
        schema = self._resolve_schema_for_entity(entity_id)
        if schema is None:
            return None
        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            return self._fetch_entity(cur, schema, entity_id)

    def find_by_name(
        self,
        agent_id: UUID,
        name: str,
        entity_type: EntityType | None = None,
    ) -> list[Entity]:
        schema = self._schema_ident(agent_id)
        needle = name.strip()
        lowered = needle.lower()

        type_filter = sql.SQL("")
        params: dict[str, Any] = {
            "agent_id": agent_id,
            "needle": needle,
            "lowered": lowered,
        }
        if entity_type is not None:
            type_filter = sql.SQL(" AND e.entity_type = %(entity_type)s")
            params["entity_type"] = entity_type.value

        query = sql.SQL(
            """
            SELECT DISTINCT
                e.id, e.agent_id, e.canonical_name, e.entity_type,
                e.description, e.first_seen_at, e.last_seen_at,
                e.mention_count, e.needs_disambiguation, e.embedding,
                e.schema_version, e.metadata
            FROM {schema}.entities e
            LEFT JOIN {schema}.entity_aliases a ON a.entity_id = e.id
            WHERE e.agent_id = %(agent_id)s
              AND (
                  e.canonical_name ILIKE %(needle)s
                  OR a.alias_text = %(lowered)s
              )
              {type_filter}
            """
        ).format(schema=schema, type_filter=type_filter)

        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return [_row_to_entity(r) for r in rows]

    def add_alias(
        self,
        entity_id: UUID,
        alias_text: str,
        *,
        learned_from_fact_id: UUID | None = None,
    ) -> EntityAlias:
        schema = self._resolve_schema_for_entity(entity_id)
        if schema is None:
            raise KeyError(f"Entity {entity_id} not found")

        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            entity = self._fetch_entity(cur, schema, entity_id)
            if entity is None:
                raise KeyError(f"Entity {entity_id} not found")
            return self._insert_alias(
                cur,
                schema,
                entity.id,
                entity.agent_id,
                alias_text,
                learned_from_fact_id,
            )

    def merge_entities(
        self,
        source_id: UUID,
        target_id: UUID,
        *,
        reason: str,
    ) -> Entity:
        source_schema = self._resolve_schema_for_entity(source_id)
        target_schema = self._resolve_schema_for_entity(target_id)
        if source_schema is None:
            raise KeyError(f"Source entity {source_id} not found")
        if target_schema is None:
            raise KeyError(f"Target entity {target_id} not found")

        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            source = self._fetch_entity(cur, source_schema, source_id)
            target = self._fetch_entity(cur, target_schema, target_id)
            if source is None:
                raise KeyError(f"Source entity {source_id} not found")
            if target is None:
                raise KeyError(f"Target entity {target_id} not found")

            # Pull source aliases — written-by-this-cursor view.
            fetch_aliases_sql = sql.SQL(
                """
                SELECT id, entity_id, agent_id, alias_text,
                       learned_from_fact_id, learned_at
                FROM {schema}.entity_aliases
                WHERE entity_id = %(source_id)s
                """
            ).format(schema=source_schema)
            cur.execute(fetch_aliases_sql, {"source_id": source_id})
            source_aliases = list(cur.fetchall())

            for alias_row in source_aliases:
                self._insert_alias(
                    cur,
                    target_schema,
                    target.id,
                    target.agent_id,
                    alias_row["alias_text"],
                    alias_row.get("learned_from_fact_id"),
                )

            # Mark source as needing disambiguation and accumulate mention_count
            # onto the target (single round-trip per side).
            update_source_sql = sql.SQL(
                """
                UPDATE {schema}.entities
                SET needs_disambiguation = TRUE,
                    metadata = metadata || %(merge_meta)s::jsonb
                WHERE id = %(source_id)s
                """
            ).format(schema=source_schema)
            cur.execute(
                update_source_sql,
                {
                    "source_id": source_id,
                    "merge_meta": Jsonb({"merged_into": str(target_id), "merge_reason": reason}),
                },
            )

            update_target_sql = sql.SQL(
                """
                UPDATE {schema}.entities
                SET mention_count = mention_count + %(added)s
                WHERE id = %(target_id)s
                RETURNING id, agent_id, canonical_name, entity_type, description,
                          first_seen_at, last_seen_at, mention_count,
                          needs_disambiguation, embedding, schema_version, metadata
                """
            ).format(schema=target_schema)
            cur.execute(
                update_target_sql,
                {
                    "target_id": target_id,
                    "added": source.mention_count,
                },
            )
            row = cur.fetchone()
            if row is None:  # pragma: no cover — defensive
                raise RuntimeError("Failed to update target entity during merge")
            return _row_to_entity(row)

    def update_last_seen(self, entity_id: UUID) -> None:
        schema = self._resolve_schema_for_entity(entity_id)
        if schema is None:
            return
        update_sql = sql.SQL(
            """
            UPDATE {schema}.entities
            SET last_seen_at = NOW(),
                mention_count = mention_count + 1
            WHERE id = %(entity_id)s
            """
        ).format(schema=schema)

        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(update_sql, {"entity_id": entity_id})

    def list_entities(
        self,
        agent_id: UUID,
        entity_type: EntityType | None = None,
        *,
        limit: int = 50,
    ) -> list[Entity]:
        schema = self._schema_ident(agent_id)

        type_filter = sql.SQL("")
        params: dict[str, Any] = {"agent_id": agent_id, "limit": limit}
        if entity_type is not None:
            type_filter = sql.SQL(" AND entity_type = %(entity_type)s")
            params["entity_type"] = entity_type.value

        query = sql.SQL(
            """
            SELECT id, agent_id, canonical_name, entity_type, description,
                   first_seen_at, last_seen_at, mention_count,
                   needs_disambiguation, embedding, schema_version, metadata
            FROM {schema}.entities
            WHERE agent_id = %(agent_id)s
              {type_filter}
            ORDER BY last_seen_at DESC
            LIMIT %(limit)s
            """
        ).format(schema=schema, type_filter=type_filter)

        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return [_row_to_entity(r) for r in rows]

    def flag_disambiguation(self, entity_id: UUID) -> None:
        schema = self._resolve_schema_for_entity(entity_id)
        if schema is None:
            return
        update_sql = sql.SQL(
            """
            UPDATE {schema}.entities
            SET needs_disambiguation = TRUE
            WHERE id = %(entity_id)s
            """
        ).format(schema=schema)

        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(update_sql, {"entity_id": entity_id})
