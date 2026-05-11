"""SessionManager integration with AffectDetector."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from atman.adapters.storage.in_memory_state_store import InMemoryStateStore
from atman.affect.detector import AffectDetectorConfig
from atman.core.clock_impl import FrozenClock
from atman.core.models import (
    CoreValue,
    EmotionalDepth,
    Goal,
    GoalHorizon,
    Identity,
    KeyMomentInput,
    LayerType,
    NarrativeDocument,
    NarrativeLayer,
    SessionEvent,
)
from atman.core.services import SessionManager


def _bootstrap_identity_narrative(store: InMemoryStateStore, agent_id) -> None:
    identity = Identity(
        id=agent_id,
        self_description="t",
        core_values=[CoreValue(name="x", description="d", confidence=0.5)],
        goals=[Goal(content="g", horizon=GoalHorizon.SHORT)],
        emotional_baseline=0.0,
    )
    store.save_identity(identity)
    narrative = NarrativeDocument(
        id=uuid4(),
        identity_id=agent_id,
        core_layer=NarrativeLayer(layer_type=LayerType.CORE, content="c"),
        recent_layer=NarrativeLayer(layer_type=LayerType.RECENT, content="r"),
    )
    store.save_narrative(narrative)


@pytest.mark.asyncio
async def test_session_manager_schedules_async_detector(tmp_path: Path) -> None:
    store = InMemoryStateStore()
    clock = FrozenClock(datetime(2025, 1, 1, tzinfo=UTC))
    agent_id = uuid4()
    _bootstrap_identity_narrative(store, agent_id)
    cfg = AffectDetectorConfig(cold_start_sessions=0, random_sample_every_n=1)
    mgr = SessionManager(
        store,
        clock=clock,
        affect_workspace=tmp_path,
        affect_config=cfg,
    )
    ctx = mgr.start_session(agent_id)
    det = mgr.affect_detector
    assert det is not None
    det.process = AsyncMock(return_value=None)  # type: ignore[method-assign]
    ev = SessionEvent(
        session_id=ctx.session_id,
        event_type="agent_response",
        description="This is a long enough reply for affect analysis to run in English today.",
        thinking="I feel dark and hopeless about everything.",
    )
    mgr.record_event(ctx.session_id, ev)
    await asyncio.sleep(0.05)
    det.process.assert_awaited()


def test_session_manager_affect_runs_when_no_event_loop(
    tmp_path: Path,
) -> None:
    """Sync ``record_event`` uses ``asyncio.run`` when no loop is running."""
    store = InMemoryStateStore()
    clock = FrozenClock(datetime(2025, 1, 1, tzinfo=UTC))
    agent_id = uuid4()
    _bootstrap_identity_narrative(store, agent_id)
    cfg = AffectDetectorConfig(cold_start_sessions=0, random_sample_every_n=1)
    mgr = SessionManager(
        store,
        clock=clock,
        affect_workspace=tmp_path,
        affect_config=cfg,
    )
    ctx = mgr.start_session(agent_id)
    mgr.record_event(
        ctx.session_id,
        SessionEvent(
            session_id=ctx.session_id,
            event_type="agent_response",
            description="This is a long enough reply for affect analysis to run in English today.",
            thinking="I feel dark and hopeless about everything.",
        ),
    )


def test_session_manager_no_affect_when_not_configured() -> None:
    store = InMemoryStateStore()
    clock = FrozenClock(datetime(2025, 1, 1, tzinfo=UTC))
    agent_id = uuid4()
    _bootstrap_identity_narrative(store, agent_id)
    mgr = SessionManager(store, clock=clock)
    ctx = mgr.start_session(agent_id)
    assert mgr.affect_detector is None
    mgr.record_event(
        ctx.session_id,
        SessionEvent(
            session_id=ctx.session_id,
            event_type="t",
            description="not important text long enough xxxxxxxxxxxxx",
        ),
    )


def test_record_key_moment_stub_attribute_error() -> None:
    store = InMemoryStateStore()
    clock = FrozenClock(datetime(2025, 1, 1, tzinfo=UTC))
    agent_id = uuid4()
    _bootstrap_identity_narrative(store, agent_id)
    mgr = SessionManager(store, clock=clock)
    ctx = mgr.start_session(agent_id)
    m = KeyMomentInput(
        what_happened="w",
        emotional_valence=0.2,
        emotional_intensity=0.3,
        depth=EmotionalDepth.SURFACE,
        why_it_matters="y",
    )
    with pytest.raises(AttributeError, match="AffectDetector"):
        mgr.record_key_moment(ctx.session_id, m)
