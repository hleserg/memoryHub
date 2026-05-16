"""Resolve per-agent PostgreSQL schema names from public.agents."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    import psycopg
    from psycopg import sql
else:
    try:
        import psycopg
        from psycopg import sql
    except ImportError:
        psycopg = None
        sql = None  # type: ignore[assignment]


class AgentSchemaResolver:
    """Maps agent UUID to ``agent_{serial_id}`` schema identifiers."""

    def __init__(self, *, fixed_serial_id: int | None = None) -> None:
        self._fixed_serial_id = fixed_serial_id
        self._serial_cache: dict[UUID, int] = {}

    def schema_name(self, agent_id: UUID) -> str:
        if self._fixed_serial_id is not None:
            return f"agent_{self._fixed_serial_id}"
        if agent_id in self._serial_cache:
            return f"agent_{self._serial_cache[agent_id]}"
        raise LookupError(
            f"Agent {agent_id} serial_id not cached; call resolve_serial_id(conn, agent_id) first"
        )

    def schema_ident(self, agent_id: UUID) -> Any:
        if sql is None:
            raise ImportError("psycopg is required for AgentSchemaResolver")
        return sql.Identifier(self.schema_name(agent_id))

    def resolve_serial_id(self, conn: psycopg.Connection[Any], agent_id: UUID) -> int:
        if self._fixed_serial_id is not None:
            self._serial_cache[agent_id] = self._fixed_serial_id
            return self._fixed_serial_id
        if agent_id in self._serial_cache:
            return self._serial_cache[agent_id]
        row = conn.execute(
            "SELECT serial_id FROM public.agents WHERE id = %s",
            [agent_id],
        ).fetchone()
        if row is None:
            raise LookupError(f"Agent {agent_id} not found in public.agents")
        serial_id = int(row[0])
        self._serial_cache[agent_id] = serial_id
        return serial_id

    def schema_ident_for_connection(self, conn: psycopg.Connection[Any], agent_id: UUID) -> Any:
        self.resolve_serial_id(conn, agent_id)
        return self.schema_ident(agent_id)

    def fixed_schema_ident(self) -> Any | None:
        if self._fixed_serial_id is None:
            return None
        if sql is None:
            raise ImportError("psycopg is required for AgentSchemaResolver")
        return sql.Identifier(f"agent_{self._fixed_serial_id}")
