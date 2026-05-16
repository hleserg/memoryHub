"""Tests for :class:`InMemoryReflectionRequestQueue` and the request_reflection tool."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from atman.adapters.agent.tools import request_reflection
from atman.adapters.storage.in_memory_reflection_request_queue import (
    InMemoryReflectionRequestQueue,
)
from atman.core.models import ReflectionRequest, ReflectionRequestLevel
from atman.core.reflection_run_keys import agent_driven_run_key

# ---------------------------------------------------------------------------
# agent_driven_run_key
# ---------------------------------------------------------------------------


def test_run_key_collapses_same_reason_within_hour():
    t = datetime(2026, 5, 16, 14, 12, tzinfo=UTC)
    same = datetime(2026, 5, 16, 14, 58, tzinfo=UTC)
    a = agent_driven_run_key("daily", "user got upset", t)
    b = agent_driven_run_key("daily", "  user got upset  ", same)
    c = agent_driven_run_key("daily", "USER GOT UPSET", same)
    assert a == b == c


def test_run_key_differs_across_hours():
    t = datetime(2026, 5, 16, 14, 59, tzinfo=UTC)
    next_hour = datetime(2026, 5, 16, 15, 0, tzinfo=UTC)
    assert agent_driven_run_key("daily", "x", t) != agent_driven_run_key("daily", "x", next_hour)


def test_run_key_differs_across_levels():
    t = datetime(2026, 5, 16, 14, tzinfo=UTC)
    assert agent_driven_run_key("daily", "x", t) != agent_driven_run_key("deep", "x", t)


# ---------------------------------------------------------------------------
# In-memory queue contract
# ---------------------------------------------------------------------------


def _request(*, reason: str = "x", level: ReflectionRequestLevel = ReflectionRequestLevel.DAILY) -> ReflectionRequest:
    when = datetime.now(UTC)
    return ReflectionRequest(
        level=level,
        reason=reason,
        run_key=agent_driven_run_key(level.value, reason, when),
        requested_at=when,
    )


def test_enqueue_returns_same_record_for_duplicate_run_key():
    queue = InMemoryReflectionRequestQueue()
    a = _request()
    stored1 = queue.enqueue(a)
    # construct b with the same run_key but different id
    b = ReflectionRequest(
        level=a.level,
        reason=a.reason,
        run_key=a.run_key,
        requested_at=datetime.now(UTC),
    )
    stored2 = queue.enqueue(b)
    assert stored1.id == stored2.id
    assert stored1.id == a.id  # original wins


def test_take_pending_returns_only_matching_level_unconsumed_in_order():
    queue = InMemoryReflectionRequestQueue()
    daily_a = queue.enqueue(_request(reason="a"))
    deep = queue.enqueue(_request(reason="d", level=ReflectionRequestLevel.DEEP))
    daily_b = queue.enqueue(_request(reason="b"))

    pending_daily = queue.take_pending(level=ReflectionRequestLevel.DAILY)
    assert [r.id for r in pending_daily] == [daily_a.id, daily_b.id]

    pending_deep = queue.take_pending(level=ReflectionRequestLevel.DEEP)
    assert [r.id for r in pending_deep] == [deep.id]


def test_mark_consumed_excludes_from_pending():
    queue = InMemoryReflectionRequestQueue()
    a = queue.enqueue(_request(reason="a"))
    consumed_at = datetime.now(UTC)
    queue.mark_consumed(a.id, consumed_at=consumed_at, reflection_event_id=uuid4())
    pending = queue.take_pending(level=ReflectionRequestLevel.DAILY)
    assert pending == []
    assert queue.get_by_run_key(a.run_key).is_consumed  # type: ignore[union-attr]


def test_mark_consumed_twice_fails():
    queue = InMemoryReflectionRequestQueue()
    a = queue.enqueue(_request())
    queue.mark_consumed(a.id, consumed_at=datetime.now(UTC), reflection_event_id=uuid4())
    with pytest.raises(ValueError):
        queue.mark_consumed(a.id, consumed_at=datetime.now(UTC), reflection_event_id=uuid4())


def test_mark_consumed_unknown_id():
    queue = InMemoryReflectionRequestQueue()
    with pytest.raises(KeyError):
        queue.mark_consumed(uuid4(), consumed_at=datetime.now(UTC), reflection_event_id=uuid4())


# ---------------------------------------------------------------------------
# request_reflection tool
# ---------------------------------------------------------------------------


@dataclass
class _StubDeps:
    reflection_request_queue: InMemoryReflectionRequestQueue | None


@dataclass
class _StubCtx:
    deps: _StubDeps


def _ctx(queue: InMemoryReflectionRequestQueue | None) -> Any:
    return _StubCtx(deps=_StubDeps(reflection_request_queue=queue))


def test_tool_errors_without_queue():
    out = request_reflection(_ctx(None), "reason")
    assert out.startswith("Error: no reflection request queue")


def test_tool_validates_empty_reason():
    queue = InMemoryReflectionRequestQueue()
    out = request_reflection(_ctx(queue), "   ")
    assert out.startswith("Error: reason is required")


def test_tool_validates_level():
    queue = InMemoryReflectionRequestQueue()
    out = request_reflection(_ctx(queue), "ok", level="weekly_ish")
    assert out.startswith("Error: unknown level")


def test_tool_enqueues_request_and_returns_id():
    queue = InMemoryReflectionRequestQueue()
    out = request_reflection(_ctx(queue), "user pushed me hard today")
    assert "Queued reflection request" in out
    pending = queue.take_pending(level=ReflectionRequestLevel.DAILY)
    assert len(pending) == 1
    assert pending[0].reason == "user pushed me hard today"


def test_tool_collapses_duplicate_within_hour():
    queue = InMemoryReflectionRequestQueue()
    request_reflection(_ctx(queue), "user pushed me hard today")
    out = request_reflection(_ctx(queue), "user pushed me hard today")
    assert "Already queued" in out
    pending = queue.take_pending(level=ReflectionRequestLevel.DAILY)
    assert len(pending) == 1


def test_tool_accepts_deep_level_and_synonym():
    queue = InMemoryReflectionRequestQueue()
    request_reflection(_ctx(queue), "something to ponder", level="deep")
    request_reflection(_ctx(queue), "another thing", level="weekly")
    pending = queue.take_pending(level=ReflectionRequestLevel.DEEP)
    assert len(pending) == 2
