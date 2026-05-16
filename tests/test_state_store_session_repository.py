"""Tests for StateStoreSessionRepository — the SessionRepository adapter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from atman.adapters.reflection.state_store_session_repository import (
    StateStoreSessionRepository,
)
from atman.adapters.storage.file_state_store import FileStateStore
from atman.adapters.storage.in_memory_state_store import InMemoryStateStore
from atman.core.models import ExperienceRecord, SessionExperience
from atman.core.models.experience import (
    EmotionalDepth,
    FeltSense,
    KeyMoment,
    ReframingNote,
    ReframingNoteAppendResult,
)
from atman.core.models.session import Session


def _make_moment(session_id, what: str = "x", when: datetime | None = None) -> KeyMoment:
    return KeyMoment(
        what_happened=what,
        how_i_felt=FeltSense(
            emotional_valence=0.0, emotional_intensity=0.5, depth=EmotionalDepth.SURFACE
        ),
        why_it_matters="why",
        session_id=session_id,
        when=when or datetime.now(UTC),
    )


def test_get_session_returns_none_when_missing() -> None:
    repo = StateStoreSessionRepository(InMemoryStateStore())
    assert repo.get_session(uuid4()) is None


def test_get_session_returns_stored_session() -> None:
    store = InMemoryStateStore()
    agent = uuid4()
    s = Session(agent_id=agent)
    store.create_session(s)
    repo = StateStoreSessionRepository(store)
    fetched = repo.get_session(s.id)
    assert fetched is not None
    assert fetched.id == s.id


def test_list_recent_sessions_uses_default_agent_id() -> None:
    store = InMemoryStateStore()
    agent = uuid4()
    other = uuid4()
    s1 = Session(agent_id=agent, started_at=datetime.now(UTC) - timedelta(hours=2))
    s2 = Session(agent_id=agent, started_at=datetime.now(UTC) - timedelta(hours=1))
    s_other = Session(agent_id=other)
    for s in (s1, s2, s_other):
        store.create_session(s)

    repo = StateStoreSessionRepository(store, agent_id=agent)
    recent = repo.list_recent_sessions(limit=10)
    assert {s.id for s in recent} == {s1.id, s2.id}
    # Newest first
    assert recent[0].id == s2.id


def test_list_recent_sessions_with_explicit_agent_id_overrides_default() -> None:
    store = InMemoryStateStore()
    agent_a = uuid4()
    agent_b = uuid4()
    store.create_session(Session(agent_id=agent_a))
    store.create_session(Session(agent_id=agent_b))

    repo = StateStoreSessionRepository(store, agent_id=agent_a)
    only_b = repo.list_recent_sessions(agent_b)
    assert len(only_b) == 1
    assert only_b[0].agent_id == agent_b


def test_list_recent_sessions_without_default_raises() -> None:
    repo = StateStoreSessionRepository(InMemoryStateStore())
    with pytest.raises(ValueError, match="no agent_id"):
        repo.list_recent_sessions()


def test_get_sessions_in_range_two_arg_uses_default_agent_id() -> None:
    store = InMemoryStateStore()
    agent = uuid4()
    now = datetime.now(UTC)
    s_old = Session(agent_id=agent, started_at=now - timedelta(days=10))
    s_in = Session(agent_id=agent, started_at=now - timedelta(days=2))
    s_new = Session(agent_id=agent, started_at=now + timedelta(days=1))
    for s in (s_old, s_in, s_new):
        store.create_session(s)

    repo = StateStoreSessionRepository(store, agent_id=agent)
    result = repo.get_sessions_in_range(now - timedelta(days=5), now)
    assert {s.id for s in result} == {s_in.id}


def test_get_sessions_in_range_three_arg_explicit_agent_id() -> None:
    store = InMemoryStateStore()
    agent_a = uuid4()
    agent_b = uuid4()
    now = datetime.now(UTC)
    s_a = Session(agent_id=agent_a, started_at=now - timedelta(hours=1))
    s_b = Session(agent_id=agent_b, started_at=now - timedelta(hours=1))
    store.create_session(s_a)
    store.create_session(s_b)

    repo = StateStoreSessionRepository(store)
    only_a = repo.get_sessions_in_range(agent_a, now - timedelta(days=1), now)
    assert {s.id for s in only_a} == {s_a.id}


def test_get_key_moments_for_session() -> None:
    store = InMemoryStateStore()
    sid = uuid4()
    m1 = _make_moment(sid, what="first")
    m2 = _make_moment(sid, what="second")
    store.store_key_moments(sid, [m1, m2])

    repo = StateStoreSessionRepository(store)
    moments = repo.get_key_moments_for_session(sid)
    assert {m.id for m in moments} == {m1.id, m2.id}


def test_get_key_moments_in_range_filters_by_when() -> None:
    store = InMemoryStateStore()
    sid = uuid4()
    now = datetime.now(UTC)
    m_old = _make_moment(sid, what="old", when=now - timedelta(days=10))
    m_in = _make_moment(sid, what="in", when=now - timedelta(days=1))
    m_future = _make_moment(sid, what="future", when=now + timedelta(days=1))
    for m in (m_old, m_in, m_future):
        store.store_key_moment(m)

    repo = StateStoreSessionRepository(store)
    result = repo.get_key_moments_in_range(now - timedelta(days=5), now)
    assert {m.id for m in result} == {m_in.id}


def test_add_reframing_note_returns_experience_not_found_for_unknown_session() -> None:
    repo = StateStoreSessionRepository(InMemoryStateStore())
    note = ReframingNote(reflection="r", reflection_type="growth")
    assert repo.add_reframing_note(uuid4(), note) is ReframingNoteAppendResult.EXPERIENCE_NOT_FOUND


def test_add_reframing_note_stored_for_existing_session_experience() -> None:
    store = InMemoryStateStore()
    sid = uuid4()
    m = _make_moment(sid)
    exp = SessionExperience(
        id=sid,
        session_id=sid,
        timestamp=datetime.now(UTC),
        key_moment_ids=[m.id],
    )
    store.create_experience(ExperienceRecord(experience=exp))

    repo = StateStoreSessionRepository(store)
    note = ReframingNote(
        reflection="reframed perspective",
        reflection_type="growth",
        triggered_by="trigger-1",
    )
    result = repo.add_reframing_note(sid, note)
    assert result is ReframingNoteAppendResult.STORED


def test_add_reframing_note_duplicate_trigger_returns_duplicate() -> None:
    store = InMemoryStateStore()
    sid = uuid4()
    m = _make_moment(sid)
    exp = SessionExperience(
        id=sid,
        session_id=sid,
        timestamp=datetime.now(UTC),
        key_moment_ids=[m.id],
    )
    store.create_experience(ExperienceRecord(experience=exp))

    repo = StateStoreSessionRepository(store)
    note = ReframingNote(reflection="r", reflection_type="growth", triggered_by="trigger-1")
    first = repo.add_reframing_note(sid, note)
    assert first is ReframingNoteAppendResult.STORED
    # Second call with same triggered_by — duplicate must not be persisted
    second = repo.add_reframing_note(sid, note)
    assert second is ReframingNoteAppendResult.DUPLICATE_TRIGGERED_BY
    record = store.get_experience(sid)
    assert record is not None
    assert len(record.experience.reframing_notes) == 1


def test_add_reframing_note_duplicate_trigger_file_store_returns_duplicate(
    tmp_path,
) -> None:
    store = FileStateStore(workspace=tmp_path)
    sid = uuid4()
    m = _make_moment(sid)
    exp = SessionExperience(
        id=sid,
        session_id=sid,
        timestamp=datetime.now(UTC),
        key_moment_ids=[m.id],
    )
    store.create_experience(ExperienceRecord(experience=exp))

    repo = StateStoreSessionRepository(store)
    note = ReframingNote(reflection="r", reflection_type="growth", triggered_by="trigger-1")
    assert repo.add_reframing_note(sid, note) is ReframingNoteAppendResult.STORED
    assert repo.add_reframing_note(sid, note) is ReframingNoteAppendResult.DUPLICATE_TRIGGERED_BY
    record = store.get_experience(sid)
    assert record is not None
    assert len(record.experience.reframing_notes) == 1


def test_add_reframing_note_finds_experience_keyed_by_deterministic_uuid() -> None:
    """Regression: in production, experience records are keyed by
    ``deterministic_session_experience_id(session_id)`` (a uuid5), not by
    session_id. The adapter must derive the experience_id at the boundary
    or every reframing note silently returns EXPERIENCE_NOT_FOUND."""
    from atman.core.services.session_manager import deterministic_session_experience_id

    store = InMemoryStateStore()
    session_id = uuid4()
    experience_id = deterministic_session_experience_id(session_id)
    m = _make_moment(session_id)
    exp = SessionExperience(
        id=experience_id,
        session_id=session_id,
        timestamp=datetime.now(UTC),
        key_moment_ids=[m.id],
    )
    store.create_experience(ExperienceRecord(experience=exp))

    repo = StateStoreSessionRepository(store)
    note = ReframingNote(reflection="r", reflection_type="growth", triggered_by="t1")
    assert repo.add_reframing_note(session_id, note) is ReframingNoteAppendResult.STORED
    record = store.get_experience(experience_id)
    assert record is not None
    assert len(record.experience.reframing_notes) == 1
