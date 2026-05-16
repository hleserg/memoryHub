"""R12 — Daily and Deep reflection drain the ReflectionRequestQueue."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from atman.adapters.reflection.mock_reflection_model import MockReflectionModel
from atman.adapters.storage.in_memory_reflection_request_queue import (
    InMemoryReflectionRequestQueue,
)
from atman.adapters.storage.in_memory_reflection_store import (
    InMemoryHealthAssessmentStore,
    InMemoryPatternStore,
    InMemoryReflectionEventStore,
)
from atman.core.models.experience import (
    EmotionalDepth,
    FeltSense,
    KeyMoment,
    ReframingNote,
    ReframingNoteAppendResult,
)
from atman.core.models.identity import Identity, IdentitySnapshot
from atman.core.models.narrative import LayerType, NarrativeDocument, NarrativeLayer
from atman.core.models.reflection_request import ReflectionRequest, ReflectionRequestLevel
from atman.core.models.session import Session
from atman.core.reflection_run_keys import agent_driven_run_key
from atman.core.services.reflection_service import (
    DailyReflectionService,
    DeepReflectionService,
)


class _SessionRepoStub:
    """Minimal SessionRepository surface for reflection services."""

    def __init__(self, sessions: list[Session], moments: dict[UUID, list[KeyMoment]]) -> None:
        self._sessions = {s.id: s for s in sessions}
        self._moments = moments

    def get_session(self, session_id: UUID) -> Session | None:  # pragma: no cover - unused
        return self._sessions.get(session_id)

    def list_recent_sessions(
        self, agent_id: UUID | None = None, *, limit: int = 10
    ) -> list[Session]:  # pragma: no cover
        return list(self._sessions.values())[:limit]

    def get_sessions_in_range(
        self,
        agent_id_or_start: UUID | datetime,
        start_or_end: datetime,
        end: datetime | None = None,
    ) -> list[Session]:
        if isinstance(agent_id_or_start, datetime):
            start, end_dt = agent_id_or_start, start_or_end
        else:
            start, end_dt = start_or_end, end
        assert end_dt is not None
        return [s for s in self._sessions.values() if start <= s.started_at <= end_dt]

    def get_key_moments_for_session(self, session_id: UUID) -> list[KeyMoment]:
        return list(self._moments.get(session_id, []))

    def get_key_moments_in_range(
        self, start: datetime, end: datetime
    ) -> list[KeyMoment]:  # pragma: no cover
        out: list[KeyMoment] = []
        for s in self.get_sessions_in_range(start, end):
            out.extend(self._moments.get(s.id, []))
        return out

    def add_reframing_note(
        self, session_id: UUID, note: ReframingNote, /
    ) -> ReframingNoteAppendResult:  # pragma: no cover
        return ReframingNoteAppendResult.STORED


class _IdentityRepoStub:
    def __init__(self, identity: Identity | None) -> None:
        self._identity = identity
        self._snapshots: dict[UUID, IdentitySnapshot] = {}

    def get_current(self) -> Identity | None:
        return self._identity

    def get_snapshot(self, snapshot_id: UUID) -> IdentitySnapshot | None:
        return self._snapshots.get(snapshot_id)

    def create_snapshot(
        self,
        identity: Identity,
        description: str,
        change_summary: str,
        *,
        snapshot_id: UUID | None = None,
    ) -> IdentitySnapshot:
        sid = snapshot_id or uuid4()
        snap = IdentitySnapshot(
            id=sid,
            identity_id=identity.id,
            identity_snapshot=identity.model_copy(deep=True),
            description=description,
            change_summary=change_summary,
        )
        self._snapshots[sid] = snap
        return snap

    def get_history(self) -> list[IdentitySnapshot]:  # pragma: no cover
        return list(self._snapshots.values())

    def update(self, identity: Identity) -> None:  # pragma: no cover
        self._identity = identity


class _NarrativeRepoStub:
    def __init__(self, narrative: NarrativeDocument | None) -> None:
        self._narr = narrative

    def get_current(self) -> NarrativeDocument | None:
        return self._narr.model_copy(deep=True) if self._narr else None

    def update(
        self,
        narrative: NarrativeDocument,
        *,
        expected_updated_at: datetime | None = None,
    ) -> None:  # pragma: no cover
        self._narr = narrative.model_copy(deep=True)

    def get_history(self) -> list[NarrativeDocument]:  # pragma: no cover
        return [self._narr] if self._narr else []


def _make_session_with_moments(anchor: datetime) -> tuple[Session, list[KeyMoment]]:
    sid = uuid4()
    session = Session(id=sid, agent_id=uuid4(), started_at=anchor)
    moments = [
        KeyMoment(
            session_id=sid,
            what_happened=f"event {i}",
            when=anchor + timedelta(minutes=i),
            how_i_felt=FeltSense(
                emotional_valence=0.0,
                emotional_intensity=0.5,
                depth=EmotionalDepth.MEANINGFUL,
            ),
            why_it_matters="t",
        )
        for i in range(3)
    ]
    return session, moments


def _enqueue(queue: InMemoryReflectionRequestQueue, level: ReflectionRequestLevel, reason: str):
    when = datetime.now(UTC)
    return queue.enqueue(
        ReflectionRequest(
            level=level,
            reason=reason,
            run_key=agent_driven_run_key(level.value, reason, when),
            requested_at=when,
        )
    )


# ---------------------------------------------------------------------------
# Daily
# ---------------------------------------------------------------------------


def test_daily_drains_pending_requests_and_marks_consumed():
    anchor = datetime(2026, 5, 16, 12, 0, 0, tzinfo=UTC)
    session, moments = _make_session_with_moments(anchor)

    queue = InMemoryReflectionRequestQueue()
    r = _enqueue(queue, ReflectionRequestLevel.DAILY, "user pushed me hard today")

    repo = _SessionRepoStub([session], {session.id: moments})
    service = DailyReflectionService(
        session_repo=repo,
        identity_repo=_IdentityRepoStub(Identity()),
        pattern_store=InMemoryPatternStore(),
        reflection_model=MockReflectionModel(),
        event_store=InMemoryReflectionEventStore(),
        reflection_request_queue=queue,
    )

    event = service.reflect(anchor)

    assert "user pushed me hard today" in (event.key_insight or "")
    assert "agent_driven_requests=1" in (event.notes or "")
    # Queue drained — no longer pending.
    assert queue.take_pending(level=ReflectionRequestLevel.DAILY) == []
    # And the original request is marked consumed.
    stored = queue.get_by_run_key(r.run_key)
    assert stored is not None and stored.is_consumed
    assert stored.consumed_by_reflection_event_id == event.id


def test_daily_drains_only_daily_level_requests():
    anchor = datetime(2026, 5, 16, 12, 0, 0, tzinfo=UTC)
    session, moments = _make_session_with_moments(anchor)

    queue = InMemoryReflectionRequestQueue()
    _enqueue(queue, ReflectionRequestLevel.DAILY, "daily reason")
    deep_req = _enqueue(queue, ReflectionRequestLevel.DEEP, "deep reason")

    repo = _SessionRepoStub([session], {session.id: moments})
    service = DailyReflectionService(
        session_repo=repo,
        identity_repo=_IdentityRepoStub(Identity()),
        pattern_store=InMemoryPatternStore(),
        reflection_model=MockReflectionModel(),
        event_store=InMemoryReflectionEventStore(),
        reflection_request_queue=queue,
    )

    service.reflect(anchor)

    # Deep request still pending.
    pending_deep = queue.take_pending(level=ReflectionRequestLevel.DEEP)
    assert [r.id for r in pending_deep] == [deep_req.id]


def test_daily_with_empty_day_still_consumes_requests():
    """Empty day → empty event, but pending requests should not pile up forever."""
    anchor = datetime(2026, 5, 16, 12, 0, 0, tzinfo=UTC)
    queue = InMemoryReflectionRequestQueue()
    r = _enqueue(queue, ReflectionRequestLevel.DAILY, "x")
    repo = _SessionRepoStub([], {})
    service = DailyReflectionService(
        session_repo=repo,
        identity_repo=_IdentityRepoStub(Identity()),
        pattern_store=InMemoryPatternStore(),
        reflection_model=MockReflectionModel(),
        event_store=InMemoryReflectionEventStore(),
        reflection_request_queue=queue,
    )
    event = service.reflect(anchor)
    stored = queue.get_by_run_key(r.run_key)
    assert stored is not None and stored.is_consumed
    assert stored.consumed_by_reflection_event_id == event.id


def test_daily_replay_does_not_re_drain_queue():
    """Idempotent replay must not consume new requests submitted between runs."""
    anchor = datetime(2026, 5, 16, 12, 0, 0, tzinfo=UTC)
    session, moments = _make_session_with_moments(anchor)
    queue = InMemoryReflectionRequestQueue()
    repo = _SessionRepoStub([session], {session.id: moments})

    service = DailyReflectionService(
        session_repo=repo,
        identity_repo=_IdentityRepoStub(Identity()),
        pattern_store=InMemoryPatternStore(),
        reflection_model=MockReflectionModel(),
        event_store=InMemoryReflectionEventStore(),
        reflection_request_queue=queue,
    )
    service.reflect(anchor)  # first live run, no requests

    # Now queue a request and replay — replay returns existing event,
    # the new request should stay pending for next live run.
    r = _enqueue(queue, ReflectionRequestLevel.DAILY, "ponder this later")
    service.reflect(anchor)

    pending = queue.take_pending(level=ReflectionRequestLevel.DAILY)
    assert [p.id for p in pending] == [r.id]


def test_daily_works_without_queue():
    """No queue configured → no drain, no error."""
    anchor = datetime(2026, 5, 16, 12, 0, 0, tzinfo=UTC)
    session, moments = _make_session_with_moments(anchor)
    repo = _SessionRepoStub([session], {session.id: moments})
    service = DailyReflectionService(
        session_repo=repo,
        identity_repo=_IdentityRepoStub(Identity()),
        pattern_store=InMemoryPatternStore(),
        reflection_model=MockReflectionModel(),
        event_store=InMemoryReflectionEventStore(),
    )
    event = service.reflect(anchor)
    assert "agent_driven_requests" not in (event.notes or "")


# ---------------------------------------------------------------------------
# Deep
# ---------------------------------------------------------------------------


def test_deep_drains_pending_requests_and_marks_consumed():
    anchor = datetime(2026, 5, 16, 12, 0, 0, tzinfo=UTC)
    sessions_with_moments = [
        _make_session_with_moments(anchor + timedelta(days=i)) for i in range(3)
    ]
    sessions = [s for s, _ in sessions_with_moments]
    moments_map = {s.id: m for s, m in sessions_with_moments}

    queue = InMemoryReflectionRequestQueue()
    _enqueue(queue, ReflectionRequestLevel.DAILY, "daily reason")  # should stay pending
    r = _enqueue(queue, ReflectionRequestLevel.DEEP, "look at trust ruptures")

    identity = Identity()
    narrative = NarrativeDocument(
        identity_id=identity.id,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="Core"),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="Recent"),
    )

    repo = _SessionRepoStub(sessions, moments_map)
    service = DeepReflectionService(
        session_repo=repo,
        identity_repo=_IdentityRepoStub(identity),
        narrative_repo=_NarrativeRepoStub(narrative),
        pattern_store=InMemoryPatternStore(),
        health_store=InMemoryHealthAssessmentStore(),
        reflection_model=MockReflectionModel(),
        event_store=InMemoryReflectionEventStore(),
        reflection_request_queue=queue,
    )

    event = service.reflect(anchor, anchor + timedelta(days=10))

    assert "look at trust ruptures" in (event.key_insight or "")
    assert "agent_driven_requests=1" in (event.notes or "")
    stored = queue.get_by_run_key(r.run_key)
    assert stored is not None and stored.is_consumed

    # Daily request untouched.
    pending_daily = queue.take_pending(level=ReflectionRequestLevel.DAILY)
    assert len(pending_daily) == 1
