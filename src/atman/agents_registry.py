"""
Agent registry backed by PostgreSQL public.agents table.

Uses admin URL for schema creation (DDL), app URL for reads.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import psycopg


@dataclass
class AgentRecord:
    serial_id: int
    uuid: UUID
    name: str
    description: str
    created_at: datetime


class AgentsRegistry:
    def __init__(self, app_url: str, admin_url: str | None = None) -> None:
        """
        app_url:   atman_app role — for reads
        admin_url: atman superuser — for schema creation (DDL)
        """
        self._app_url = app_url
        self._admin_url = admin_url or app_url

    def create(self, description: str = "", name: str = "") -> AgentRecord:
        """Create agent record and provision its private schema."""
        with psycopg.connect(self._admin_url) as conn, conn.transaction():
            row = conn.execute(
                """
                INSERT INTO public.agents (name, description)
                VALUES (%s, %s)
                RETURNING serial_id, id, name, description, created_at
                """,
                [name or description or "agent", description],
            ).fetchone()

            if row is None:
                raise RuntimeError("INSERT INTO public.agents returned no row")

            record = AgentRecord(
                serial_id=row[0],
                uuid=row[1],
                name=row[2],
                description=row[3],
                created_at=row[4],
            )

            conn.execute(
                "SELECT public.create_agent_schema(%s, %s)",
                [record.uuid, record.serial_id],
            )

        return record

    def get_by_serial(self, serial_id: int) -> AgentRecord | None:
        with psycopg.connect(self._app_url) as conn:
            row = conn.execute(
                "SELECT serial_id, id, name, description, created_at "
                "FROM public.agents WHERE serial_id = %s",
                [serial_id],
            ).fetchone()
        if row is None:
            return None
        return AgentRecord(
            serial_id=row[0],
            uuid=row[1],
            name=row[2],
            description=row[3],
            created_at=row[4],
        )

    def list_all(self) -> list[AgentRecord]:
        with psycopg.connect(self._app_url) as conn:
            rows = conn.execute(
                "SELECT serial_id, id, name, description, created_at "
                "FROM public.agents ORDER BY serial_id"
            ).fetchall()
        return [
            AgentRecord(serial_id=r[0], uuid=r[1], name=r[2], description=r[3], created_at=r[4])
            for r in rows
        ]
