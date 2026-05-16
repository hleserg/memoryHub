"""
Tests for the pending human review inbox.

The inbox is the bridge between reflection's "I'm not sure" and the next
interactive session: reflection writes, the runner picks up at session start.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from atman.adapters.storage.in_memory_pending_human_review import (
    InMemoryPendingHumanReviewInbox,
)
from atman.core.models import (
    PendingReviewDraft,
    PendingReviewKind,
    PendingReviewPriority,
    PendingReviewResolution,
)


def _draft(
    *,
    created_by: str = "reflection_daily",
    kind: PendingReviewKind = PendingReviewKind.IDENTITY_CHANGE_DOUBT,
    question: str = "Should I add this principle?",
    priority: PendingReviewPriority = PendingReviewPriority.NORMAL,
    context: dict | None = None,
) -> PendingReviewDraft:
    return PendingReviewDraft(
        created_by=created_by,
        reflection_event_id=uuid4(),
        kind=kind,
        question=question,
        context=context or {"proposed": "principle text"},
        priority=priority,
    )


def test_draft_requires_nonempty_fields():
    with pytest.raises(ValueError):
        PendingReviewDraft(
            created_by="   ",
            kind=PendingReviewKind.IDENTITY_CHANGE_DOUBT,
            question="x",
        )
    with pytest.raises(ValueError):
        PendingReviewDraft(
            created_by="x",
            kind=PendingReviewKind.IDENTITY_CHANGE_DOUBT,
            question="",
        )


def test_enqueue_persists_and_get_returns_same_item():
    inbox = InMemoryPendingHumanReviewInbox()
    item = inbox.enqueue(_draft())
    assert inbox.get(item.id) == item
    assert not item.is_resolved


def test_list_unresolved_orders_high_priority_first_then_oldest():
    inbox = InMemoryPendingHumanReviewInbox()
    normal_old = inbox.enqueue(_draft(question="normal old"))
    high = inbox.enqueue(_draft(question="high", priority=PendingReviewPriority.HIGH))
    normal_new = inbox.enqueue(_draft(question="normal new"))

    rows = inbox.list_unresolved()
    assert [r.id for r in rows] == [high.id, normal_old.id, normal_new.id]


def test_list_unresolved_kind_filter_and_limit():
    inbox = InMemoryPendingHumanReviewInbox()
    inbox.enqueue(_draft(kind=PendingReviewKind.IDENTITY_CHANGE_DOUBT))
    narrative = inbox.enqueue(_draft(kind=PendingReviewKind.NARRATIVE_CHANGE_DOUBT))
    inbox.enqueue(_draft(kind=PendingReviewKind.IDENTITY_CHANGE_DOUBT))

    only_narrative = inbox.list_unresolved(kind=PendingReviewKind.NARRATIVE_CHANGE_DOUBT)
    assert [r.id for r in only_narrative] == [narrative.id]

    limited = inbox.list_unresolved(limit=2)
    assert len(limited) == 2


def test_resolve_marks_item_and_excludes_from_unresolved():
    inbox = InMemoryPendingHumanReviewInbox()
    item = inbox.enqueue(_draft())
    applied_change = uuid4()
    resolved_at = datetime.now(UTC)

    resolved = inbox.resolve(
        item.id,
        resolution=PendingReviewResolution.ACCEPTED,
        note="agreed",
        resolved_at=resolved_at,
        applied_change_id=applied_change,
    )
    assert resolved.is_resolved
    assert resolved.resolution == PendingReviewResolution.ACCEPTED
    assert resolved.resolution_note == "agreed"
    assert resolved.applied_change_id == applied_change

    assert inbox.list_unresolved() == []


def test_resolve_unknown_id_raises_key_error():
    inbox = InMemoryPendingHumanReviewInbox()
    with pytest.raises(KeyError):
        inbox.resolve(
            uuid4(),
            resolution=PendingReviewResolution.DISMISSED,
            note="x",
            resolved_at=datetime.now(UTC),
        )


def test_resolve_twice_raises_value_error():
    inbox = InMemoryPendingHumanReviewInbox()
    item = inbox.enqueue(_draft())
    inbox.resolve(
        item.id,
        resolution=PendingReviewResolution.REJECTED,
        note="no",
        resolved_at=datetime.now(UTC),
    )
    with pytest.raises(ValueError):
        inbox.resolve(
            item.id,
            resolution=PendingReviewResolution.ACCEPTED,
            note="changed mind",
            resolved_at=datetime.now(UTC),
        )
