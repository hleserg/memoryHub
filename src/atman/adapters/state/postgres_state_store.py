"""
PostgreSQL adapter for StateStore (KeyMoment operations only).

Implements KeyMoment storage methods of the StateStore port using psycopg3.
This is a partial implementation focusing on KeyMoment persistence.

Other StateStore methods (experiences, identity, narrative, eigenstate) are
not implemented and will raise NotImplementedError.
"""

import json
import os
import warnings
from datetime import datetime
from typing import TYPE_CHECKING, Any
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
from atman.core.ports.state_store import (
    ExperienceQuery,
    StateStore,
)


def _parse_key_moment(row: Any) -> KeyMoment:
    """Build a KeyMoment from a psycopg row."""
    data = row["data"]
    if isinstance(data, str):
        data = json.loads(data)

    # Parse the JSON data into a KeyMoment model
    return KeyMoment.model_validate(data)


class PostgresStateStore(StateStore):
    """
    PostgreSQL implementation of StateStore (KeyMoment operations only).

    Reads database URL from (in order):
      1. ``db_url`` constructor argument
      2. ``ATMAN_DB_URL`` environment variable
      3. ``DATABASE_URL`` environment variable
      4. ``postgresql://atman@localhost:5432/atman`` (default)

    Example::

        store = PostgresStateStore()
        store.store_key_moments(session_id, [moment1, moment2])
        moments = store.get_key_moments_for_session(session_id)
    """

    def __init__(self, db_url: str | None = None) -> None:
        if psycopg is None:
            raise ImportError("psycopg not installed. Install with: pip install 'psycopg[binary]'")

        self._db_url = (
            db_url
            or os.environ.get("ATMAN_DB_URL")
            or os.environ.get("DATABASE_URL")
            or "postgresql://atman@localhost:5432/atman"
        )
        self._conn: psycopg.Connection[Any] | None = None

    def _get_conn(self) -> "psycopg.Connection[Any]":
        """Get or create database connection."""
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(self._db_url, row_factory=dict_row)  # type: ignore[arg-type]
        return self._conn

    def close(self) -> None:
        """Close database connection."""
        if self._conn is not None and not self._conn.closed:
            self._conn.close()

    def __enter__(self) -> "PostgresStateStore":
        """Context manager entry."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Context manager exit."""
        self.close()

    # KeyMoment operations (implemented)

    def store_key_moments(self, session_id: UUID, moments: list[KeyMoment]) -> None:
        """
        Store key moments for a session.

        Args:
            session_id: UUID of the session
            moments: List of key moments to store
        """
        if not moments:
            return

        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            for moment in moments:
                # Serialize the KeyMoment to JSONB
                data = Jsonb(moment.model_dump(mode="json"))

                cur.execute(
                    """
                    INSERT INTO public.key_moments (id, session_id, data, created_at)
                    VALUES (%(id)s, %(session_id)s, %(data)s, %(created_at)s)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    {
                        "id": moment.id,
                        "session_id": session_id,
                        "data": data,
                        "created_at": moment.when,
                    },
                )

    def get_key_moment(self, moment_id: UUID) -> KeyMoment | None:
        """
        Retrieve a key moment by its ID.

        Args:
            moment_id: UUID of the key moment

        Returns:
            KeyMoment | None: The key moment if found, None otherwise
        """
        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, session_id, data, created_at
                FROM public.key_moments
                WHERE id = %(moment_id)s
                """,
                {"moment_id": moment_id},
            )
            row = cur.fetchone()
            if row is None:
                return None
            return _parse_key_moment(row)

    def get_key_moments_for_session(self, session_id: UUID) -> list[KeyMoment]:
        """
        Retrieve all key moments for a session.

        Args:
            session_id: UUID of the session

        Returns:
            list[KeyMoment]: List of key moments for the session
        """
        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, session_id, data, created_at
                FROM public.key_moments
                WHERE session_id = %(session_id)s
                ORDER BY created_at ASC
                """,
                {"session_id": session_id},
            )
            rows = cur.fetchall()
            return [_parse_key_moment(row) for row in rows]

    # Experience operations (not implemented)

    def create_experience(self, record: ExperienceRecord) -> ExperienceRecord:
        """Not implemented in this adapter."""
        raise NotImplementedError("Experience operations not implemented in PostgresStateStore")

    def get_experience(self, experience_id: UUID) -> ExperienceRecord | None:
        """Not implemented in this adapter."""
        raise NotImplementedError("Experience operations not implemented in PostgresStateStore")

    def add_reframing_note(
        self, experience_id: UUID, note: ReframingNote
    ) -> ExperienceRecord | None:
        """Not implemented in this adapter."""
        raise NotImplementedError("Experience operations not implemented in PostgresStateStore")

    def mark_accessed(self, experience_id: UUID) -> ExperienceRecord | None:
        """Not implemented in this adapter."""
        raise NotImplementedError("Experience operations not implemented in PostgresStateStore")

    def search_experiences(
        self, query: ExperienceQuery | None = None, limit: int = 10
    ) -> list[ExperienceRecord]:
        """Not implemented in this adapter."""
        raise NotImplementedError("Experience operations not implemented in PostgresStateStore")

    def list_recent_experiences(self, limit: int = 10) -> list[ExperienceRecord]:
        """Not implemented in this adapter."""
        raise NotImplementedError("Experience operations not implemented in PostgresStateStore")

    # Identity operations (not implemented)

    def load_identity(self, agent_id: UUID) -> Identity | None:
        """Not implemented in this adapter."""
        raise NotImplementedError("Identity operations not implemented in PostgresStateStore")

    def save_identity(self, identity: Identity, expected_version: str | None = None) -> Identity:
        """Not implemented in this adapter."""
        raise NotImplementedError("Identity operations not implemented in PostgresStateStore")

    def create_identity_snapshot(self, snapshot: IdentitySnapshot) -> IdentitySnapshot:
        """Not implemented in this adapter."""
        raise NotImplementedError("Identity operations not implemented in PostgresStateStore")

    def list_identity_snapshots(self, identity_id: UUID, limit: int = 10) -> list[IdentitySnapshot]:
        """Not implemented in this adapter."""
        raise NotImplementedError("Identity operations not implemented in PostgresStateStore")

    # Narrative operations (not implemented)

    def load_narrative(self, identity_id: UUID) -> NarrativeDocument | None:
        """Not implemented in this adapter."""
        raise NotImplementedError("Narrative operations not implemented in PostgresStateStore")

    def save_narrative(
        self,
        narrative: NarrativeDocument,
        expected_version: str | None = None,
        expected_updated_at: datetime | None = None,
    ) -> NarrativeDocument:
        """Not implemented in this adapter."""
        raise NotImplementedError("Narrative operations not implemented in PostgresStateStore")

    def archive_narrative(self, narrative_id: UUID, reason: str) -> None:
        """Not implemented in this adapter."""
        raise NotImplementedError("Narrative operations not implemented in PostgresStateStore")

    def list_archived_narratives(
        self, identity_id: UUID, limit: int = 10
    ) -> list[tuple[NarrativeDocument, str, datetime]]:
        """Not implemented in this adapter."""
        raise NotImplementedError("Narrative operations not implemented in PostgresStateStore")

    # Eigenstate operations (not implemented)

    def save_eigenstate(self, eigenstate: Eigenstate) -> Eigenstate:
        """Not implemented in this adapter."""
        raise NotImplementedError("Eigenstate operations not implemented in PostgresStateStore")

    def load_latest_eigenstate(
        self,
        session_id: UUID | None = None,
        identity_id: UUID | None = None,
    ) -> Eigenstate | None:
        """Not implemented in this adapter."""
        raise NotImplementedError("Eigenstate operations not implemented in PostgresStateStore")

    # KeyMoment operations (duplicate methods in port - using same implementations)

    def create_key_moment(self, key_moment: KeyMoment) -> KeyMoment:
        """
        Create a new key moment in storage.

        Args:
            key_moment: KeyMoment to store

        Returns:
            KeyMoment: The stored key moment

        Raises:
            ValueError: If the key moment already exists
        """
        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            # Note: We don't have session_id in KeyMoment model, so we use a placeholder
            # This method may need review when session_id is added to KeyMoment
            data = Jsonb(key_moment.model_dump(mode="json"))

            cur.execute(
                """
                INSERT INTO public.key_moments (id, session_id, data, created_at)
                VALUES (%(id)s, %(session_id)s, %(data)s, %(created_at)s)
                ON CONFLICT (id) DO NOTHING
                """,
                {
                    "id": key_moment.id,
                    "session_id": UUID("00000000-0000-0000-0000-000000000000"),  # Placeholder
                    "data": data,
                    "created_at": key_moment.when,
                },
            )

            # Check if the insert was successful (rowcount == 0 means duplicate)
            if cur.rowcount == 0:
                raise ValueError(f"KeyMoment {key_moment.id} already exists")

        return key_moment

    def list_key_moments(self, session_id: UUID | None = None) -> list[KeyMoment]:
        """
        List key moments, optionally filtered by session_id.

        Args:
            session_id: If provided, return only key moments from this session

        Returns:
            list[KeyMoment]: List of key moments
        """
        if session_id is not None:
            return self.get_key_moments_for_session(session_id)

        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, session_id, data, created_at
                FROM public.key_moments
                ORDER BY created_at ASC
                """
            )
            rows = cur.fetchall()
            return [_parse_key_moment(row) for row in rows]
