"""Tests for MemoryMiddlewarePort (E24)."""

from __future__ import annotations

from uuid import UUID, uuid4

from typing_extensions import override

from atman.core.ports.memory_middleware import MemoryContext, MemoryMiddlewarePort


class _StubMiddleware(MemoryMiddlewarePort):
    """Concrete stub used to exercise the protocol's abstract bodies."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    @override
    def prepare_context(self, session_id: UUID, situation: str) -> MemoryContext:
        # Run the protocol's abstract body for coverage.
        super().prepare_context(session_id, situation)
        self.calls.append(("prepare", (session_id, situation)))
        return MemoryContext(
            relevant_facts=[],
            relevant_experiences=[],
            emotional_echo="",
            conflicts=[],
        )

    @override
    def note_fact_used(
        self,
        session_id: UUID,
        fact_id: UUID,
        usage_type: str,
        context: str,
    ) -> None:
        super().note_fact_used(session_id, fact_id, usage_type, context)
        self.calls.append(("note", (session_id, fact_id, usage_type, context)))

    @override
    def end_session(self, session_id: UUID) -> None:
        super().end_session(session_id)
        self.calls.append(("end", (session_id,)))


def test_memory_context_stores_lists_and_strings():
    ctx = MemoryContext(
        relevant_facts=[],
        relevant_experiences=[],
        emotional_echo="calm",
        conflicts=["a vs b"],
    )
    assert ctx.emotional_echo == "calm"
    assert ctx.conflicts == ["a vs b"]
    assert ctx.relevant_facts == []
    assert ctx.relevant_experiences == []


def test_protocol_methods_callable_via_super():
    middleware = _StubMiddleware()
    session_id = uuid4()
    fact_id = uuid4()

    ctx = middleware.prepare_context(session_id, "morning standup")
    assert isinstance(ctx, MemoryContext)

    middleware.note_fact_used(session_id, fact_id, "cited", "in summary")
    middleware.end_session(session_id)

    assert [call[0] for call in middleware.calls] == ["prepare", "note", "end"]
