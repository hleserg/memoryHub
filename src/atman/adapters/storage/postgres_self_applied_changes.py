"""PostgreSQL adapter for ``SelfAppliedChangeStore`` (per-agent schema)."""

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
            "psycopg not installed. PostgresSelfAppliedChangeStore requires PostgreSQL.",
            ImportWarning,
            stacklevel=2,
        )

from atman.adapters.storage.postgres_agent_schema import AgentSchemaResolver
from atman.core.models import SelfAppliedChange, SelfChangeActor, SelfChangeTargetKind
from atman.core.ports.self_applied_changes import SelfAppliedChangeStore


def _row_to_change(row: dict[str, Any]) -> SelfAppliedChange:
    return SelfAppliedChange(
        id=row["id"],
        applied_at=row["applied_at"],
        actor=SelfChangeActor(row["actor"]),
        reflection_event_id=row["reflection_event_id"],
        target_kind=SelfChangeTargetKind(row["target_kind"]),
        agent_id=row["agent_id"],
        target_ref=row["target_ref"],
        before_snapshot=dict(row["before_snapshot"] or {}),
        after_snapshot=dict(row["after_snapshot"] or {}),
        rationale=row["rationale"],
        confidence_self_assessment=row["confidence_self_assessment"],
        based_on_moment_ids=list(row["based_on_moment_ids"] or []),
        reverted_at=row["reverted_at"],
        reverted_reason=row["reverted_reason"],
        reverted_by_change_id=row["reverted_by_change_id"],
    )


class PostgresSelfAppliedChangeStore(SelfAppliedChangeStore):
    """Persists audit rows in ``agent_{serial_id}.self_applied_changes``."""

    def __init__(
        self,
        agent_id: UUID,
        db_url: str | None = None,
        *,
        fixed_serial_id: int | None = None,
    ) -> None:
        if psycopg is None:
            raise ImportError(
                "psycopg is required for PostgresSelfAppliedChangeStore. "
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
            raise RuntimeError("Call connect() before using PostgresSelfAppliedChangeStore")
        return self._conn

    def _schema(self) -> Any:
        conn = self._require_conn()
        return self._schema_resolver.schema_ident_for_connection(conn, self._agent_id)

    def save(self, change: SelfAppliedChange) -> None:
        conn = self._require_conn()
        schema = self._schema()
        q = sql.SQL(
            """
            INSERT INTO {schema}.self_applied_changes (
                id, applied_at, agent_id, actor, reflection_event_id, target_kind,
                target_ref, before_snapshot, after_snapshot, rationale,
                confidence_self_assessment, based_on_moment_ids,
                reverted_at, reverted_reason, reverted_by_change_id
            ) VALUES (
                %(id)s, %(applied_at)s, %(agent_id)s, %(actor)s, %(reflection_event_id)s,
                %(target_kind)s, %(target_ref)s, %(before_snapshot)s, %(after_snapshot)s,
                %(rationale)s, %(confidence_self_assessment)s, %(based_on_moment_ids)s,
                %(reverted_at)s, %(reverted_reason)s, %(reverted_by_change_id)s
            )
            """
        ).format(schema=schema)
        params = {
            "id": change.id,
            "applied_at": change.applied_at,
            "agent_id": change.agent_id,
            "actor": change.actor.value,
            "reflection_event_id": change.reflection_event_id,
            "target_kind": change.target_kind.value,
            "target_ref": change.target_ref,
            "before_snapshot": Jsonb(change.before_snapshot),
            "after_snapshot": Jsonb(change.after_snapshot),
            "rationale": change.rationale,
            "confidence_self_assessment": change.confidence_self_assessment,
            "based_on_moment_ids": change.based_on_moment_ids,
            "reverted_at": change.reverted_at,
            "reverted_reason": change.reverted_reason,
            "reverted_by_change_id": change.reverted_by_change_id,
        }
        try:
            with conn.cursor() as cur:
                cur.execute(q, params)
            conn.commit()
        except psycopg.errors.UniqueViolation as exc:
            conn.rollback()
            raise ValueError(f"self_applied_change {change.id} already saved") from exc

    def get(self, change_id: UUID) -> SelfAppliedChange | None:
        conn = self._require_conn()
        schema = self._schema()
        q = sql.SQL("SELECT * FROM {schema}.self_applied_changes WHERE id = %(id)s").format(
            schema=schema
        )
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(q, {"id": change_id})
            row = cur.fetchone()
        conn.commit()
        if row is None:
            return None
        return _row_to_change(row)

    def list(
        self,
        *,
        actor: SelfChangeActor | None = None,
        target_kind: SelfChangeTargetKind | None = None,
        since: datetime | None = None,
        only_active: bool = False,
        limit: int | None = None,
    ) -> list[SelfAppliedChange]:
        conn = self._require_conn()
        schema = self._schema()
        where_parts: list[sql.Composable] = [sql.SQL("TRUE")]
        params: dict[str, Any] = {}
        if actor is not None:
            where_parts.append(sql.SQL("actor = %(actor)s"))
            params["actor"] = actor.value
        if target_kind is not None:
            where_parts.append(sql.SQL("target_kind = %(target_kind)s"))
            params["target_kind"] = target_kind.value
        if since is not None:
            where_parts.append(sql.SQL("applied_at >= %(since)s"))
            params["since"] = since
        if only_active:
            where_parts.append(sql.SQL("reverted_at IS NULL"))
        where_sql = sql.SQL(" AND ").join(where_parts)
        order_sql = sql.SQL(" ORDER BY applied_at DESC")
        limit_sql = sql.SQL(" LIMIT %(limit)s") if limit is not None else sql.SQL("")
        if limit is not None:
            params["limit"] = limit
        q = (
            sql.SQL("SELECT * FROM {schema}.self_applied_changes WHERE ").format(schema=schema)
            + where_sql
            + order_sql
            + limit_sql
        )
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(q, params)
            rows = cur.fetchall()
        conn.commit()
        return [_row_to_change(r) for r in rows]

    def mark_reverted(
        self,
        change_id: UUID,
        *,
        reverted_at: datetime,
        reason: str,
        reverted_by_change_id: UUID | None = None,
    ) -> SelfAppliedChange:
        conn = self._require_conn()
        existing = self.get(change_id)
        if existing is None:
            raise KeyError(f"self_applied_change {change_id} not found")
        if existing.reverted_at is not None:
            raise ValueError(f"self_applied_change {change_id} already reverted")
        schema = self._schema()
        q = sql.SQL(
            """
            UPDATE {schema}.self_applied_changes
            SET reverted_at = %(reverted_at)s,
                reverted_reason = %(reason)s,
                reverted_by_change_id = %(reverted_by_change_id)s
            WHERE id = %(id)s
            """
        ).format(schema=schema)
        with conn.cursor() as cur:
            cur.execute(
                q,
                {
                    "id": change_id,
                    "reverted_at": reverted_at,
                    "reason": reason,
                    "reverted_by_change_id": reverted_by_change_id,
                },
            )
        conn.commit()
        updated = self.get(change_id)
        assert updated is not None
        return updated
