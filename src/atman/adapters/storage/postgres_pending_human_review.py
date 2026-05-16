"""PostgreSQL adapter for ``PendingHumanReviewInbox`` (per-agent schema)."""

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
        warnings.warn(
            "psycopg not installed. PostgresPendingHumanReviewInbox requires PostgreSQL.",
            ImportWarning,
            stacklevel=2,
        )

from atman.adapters.storage.postgres_agent_schema import AgentSchemaResolver
from atman.core.models.pending_human_review import (
    PendingReview,
    PendingReviewDraft,
    PendingReviewKind,
    PendingReviewPriority,
    PendingReviewResolution,
)
from atman.core.ports.pending_human_review import PendingHumanReviewInbox


def _row_to_review(row: dict[str, Any]) -> PendingReview:
    resolution = row["resolution"]
    return PendingReview(
        id=row["id"],
        created_at=row["created_at"],
        created_by=row["created_by"],
        reflection_event_id=row["reflection_event_id"],
        kind=PendingReviewKind(row["kind"]),
        question=row["question"],
        context=dict(row["context"] or {}),
        priority=PendingReviewPriority(row["priority"]),
        resolved_at=row["resolved_at"],
        resolution=PendingReviewResolution(resolution) if resolution else None,
        resolution_note=row["resolution_note"],
        applied_change_id=row["applied_change_id"],
    )


class PostgresPendingHumanReviewInbox(PendingHumanReviewInbox):
    """Persists inbox rows in ``agent_{serial_id}.pending_human_review``."""

    def __init__(
        self,
        agent_id: UUID,
        db_url: str | None = None,
        *,
        fixed_serial_id: int | None = None,
    ) -> None:
        if psycopg is None:
            raise ImportError(
                "psycopg is required for PostgresPendingHumanReviewInbox. "
                "Install with: pip install psycopg[binary]"
            )
        self._agent_id = agent_id
        self._db_url = db_url or os.environ.get(
            "ATMAN_DB_URL", "postgresql://atman@localhost:5432/atman"
        )
        self._conn: psycopg.Connection[Any] | None = None
        self._schema_resolver = AgentSchemaResolver(fixed_serial_id=fixed_serial_id)

    def connect(self) -> None:
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(self._db_url)

    def close(self) -> None:
        if self._conn is not None and not self._conn.closed:
            self._conn.close()

    def _require_conn(self) -> psycopg.Connection[Any]:
        if self._conn is None or self._conn.closed:
            raise RuntimeError("Call connect() before using PostgresPendingHumanReviewInbox")
        return self._conn

    def _schema(self) -> Any:
        conn = self._require_conn()
        return self._schema_resolver.schema_ident_for_connection(conn, self._agent_id)

    def enqueue(self, draft: PendingReviewDraft) -> PendingReview:
        conn = self._require_conn()
        review = PendingReview(
            created_by=draft.created_by,
            reflection_event_id=draft.reflection_event_id,
            kind=draft.kind,
            question=draft.question,
            context=dict(draft.context),
            priority=draft.priority,
        )
        ctx = dict(review.context)
        ctx.setdefault("agent_id", str(self._agent_id))
        schema = self._schema()
        q = sql.SQL(
            """
            INSERT INTO {schema}.pending_human_review (
                id, created_at, created_by, reflection_event_id, kind, question,
                context, priority
            ) VALUES (
                %(id)s, %(created_at)s, %(created_by)s, %(reflection_event_id)s,
                %(kind)s, %(question)s, %(context)s, %(priority)s
            )
            """
        ).format(schema=schema)
        with conn.cursor() as cur:
            cur.execute(
                q,
                {
                    "id": review.id,
                    "created_at": review.created_at,
                    "created_by": review.created_by,
                    "reflection_event_id": review.reflection_event_id,
                    "kind": review.kind.value,
                    "question": review.question,
                    "context": Jsonb(ctx),
                    "priority": review.priority.value,
                },
            )
        conn.commit()
        return review.model_copy(update={"context": ctx})

    def get(self, review_id: UUID) -> PendingReview | None:
        conn = self._require_conn()
        schema = self._schema()
        q = sql.SQL("SELECT * FROM {schema}.pending_human_review WHERE id = %(id)s").format(
            schema=schema
        )
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(q, {"id": review_id})
            row = cur.fetchone()
        conn.commit()
        if row is None:
            return None
        return _row_to_review(row)

    def list_unresolved(
        self,
        *,
        kind: PendingReviewKind | None = None,
        limit: int | None = None,
    ) -> list[PendingReview]:
        conn = self._require_conn()
        schema = self._schema()
        where_parts: list[sql.Composable] = [sql.SQL("resolved_at IS NULL")]
        params: dict[str, Any] = {}
        if kind is not None:
            where_parts.append(sql.SQL("kind = %(kind)s"))
            params["kind"] = kind.value
        where_sql = sql.SQL(" AND ").join(where_parts)
        limit_sql = sql.SQL(" LIMIT %(limit)s") if limit is not None else sql.SQL("")
        if limit is not None:
            params["limit"] = limit
        q = (
            sql.SQL("SELECT * FROM {schema}.pending_human_review WHERE ").format(schema=schema)
            + where_sql
            + sql.SQL(" ORDER BY CASE priority WHEN 'high' THEN 0 ELSE 1 END, created_at")
            + limit_sql
        )
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(q, params)
            rows = cur.fetchall()
        conn.commit()
        return [_row_to_review(r) for r in rows]

    def resolve(
        self,
        review_id: UUID,
        *,
        resolution: PendingReviewResolution,
        note: str,
        resolved_at: datetime,
        applied_change_id: UUID | None = None,
    ) -> PendingReview:
        conn = self._require_conn()
        existing = self.get(review_id)
        if existing is None:
            raise KeyError(f"pending_human_review {review_id} not found")
        if existing.is_resolved:
            raise ValueError(f"pending_human_review {review_id} already resolved")
        schema = self._schema()
        q = sql.SQL(
            """
            UPDATE {schema}.pending_human_review
            SET resolved_at = %(resolved_at)s,
                resolution = %(resolution)s,
                resolution_note = %(note)s,
                applied_change_id = %(applied_change_id)s
            WHERE id = %(id)s
            """
        ).format(schema=schema)
        with conn.cursor() as cur:
            cur.execute(
                q,
                {
                    "id": review_id,
                    "resolved_at": resolved_at,
                    "resolution": resolution.value,
                    "note": note,
                    "applied_change_id": applied_change_id,
                },
            )
        conn.commit()
        updated = self.get(review_id)
        assert updated is not None
        return updated
