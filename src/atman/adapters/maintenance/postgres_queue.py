"""PostgreSQL adapter for MaintenanceQueue with SKIP LOCKED claim semantics."""

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
            "psycopg not installed. PostgresMaintenanceQueue requires PostgreSQL support. "
            "Install with: pip install 'psycopg[binary]'",
            ImportWarning,
            stacklevel=2,
        )

from atman.core.models.maintenance import JobName, JobStatus, MaintenanceJob
from atman.core.ports.maintenance_queue import MaintenanceQueue


def _coerce_dict(value: Any) -> dict[str, Any]:
    """Coerce a JSONB column value into a plain dict."""
    if value is None:
        return {}
    if isinstance(value, str):
        loaded = json.loads(value)
        return loaded if isinstance(loaded, dict) else {}
    if isinstance(value, dict):
        return value
    return {}


def _coerce_optional_dict(value: Any) -> dict[str, Any] | None:
    """Coerce a JSONB column value into an optional dict (None preserved)."""
    if value is None:
        return None
    if isinstance(value, str):
        loaded = json.loads(value)
        return loaded if isinstance(loaded, dict) else None
    if isinstance(value, dict):
        return value
    return None


def _row_to_job(row: Any) -> MaintenanceJob:
    """Build a MaintenanceJob from a psycopg dict_row."""
    return MaintenanceJob(
        id=row["id"],
        job_name=JobName(row["job_name"]),
        agent_id=row["agent_id"],
        payload=_coerce_dict(row["payload"]),
        run_key=row["run_key"],
        status=JobStatus(row["status"]),
        scheduled_at=row["scheduled_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        error=row["error"],
        result=_coerce_optional_dict(row["result"]),
    )


_JOB_COLUMNS = (
    "id, job_name, agent_id, payload, run_key, status, "
    "scheduled_at, started_at, finished_at, error, result"
)

# Pre-composed SQL templates — built once at module load with the static
# _JOB_COLUMNS interpolated. All user-supplied data is bound via %(name)s
# parameters, so these strings are safe to pass to cursor.execute() directly
# without bandit B608 flagging f-string composition at the call site.
_SQL_SELECT_BY_RUN_KEY = f"""
    SELECT {_JOB_COLUMNS}
    FROM public.maintenance_jobs
    WHERE run_key = %(run_key)s
      AND status IN ('pending', 'running')
    LIMIT 1
"""  # nosec B608

_SQL_INSERT_JOB = f"""
    INSERT INTO public.maintenance_jobs
        (job_name, agent_id, payload, run_key, scheduled_at)
    VALUES
        (%(job_name)s, %(agent_id)s, %(payload)s, %(run_key)s,
         COALESCE(%(scheduled_at)s, NOW()))
    RETURNING {_JOB_COLUMNS}
"""  # nosec B608

_SQL_CLAIM_BATCH = f"""
    WITH next_jobs AS (
        SELECT id
        FROM public.maintenance_jobs
        WHERE status = 'pending'
          AND (%(job_name)s::text IS NULL OR job_name = %(job_name)s)
        ORDER BY scheduled_at
        LIMIT %(batch_size)s
        FOR UPDATE SKIP LOCKED
    )
    UPDATE public.maintenance_jobs
    SET status = 'running',
        started_at = NOW()
    WHERE id IN (SELECT id FROM next_jobs)
    RETURNING {_JOB_COLUMNS}
"""  # nosec B608

_SQL_LIST_JOBS = f"""
    SELECT {_JOB_COLUMNS}
    FROM public.maintenance_jobs
    WHERE (%(status)s::text IS NULL OR status = %(status)s)
      AND (%(agent_id)s::uuid IS NULL OR agent_id = %(agent_id)s)
    ORDER BY scheduled_at DESC
    LIMIT %(limit)s
"""  # nosec B608


class PostgresMaintenanceQueue(MaintenanceQueue):
    """
    PostgreSQL-backed MaintenanceQueue using ``SELECT ... FOR UPDATE SKIP LOCKED``.

    Reads database URL from (in order):
      1. ``db_url`` constructor argument
      2. ``ATMAN_DB_URL`` environment variable
      3. ``DATABASE_URL`` environment variable
      4. ``postgresql://atman@localhost:5432/atman`` (default)

    Example::

        queue = PostgresMaintenanceQueue()
        job = queue.enqueue(JobName.salience_decay, agent_id=agent_id)
        for claimed in queue.claim_batch(batch_size=5):
            try:
                ...
                queue.mark_done(claimed.id, result={"updated": 5})
            except Exception as exc:
                queue.mark_failed(claimed.id, error=str(exc))
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

    def __enter__(self) -> "PostgresMaintenanceQueue":
        """Context manager entry."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Context manager exit."""
        self.close()

    # ------------------------------------------------------------------
    # Enqueue
    # ------------------------------------------------------------------

    def enqueue(
        self,
        job_name: JobName,
        *,
        agent_id: UUID | None = None,
        payload: dict | None = None,
        run_key: str | None = None,
        scheduled_at: datetime | None = None,
    ) -> MaintenanceJob:
        """
        Enqueue a job. If ``run_key`` matches an existing pending/running job,
        return that existing row (idempotent).
        """
        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            if run_key is not None:
                cur.execute(_SQL_SELECT_BY_RUN_KEY, {"run_key": run_key})
                existing = cur.fetchone()
                if existing is not None:
                    return _row_to_job(existing)

            cur.execute(
                _SQL_INSERT_JOB,
                {
                    "job_name": job_name.value,
                    "agent_id": agent_id,
                    "payload": Jsonb(payload or {}),
                    "run_key": run_key,
                    "scheduled_at": scheduled_at,
                },
            )
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("INSERT ... RETURNING returned no row")
            return _row_to_job(row)

    # ------------------------------------------------------------------
    # Claiming
    # ------------------------------------------------------------------

    def claim_batch(
        self,
        job_name: JobName | None = None,
        *,
        batch_size: int = 10,
    ) -> list[MaintenanceJob]:
        """
        Atomically claim up to ``batch_size`` pending jobs using
        ``SELECT ... FOR UPDATE SKIP LOCKED``. Returns claimed jobs with
        ``status=running``. Two concurrent callers get disjoint job sets.
        """
        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(
                _SQL_CLAIM_BATCH,
                {
                    "job_name": job_name.value if job_name is not None else None,
                    "batch_size": batch_size,
                },
            )
            rows = cur.fetchall()
            return [_row_to_job(r) for r in rows]

    # ------------------------------------------------------------------
    # Completion transitions
    # ------------------------------------------------------------------

    def mark_done(self, job_id: UUID, *, result: dict | None = None) -> None:
        """Mark job as succeeded."""
        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """
                UPDATE public.maintenance_jobs
                SET status = 'succeeded',
                    finished_at = NOW(),
                    result = %(result)s
                WHERE id = %(job_id)s
                """,
                {
                    "job_id": job_id,
                    "result": Jsonb(result) if result is not None else None,
                },
            )

    def mark_failed(self, job_id: UUID, *, error: str) -> None:
        """Mark job as failed."""
        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """
                UPDATE public.maintenance_jobs
                SET status = 'failed',
                    finished_at = NOW(),
                    error = %(error)s
                WHERE id = %(job_id)s
                """,
                {"job_id": job_id, "error": error},
            )

    def mark_skipped(self, job_id: UUID, *, reason: str = "") -> None:
        """Mark job as skipped (duplicate or not applicable)."""
        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(
                """
                UPDATE public.maintenance_jobs
                SET status = 'skipped',
                    finished_at = NOW(),
                    error = %(reason)s
                WHERE id = %(job_id)s
                """,
                {"job_id": job_id, "reason": reason},
            )

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------

    def list_jobs(
        self,
        status: JobStatus | None = None,
        agent_id: UUID | None = None,
        *,
        limit: int = 100,
    ) -> list[MaintenanceJob]:
        """List jobs filtered by status and/or agent, newest ``scheduled_at`` first."""
        conn = self._get_conn()
        with conn.transaction(), conn.cursor() as cur:
            cur.execute(
                _SQL_LIST_JOBS,
                {
                    "status": status.value if status is not None else None,
                    "agent_id": agent_id,
                    "limit": limit,
                },
            )
            rows = cur.fetchall()
            return [_row_to_job(r) for r in rows]
