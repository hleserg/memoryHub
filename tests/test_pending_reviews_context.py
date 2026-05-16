"""Tests for `format_pending_reviews_block` and the `resolve_pending_review` tool."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from atman.adapters.agent.pending_reviews_context import format_pending_reviews_block
from atman.adapters.agent.tools import resolve_pending_review
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
    kind: PendingReviewKind = PendingReviewKind.IDENTITY_CHANGE_DOUBT,
    question: str = "Should I add a 'patience' principle?",
    priority: PendingReviewPriority = PendingReviewPriority.NORMAL,
    context: dict[str, Any] | None = None,
) -> PendingReviewDraft:
    return PendingReviewDraft(
        created_by="reflection_daily",
        reflection_event_id=uuid4(),
        kind=kind,
        question=question,
        priority=priority,
        context=context or {},
    )


def test_format_block_returns_none_when_inbox_missing():
    assert format_pending_reviews_block(None) is None


def test_format_block_returns_none_when_no_items():
    inbox = InMemoryPendingHumanReviewInbox()
    assert format_pending_reviews_block(inbox) is None


def test_format_block_contains_question_and_id():
    inbox = InMemoryPendingHumanReviewInbox()
    item = inbox.enqueue(_draft(question="Confirm this change?"))
    block = format_pending_reviews_block(inbox)
    assert block is not None
    assert "Confirm this change?" in block
    assert str(item.id) in block
    assert "resolve_pending_review" in block


def test_format_block_high_priority_appears_before_normal():
    inbox = InMemoryPendingHumanReviewInbox()
    normal = inbox.enqueue(_draft(question="normal item"))
    high = inbox.enqueue(_draft(question="urgent item", priority=PendingReviewPriority.HIGH))
    block = format_pending_reviews_block(inbox)
    assert block is not None
    assert block.find(str(high.id)) < block.find(str(normal.id))


def test_format_block_limit_respected():
    inbox = InMemoryPendingHumanReviewInbox()
    inbox.enqueue(_draft(question="q1"))
    inbox.enqueue(_draft(question="q2"))
    inbox.enqueue(_draft(question="q3"))
    inbox.enqueue(_draft(question="q4"))
    block = format_pending_reviews_block(inbox, limit=2)
    assert block is not None
    assert block.count("resolve_pending_review") == 1  # one mention in preamble
    assert block.count("priority=") == 2


def test_format_block_renders_string_and_dict_context():
    inbox = InMemoryPendingHumanReviewInbox()
    inbox.enqueue(
        _draft(
            context={
                "proposed_principle": "Take time to listen before answering.",
                "supporting_moments": [str(uuid4()), str(uuid4())],
            }
        )
    )
    block = format_pending_reviews_block(inbox)
    assert block is not None
    assert "proposed_principle" in block
    assert "Take time to listen" in block
    assert "supporting_moments" in block


def test_format_block_truncates_very_long_strings():
    inbox = InMemoryPendingHumanReviewInbox()
    inbox.enqueue(_draft(context={"k": "x" * 500}))
    block = format_pending_reviews_block(inbox)
    assert block is not None
    assert "..." in block
    assert "x" * 500 not in block


# ---------------------------------------------------------------------------
# resolve_pending_review tool
# ---------------------------------------------------------------------------


@dataclass
class _StubDeps:
    pending_review_inbox: InMemoryPendingHumanReviewInbox | None


@dataclass
class _StubCtx:
    deps: _StubDeps


def _ctx(inbox: InMemoryPendingHumanReviewInbox | None) -> Any:
    return _StubCtx(deps=_StubDeps(pending_review_inbox=inbox))


def test_resolve_tool_errors_without_inbox():
    out = resolve_pending_review(_ctx(None), str(uuid4()), "accepted", "x")
    assert out.startswith("Error: no pending review inbox")


def test_resolve_tool_validates_decision():
    inbox = InMemoryPendingHumanReviewInbox()
    item = inbox.enqueue(_draft())
    out = resolve_pending_review(_ctx(inbox), str(item.id), "maybe", "ok")
    assert out.startswith("Error: unknown decision")


def test_resolve_tool_validates_note_required():
    inbox = InMemoryPendingHumanReviewInbox()
    item = inbox.enqueue(_draft())
    out = resolve_pending_review(_ctx(inbox), str(item.id), "accepted", "   ")
    assert out.startswith("Error: note is required")


def test_resolve_tool_validates_uuid():
    inbox = InMemoryPendingHumanReviewInbox()
    out = resolve_pending_review(_ctx(inbox), "not-a-uuid", "accepted", "ok")
    assert "not a valid UUID" in out


def test_resolve_tool_unknown_id():
    inbox = InMemoryPendingHumanReviewInbox()
    out = resolve_pending_review(_ctx(inbox), str(uuid4()), "accepted", "ok")
    assert "no pending review" in out


def test_resolve_tool_happy_path_accept_with_synonym():
    inbox = InMemoryPendingHumanReviewInbox()
    item = inbox.enqueue(_draft())
    out = resolve_pending_review(_ctx(inbox), str(item.id), "yes", "agreed")
    assert "Resolved review" in out
    refreshed = inbox.get(item.id)
    assert refreshed is not None
    assert refreshed.resolution == PendingReviewResolution.ACCEPTED
    assert refreshed.resolution_note == "agreed"
    assert refreshed.resolved_at is not None


def test_resolve_tool_double_resolve_returns_error():
    inbox = InMemoryPendingHumanReviewInbox()
    item = inbox.enqueue(_draft())
    resolve_pending_review(_ctx(inbox), str(item.id), "rejected", "no")
    out = resolve_pending_review(_ctx(inbox), str(item.id), "accepted", "changed mind")
    assert out.startswith("Error:")


def test_resolve_tool_decision_aliases_map_correctly():
    inbox = InMemoryPendingHumanReviewInbox()
    for synonym, expected in [
        ("approve", PendingReviewResolution.ACCEPTED),
        ("decline", PendingReviewResolution.REJECTED),
        ("modified", PendingReviewResolution.MODIFIED),
        ("skip", PendingReviewResolution.DISMISSED),
    ]:
        item = inbox.enqueue(_draft())
        resolve_pending_review(_ctx(inbox), str(item.id), synonym, "note")
        refreshed = inbox.get(item.id)
        assert refreshed is not None
        assert refreshed.resolution == expected


