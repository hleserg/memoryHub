"""Tests for PostWriteScheduler — async + sync enqueue paths."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from atman.adapters.maintenance.in_memory_queue import InMemoryMaintenanceQueue
from atman.core.models.experience import EmotionalDepth, FeltSense, KeyMoment
from atman.core.models.maintenance import JobName, JobStatus
from atman.core.services.post_write_scheduler import PostWriteScheduler


def _moment(session_id=None) -> KeyMoment:
    return KeyMoment(
        what_happened="thing",
        how_i_felt=FeltSense(
            emotional_valence=0.1, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
        ),
        why_it_matters="why",
        session_id=session_id,
    )


def test_schedule_for_key_moment_enqueues_default_jobs() -> None:
    q = InMemoryMaintenanceQueue()
    scheduler = PostWriteScheduler(q)
    agent = uuid4()
    moment = _moment()
    scheduler.schedule_for_key_moment(moment, agent)

    jobs = q.list_jobs()
    job_names = {j.job_name for j in jobs}
    assert JobName.mrebel_extract in job_names
    assert JobName.lingvo_enrich in job_names
    # All jobs reference the moment via payload
    for j in jobs:
        assert j.payload["key_moment_id"] == str(moment.id)
        assert j.agent_id == agent
        assert j.status is JobStatus.pending


def test_schedule_for_key_moment_idempotent_via_run_key() -> None:
    q = InMemoryMaintenanceQueue()
    scheduler = PostWriteScheduler(q)
    agent = uuid4()
    moment = _moment()
    scheduler.schedule_for_key_moment(moment, agent)
    scheduler.schedule_for_key_moment(moment, agent)
    # Each job name should appear at most once for this moment.
    by_name = [j for j in q.list_jobs() if j.job_name is JobName.mrebel_extract]
    assert len(by_name) == 1


def test_schedule_for_key_moment_custom_jobs_only() -> None:
    q = InMemoryMaintenanceQueue()
    scheduler = PostWriteScheduler(q, jobs=(JobName.salience_decay,))
    agent = uuid4()
    moment = _moment()
    scheduler.schedule_for_key_moment(moment, agent)
    jobs = q.list_jobs()
    assert len(jobs) == 1
    assert jobs[0].job_name is JobName.salience_decay


def test_schedule_for_key_moment_swallows_queue_errors(caplog) -> None:
    class _BoomQueue(InMemoryMaintenanceQueue):
        def enqueue(self, *args, **kwargs):  # type: ignore[override]
            raise RuntimeError("queue down")

    scheduler = PostWriteScheduler(_BoomQueue())
    agent = uuid4()
    moment = _moment()
    # Must not propagate the exception — post-write hooks are best-effort.
    scheduler.schedule_for_key_moment(moment, agent)


def test_schedule_at_specific_time() -> None:
    q = InMemoryMaintenanceQueue()
    scheduler = PostWriteScheduler(q, jobs=(JobName.mrebel_extract,))
    when = datetime.now(UTC) + timedelta(minutes=5)
    moment = _moment()
    scheduler.schedule_for_key_moment(moment, uuid4(), scheduled_at=when)
    assert q.list_jobs()[0].scheduled_at == when


def test_async_schedule_falls_back_to_sync_without_loop() -> None:
    """`schedule_for_key_moment_async` must work even when called sync (no running loop)."""
    q = InMemoryMaintenanceQueue()
    scheduler = PostWriteScheduler(q, jobs=(JobName.mrebel_extract,))
    moment = _moment()
    asyncio.run(scheduler.schedule_for_key_moment_async(moment, uuid4()))
    assert len(q.list_jobs()) == 1


@pytest.mark.asyncio
async def test_async_schedule_inside_event_loop_creates_task() -> None:
    q = InMemoryMaintenanceQueue()
    scheduler = PostWriteScheduler(q, jobs=(JobName.mrebel_extract,))
    moment = _moment()
    agent = uuid4()
    await scheduler.schedule_for_key_moment_async(moment, agent)
    # Give the loop a chance to run the spawned task
    await asyncio.sleep(0)
    assert len(q.list_jobs()) == 1
