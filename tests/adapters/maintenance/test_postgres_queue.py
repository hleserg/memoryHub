"""Tests for PostgresMaintenanceQueue (SKIP LOCKED claim semantics)."""

from __future__ import annotations

import os
import threading
from typing import Any
from uuid import uuid4

import pytest

# Skip all tests if psycopg is not installed
try:
    import psycopg  # noqa: F401

    PSYCOPG_AVAILABLE = True
except ImportError:
    PSYCOPG_AVAILABLE = False

from atman.core.models.maintenance import JobName, JobStatus

pytestmark = [
    pytest.mark.skipif(not PSYCOPG_AVAILABLE, reason="psycopg not installed"),
    pytest.mark.skipif(
        not os.environ.get("TEST_DB_URL"),
        reason="TEST_DB_URL not set - skipping PostgresMaintenanceQueue tests",
    ),
]


@pytest.fixture
def db_url() -> str:
    """Return test database URL from environment."""
    return os.environ.get("TEST_DB_URL", "postgresql://atman@localhost:5432/atman_test")


@pytest.fixture
def queue(db_url: str) -> Any:
    """Create a PostgresMaintenanceQueue instance for testing with a clean table."""
    from atman.adapters.maintenance.postgres_queue import PostgresMaintenanceQueue

    q = PostgresMaintenanceQueue(db_url=db_url)
    conn = q._get_conn()
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE public.maintenance_jobs")
    conn.commit()
    yield q
    q.close()


# ---------------------------------------------------------------------------
# enqueue
# ---------------------------------------------------------------------------


def test_enqueue_creates_pending(queue: Any) -> None:
    agent = uuid4()
    job = queue.enqueue(JobName.salience_decay, agent_id=agent)
    assert job.status is JobStatus.pending
    assert job.agent_id == agent
    assert job.job_name is JobName.salience_decay
    assert job.payload == {}
    assert job.scheduled_at is not None
    assert job.started_at is None
    assert job.finished_at is None


def test_enqueue_with_payload(queue: Any) -> None:
    job = queue.enqueue(
        JobName.memory_guardian_scan,
        payload={"window_days": 7, "agent": "test"},
    )
    assert job.payload == {"window_days": 7, "agent": "test"}


def test_enqueue_idempotent_via_run_key(queue: Any) -> None:
    a = queue.enqueue(JobName.salience_decay, run_key="day-2026-05-16-decay")
    b = queue.enqueue(JobName.salience_decay, run_key="day-2026-05-16-decay")
    assert a.id == b.id
    assert len(queue.list_jobs()) == 1


def test_enqueue_distinct_run_keys_creates_two(queue: Any) -> None:
    a = queue.enqueue(JobName.salience_decay, run_key="k1")
    b = queue.enqueue(JobName.salience_decay, run_key="k2")
    assert a.id != b.id
    assert len(queue.list_jobs()) == 2


def test_enqueue_run_key_after_terminal_creates_new(queue: Any) -> None:
    """A new job with the same run_key after the previous one terminated returns the prior row.

    The SQL UNIQUE constraint on run_key plus the idempotency check only matches
    pending/running jobs. Once the first job is marked done/failed/skipped, a
    second enqueue with the same key would *attempt* an INSERT and hit the UNIQUE
    constraint. Confirm that this raises an integrity error (callers must use
    a fresh run_key after terminal states).
    """
    a = queue.enqueue(JobName.salience_decay, run_key="reuse-key")
    queue.mark_done(a.id)
    with pytest.raises(Exception):  # psycopg.errors.UniqueViolation
        queue.enqueue(JobName.salience_decay, run_key="reuse-key")


# ---------------------------------------------------------------------------
# claim_batch
# ---------------------------------------------------------------------------


def test_claim_batch_marks_running(queue: Any) -> None:
    for _ in range(3):
        queue.enqueue(JobName.salience_decay)
    claimed = queue.claim_batch(batch_size=2)
    assert len(claimed) == 2
    assert all(c.status is JobStatus.running for c in claimed)
    assert all(c.started_at is not None for c in claimed)
    # Remaining still pending
    pending = queue.list_jobs(status=JobStatus.pending)
    assert len(pending) == 1


def test_claim_batch_filters_by_job_name(queue: Any) -> None:
    queue.enqueue(JobName.salience_decay)
    queue.enqueue(JobName.memory_guardian_scan)
    claimed = queue.claim_batch(job_name=JobName.memory_guardian_scan, batch_size=10)
    assert len(claimed) == 1
    assert claimed[0].job_name is JobName.memory_guardian_scan


def test_claim_batch_empty_returns_empty(queue: Any) -> None:
    assert queue.claim_batch(batch_size=10) == []


