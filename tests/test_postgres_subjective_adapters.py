"""Unit tests for per-agent subjective Postgres adapters (mocked DB)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from atman.core.models import SelfAppliedChange, SelfChangeActor, SelfChangeTargetKind
from atman.core.models.pending_human_review import (
    PendingReviewDraft,
    PendingReviewKind,
)


@pytest.fixture
def agent_id() -> UUID:
    return uuid4()


def test_postgres_self_applied_change_store_primes_schema(agent_id: UUID) -> None:
    from atman.adapters.storage.postgres_self_applied_changes import (
        PostgresSelfAppliedChangeStore,
    )

    mock_conn = MagicMock()
    mock_conn.closed = False
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    store = PostgresSelfAppliedChangeStore(agent_id, fixed_serial_id=1)
    store._conn = mock_conn
    store._schema_resolver._serial_cache[agent_id] = 1

    change = SelfAppliedChange(
        actor=SelfChangeActor.REFLECTION_DAILY,
        reflection_event_id=uuid4(),
        target_kind=SelfChangeTargetKind.IDENTITY_PRINCIPLE,
        agent_id=agent_id,
        target_ref="p1",
        before_snapshot={"x": 1},
        after_snapshot={"x": 2},
        rationale="test",
        confidence_self_assessment="medium",
    )
    store.save(change)
    mock_conn.commit.assert_called()


def test_postgres_pending_inbox_enqueue_sets_agent_in_context(agent_id: UUID) -> None:
    from atman.adapters.storage.postgres_pending_human_review import (
        PostgresPendingHumanReviewInbox,
    )

    mock_conn = MagicMock()
    mock_conn.closed = False
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    inbox = PostgresPendingHumanReviewInbox(agent_id, fixed_serial_id=1)
    inbox._conn = mock_conn
    inbox._schema_resolver._serial_cache[agent_id] = 1

    draft = PendingReviewDraft(
        created_by="reflection_daily",
        kind=PendingReviewKind.IDENTITY_CHANGE_DOUBT,
        question="Should I add this principle?",
    )
    review = inbox.enqueue(draft)
    assert review.context.get("agent_id") == str(agent_id)
    mock_conn.commit.assert_called()


def test_postgres_pending_inbox_resolve_commits(agent_id: UUID) -> None:
    from atman.adapters.storage.postgres_pending_human_review import (
        PostgresPendingHumanReviewInbox,
    )
    from atman.core.models.pending_human_review import (
        PendingReview,
        PendingReviewPriority,
        PendingReviewResolution,
    )

    review_id = uuid4()
    existing = PendingReview(
        id=review_id,
        created_by="reflection_daily",
        kind=PendingReviewKind.NARRATIVE_CHANGE_DOUBT,
        question="Q?",
        priority=PendingReviewPriority.NORMAL,
    )

    mock_conn = MagicMock()
    mock_conn.closed = False
    mock_cursor = MagicMock()
    mock_cursor.fetchone.side_effect = [
        {
            "id": review_id,
            "created_at": existing.created_at,
            "created_by": existing.created_by,
            "reflection_event_id": None,
            "kind": existing.kind.value,
            "question": existing.question,
            "context": {"agent_id": str(agent_id)},
            "priority": existing.priority.value,
            "resolved_at": None,
            "resolution": None,
            "resolution_note": None,
            "applied_change_id": None,
        },
        {
            "id": review_id,
            "created_at": existing.created_at,
            "created_by": existing.created_by,
            "reflection_event_id": None,
            "kind": existing.kind.value,
            "question": existing.question,
            "context": {"agent_id": str(agent_id)},
            "priority": existing.priority.value,
            "resolved_at": datetime.now(UTC),
            "resolution": PendingReviewResolution.ACCEPTED.value,
            "resolution_note": "ok",
            "applied_change_id": None,
        },
    ]
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    inbox = PostgresPendingHumanReviewInbox(agent_id, fixed_serial_id=1)
    inbox._conn = mock_conn
    inbox._schema_resolver._serial_cache[agent_id] = 1

    resolved = inbox.resolve(
        review_id,
        resolution=PendingReviewResolution.ACCEPTED,
        note="ok",
        resolved_at=datetime.now(UTC),
    )
    assert resolved.is_resolved
