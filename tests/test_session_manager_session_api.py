"""Regression tests for SessionManager v2 Session API wiring.

These tests verify the post-PR-#558 behaviour where start_session calls
state_store.create_session and finish_session calls update_session, plus
the failure-mode contracts around those calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atman.adapters.storage.in_memory_state_store import InMemoryStateStore
from atman.core.models import (
    Identity,
    LayerType,
    NarrativeDocument,
    NarrativeLayer,
    Session,
)
from atman.core.services.session_manager import SessionManager


def _bootstrap_agent(store: InMemoryStateStore) -> Identity:
    """Persist a minimal identity + narrative pair so start_session can run."""
    identity = Identity(self_description="test")
    store.save_identity(identity)
    narrative = NarrativeDocument(
        identity_id=identity.id,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="core"),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="recent"),
    )
    store.save_narrative(narrative)
    return identity


def test_start_session_persists_session_row(tmp_path: Path) -> None:
    """start_session must call state_store.create_session with status='active'."""
    store = InMemoryStateStore()
    identity = _bootstrap_agent(store)
    manager = SessionManager(store)

    context = manager.start_session(identity.id)

    persisted = store.get_session(context.session_id)
    assert persisted is not None
    assert persisted.id == context.session_id
    assert persisted.agent_id == identity.id
    assert persisted.status == "active"
    assert persisted.identity_snapshot_id == context.identity_snapshot_id


def test_start_session_rolls_back_on_create_session_failure() -> None:
    """If create_session raises, the orphan must not stay in _active_sessions."""

    class _ExplodingStore(InMemoryStateStore):
        def create_session(self, session: Session) -> Session:  # type: ignore[override]
            raise RuntimeError("DB connection lost")

    store = _ExplodingStore()
    identity = _bootstrap_agent(store)
    manager = SessionManager(store)

    with pytest.raises(RuntimeError, match="DB connection lost"):
        manager.start_session(identity.id)

    # No orphan in the active registry — a subsequent start must succeed.
    assert manager.list_active_sessions() == []


def test_start_session_failure_does_not_leak_max_active_sessions_slot() -> None:
    """An orphan would block `max_active_sessions=1`; cleanup must restore the slot."""

    failures = {"count": 0}

    class _OnceExplodingStore(InMemoryStateStore):
        def create_session(self, session: Session) -> Session:  # type: ignore[override]
            if failures["count"] == 0:
                failures["count"] += 1
                raise RuntimeError("transient failure")
            return super().create_session(session)

    store = _OnceExplodingStore()
    identity = _bootstrap_agent(store)
    manager = SessionManager(store, max_active_sessions=1)

    with pytest.raises(RuntimeError, match="transient failure"):
        manager.start_session(identity.id)

    # Slot freed — a retry must succeed.
    context = manager.start_session(identity.id)
    assert context is not None
    assert len(manager.list_active_sessions()) == 1