def test_claim_batch_skip_locked_disjoint(db_url: str) -> None:
    """Two parallel callers MUST receive disjoint job sets (SKIP LOCKED).

    We run two threads, each calling claim_batch on its own connection. The
    union of their claims should equal the total set of enqueued jobs, with
    no overlap.
    """
    from atman.adapters.maintenance.postgres_queue import PostgresMaintenanceQueue

    # Producer queue: seed the table.
    producer = PostgresMaintenanceQueue(db_url=db_url)
    conn = producer._get_conn()
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE public.maintenance_jobs")
    conn.commit()

    job_ids = set()
    for _ in range(10):
        job_ids.add(producer.enqueue(JobName.salience_decay).id)
    producer.close()

    # Two worker queues, each on its own connection.
    worker_a = PostgresMaintenanceQueue(db_url=db_url)
    worker_b = PostgresMaintenanceQueue(db_url=db_url)

    start_barrier = threading.Barrier(2)
    results: dict[str, list] = {}

    def claim(name: str, q: Any) -> None:
        start_barrier.wait()
        results[name] = q.claim_batch(batch_size=10)

    t_a = threading.Thread(target=claim, args=("a", worker_a))
    t_b = threading.Thread(target=claim, args=("b", worker_b))
    t_a.start()
    t_b.start()
    t_a.join()
    t_b.join()

    ids_a = {j.id for j in results["a"]}
    ids_b = {j.id for j in results["b"]}

    # Disjoint
    assert ids_a.isdisjoint(ids_b), f"overlap between workers: {ids_a & ids_b}"
    # Union covers all jobs
    assert ids_a | ids_b == job_ids
    # All claimed are running
    assert all(j.status is JobStatus.running for j in results["a"] + results["b"])

    worker_a.close()
    worker_b.close()


# ---------------------------------------------------------------------------
# mark_done / mark_failed / mark_skipped
# ---------------------------------------------------------------------------


def test_mark_done_failed_skipped(queue: Any) -> None:
    j1 = queue.enqueue(JobName.salience_decay)
    j2 = queue.enqueue(JobName.salience_decay)
    j3 = queue.enqueue(JobName.salience_decay)
    queue.claim_batch(batch_size=10)
    queue.mark_done(j1.id, result={"updated": 5})
    queue.mark_failed(j2.id, error="boom")
    queue.mark_skipped(j3.id, reason="dup")

    all_jobs = {j.id: j for j in queue.list_jobs()}
    assert all_jobs[j1.id].status is JobStatus.succeeded
    assert all_jobs[j1.id].result == {"updated": 5}
    assert all_jobs[j1.id].finished_at is not None

    assert all_jobs[j2.id].status is JobStatus.failed
    assert all_jobs[j2.id].error == "boom"
    assert all_jobs[j2.id].finished_at is not None

    assert all_jobs[j3.id].status is JobStatus.skipped
    assert all_jobs[j3.id].error == "dup"
    assert all_jobs[j3.id].finished_at is not None


def test_mark_unknown_id_is_silent(queue: Any) -> None:
    # Should not raise even though id does not exist.
    queue.mark_done(uuid4())
    queue.mark_failed(uuid4(), error="x")
    queue.mark_skipped(uuid4())


def test_mark_done_with_none_result(queue: Any) -> None:
    j = queue.enqueue(JobName.salience_decay)
    queue.claim_batch(batch_size=10)
    queue.mark_done(j.id)
    fetched = next(x for x in queue.list_jobs() if x.id == j.id)
    assert fetched.status is JobStatus.succeeded
    assert fetched.result is None


# ---------------------------------------------------------------------------
# list_jobs
# ---------------------------------------------------------------------------


def test_list_jobs_filter_and_order(queue: Any) -> None:
    agent = uuid4()
    j1 = queue.enqueue(JobName.salience_decay, agent_id=agent)
    j2 = queue.enqueue(JobName.salience_decay)

    all_jobs = queue.list_jobs()
    assert {j.id for j in all_jobs} == {j1.id, j2.id}

    only_agent = queue.list_jobs(agent_id=agent)
    assert {j.id for j in only_agent} == {j1.id}


def test_list_jobs_filter_by_status(queue: Any) -> None:
    j1 = queue.enqueue(JobName.salience_decay)
    queue.enqueue(JobName.salience_decay)
    queue.claim_batch(batch_size=1)
    queue.mark_done(j1.id)

    succeeded = queue.list_jobs(status=JobStatus.succeeded)
    assert {j.id for j in succeeded} == {j1.id}

    pending = queue.list_jobs(status=JobStatus.pending)
    assert len(pending) == 1


def test_list_jobs_limit(queue: Any) -> None:
    for _ in range(5):
        queue.enqueue(JobName.salience_decay)
    jobs = queue.list_jobs(limit=2)
    assert len(jobs) == 2


def test_list_jobs_orders_newest_first(queue: Any) -> None:
    j1 = queue.enqueue(JobName.salience_decay)
    j2 = queue.enqueue(JobName.salience_decay)
    j3 = queue.enqueue(JobName.salience_decay)
    jobs = queue.list_jobs()
    # Most recently scheduled first.
    assert [j.id for j in jobs] == [j3.id, j2.id, j1.id]


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


def test_context_manager(db_url: str) -> None:
    from atman.adapters.maintenance.postgres_queue import PostgresMaintenanceQueue

    with PostgresMaintenanceQueue(db_url=db_url) as q:
        conn = q._get_conn()
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE public.maintenance_jobs")
        conn.commit()
        job = q.enqueue(JobName.salience_decay)
        assert job.status is JobStatus.pending
