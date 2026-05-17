"""Tests for HLE-29 — AffectDetector ↔ DivergenceDetector ↔ event store wiring."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from atman.adapters.memory.in_memory_divergence_events import InMemoryDivergenceEventStore
from atman.affect.detector import AffectDetector, AffectDetectorConfig
from atman.core.models.experience import KeyMoment
from atman.core.ports.linguistic import (
    AgentMessageAnalysis,
    KeyMomentAnalysis,
    LinguisticAnalyzer,
    UserMessageAnalysis,
)
from atman.core.services.divergence_detector import DivergenceDetector


class _StubAnalyzer(LinguisticAnalyzer):
    """LinguisticAnalyzer that returns a fixed AgentMessageAnalysis.

    The signals here map to DivergenceType.message_entity_gap via the detector's
    keyword matcher, and the cognitive_load_high flag triggers an extra event.
    """

    def __init__(
        self,
        *,
        divergence_signals: list[str] | None = None,
        cognitive_load_high: bool = False,
    ) -> None:
        self._signals = divergence_signals or []
        self._cog = cognitive_load_high

    def analyze_user_message(self, text: str) -> UserMessageAnalysis:  # type: ignore[override]
        return UserMessageAnalysis(text=text)

    def analyze_agent_message(  # type: ignore[override]
        self, message: str, *, thinking: str | None = None
    ) -> AgentMessageAnalysis:
        return AgentMessageAnalysis(
            divergence_signals=self._signals,
            cognitive_load_high=self._cog,
        )

    def analyze_key_moment(  # type: ignore[override]
        self, what_happened: str, why_it_matters: str
    ) -> KeyMomentAnalysis:
        return KeyMomentAnalysis()


@pytest.mark.asyncio
async def test_detector_persists_divergence_events_from_analysis(tmp_path: Path) -> None:
    agent_id = uuid4()
    store = InMemoryDivergenceEventStore()
    captured: list[KeyMoment] = []

    det = AffectDetector(
        AffectDetectorConfig(cold_start_sessions=0),
        workspace=tmp_path,
        append_moment=lambda _sid, km: captured.append(km),
        linguistic_analyzer=_StubAnalyzer(divergence_signals=["entity_gap_observed"]),
        divergence_detector=DivergenceDetector(agent_id),
        divergence_event_store=store,
    )
    sid = uuid4()
    await det.process(
        "agent said something but thinking was suppressed entirely from output",
        thinking="I noticed an entity that I did not mention in the output",
        session_id=sid,
    )

    # The divergence signal in the analysis produces one persisted event,
    # with agent_id + session_id attached for provenance.
    events = store.list_in_range(
        agent_id,
        datetime.now(UTC) - timedelta(minutes=1),
        datetime.now(UTC) + timedelta(minutes=1),
    )
    assert len(events) == 1
    assert events[0].agent_id == agent_id
    assert events[0].session_id == sid


@pytest.mark.asyncio
async def test_detector_silent_when_divergence_store_unavailable(tmp_path: Path) -> None:
    """Without store wiring, the detector still processes; no crash, no persistence."""
    captured: list[KeyMoment] = []
    det = AffectDetector(
        AffectDetectorConfig(cold_start_sessions=0),
        workspace=tmp_path,
        append_moment=lambda _sid, km: captured.append(km),
        linguistic_analyzer=_StubAnalyzer(divergence_signals=["entity_gap_observed"]),
        # no divergence_detector / divergence_event_store
    )
    await det.process("text long enough to pass min_length_gate", session_id=uuid4())
    # nothing to assert about the store — what we care about is that processing
    # did not raise even though no divergence pipeline was wired.


@pytest.mark.asyncio
async def test_detector_swallows_store_write_errors(tmp_path: Path) -> None:
    """A broken store must not abort message processing."""

    class _Boom:
        def write_event(self, *_a: Any, **_kw: Any) -> Any:
            raise RuntimeError("write failure")

    det = AffectDetector(
        AffectDetectorConfig(cold_start_sessions=0),
        workspace=tmp_path,
        append_moment=lambda _sid, _km: None,
        linguistic_analyzer=_StubAnalyzer(divergence_signals=["entity_gap_observed"]),
        divergence_detector=DivergenceDetector(uuid4()),
        divergence_event_store=_Boom(),
    )
    # If the wiring crashed callers, this would raise.
    await det.process(
        "agent said something but thinking suppressed",
        thinking="hidden trace",
        session_id=uuid4(),
    )


def test_factory_wires_divergence_pipeline_through_session_manager(tmp_path: Path) -> None:
    """build_deps should hand a DivergenceDetector + event store to AffectDetector
    via SessionManager so factory consumers don't need to construct the chain."""
    from atman.adapters.agent.factory import build_deps

    deps, session_manager, _store = build_deps(tmp_path, uuid4())
    assert deps is not None
    affect = session_manager.affect_detector
    assert affect is not None, "factory wires affect_detector by default"
    # Internal attributes are not public API but are the only handle we have
    # to confirm wiring without spinning a full session through the runtime.
    assert affect._linguistic_analyzer is not None  # type: ignore[attr-defined]
    assert affect._divergence_detector is not None  # type: ignore[attr-defined]
    assert affect._divergence_event_store is not None  # type: ignore[attr-defined]
