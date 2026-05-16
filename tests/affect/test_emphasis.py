"""Tests for markdown emphasis detection in AffectDetector."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from atman.affect.detector import AffectDetector, AffectDetectorConfig
from atman.affect.metrics import emphasis_signal, strip_markdown
from atman.affect.models import TriggerReason
from atman.core.models.experience import KeyMoment


def test_strip_markdown_double_asterisk() -> None:
    """Test **bold** markdown removal."""
    clean, emphasized = strip_markdown("**мой** блог")
    assert clean == "мой блог"
    assert emphasized == ["мой"]


def test_strip_markdown_double_underscore() -> None:
    """Test __bold__ markdown removal."""
    clean, emphasized = strip_markdown("This is __important__ text")
    assert clean == "This is important text"
    assert emphasized == ["important"]


def test_strip_markdown_no_bold() -> None:
    """Test text without bold markers."""
    clean, emphasized = strip_markdown("no bold here")
    assert clean == "no bold here"
    assert emphasized == []


def test_strip_markdown_multiple_bold() -> None:
    """Test multiple bold sections."""
    clean, emphasized = strip_markdown("**first** and **second** words")
    assert clean == "first and second words"
    assert emphasized == ["first", "second"]


def test_strip_markdown_mixed_markers() -> None:
    """Test mixed ** and __ markers."""
    clean, emphasized = strip_markdown("**asterisk** and __underscore__")
    assert clean == "asterisk and underscore"
    assert emphasized == ["asterisk", "underscore"]


def test_emphasis_signal_basic() -> None:
    """Test emphasis_signal generates correct metadata."""
    signal = emphasis_signal(["word1", "word2"])
    assert signal["emphasized_count"] == 2
    assert signal["emphasized_words"] == ["word1", "word2"]
    assert signal["total_chars"] == 10  # 5 + 5


def test_emphasis_signal_empty() -> None:
    """Test emphasis_signal with empty list."""
    signal = emphasis_signal([])
    assert signal["emphasized_count"] == 0
    assert signal["emphasized_words"] == []
    assert signal["total_chars"] == 0


@pytest.mark.asyncio
async def test_detector_emphasis_trigger_creates_key_moment(tmp_path: Path) -> None:
    """Test that text with emphasis creates affect:emphasis key_moment."""
    captured: list[KeyMoment] = []

    def sink(_sid: UUID, km: KeyMoment) -> None:
        captured.append(km)

    det = AffectDetector(
        AffectDetectorConfig(cold_start_sessions=0),
        workspace=tmp_path,
        append_moment=sink,
    )

    sid = UUID("018e5a2b-0000-0000-0000-000000000001")
    await det.process("This **слово** is important", session_id=sid)

    # Should have one emphasis key_moment
    emphasis_moments = [km for km in captured if "affect:emphasis" in km.values_touched]
    assert len(emphasis_moments) == 1

    km = emphasis_moments[0]
    meta = km.context_halo
    assert meta is not None
    assert meta.metadata["trigger_reason"] == TriggerReason.EMPHASIS.value
    assert "affect:emphasis" in meta.metadata["tags"]
    assert meta.metadata["says_writes"]["emphasized_words"] == ["слово"]


@pytest.mark.asyncio
async def test_detector_no_emphasis_no_trigger(tmp_path: Path) -> None:
    """Test that text without emphasis does not create affect:emphasis record."""
    captured: list[KeyMoment] = []

    def sink(_sid: UUID, km: KeyMoment) -> None:
        captured.append(km)

    det = AffectDetector(
        AffectDetectorConfig(cold_start_sessions=0),
        workspace=tmp_path,
        append_moment=sink,
    )

    sid = UUID("018e5a2b-0000-0000-0000-000000000002")
    await det.process("Plain text without bold", session_id=sid)

    # Should have no emphasis key_moments
    emphasis_moments = [km for km in captured if "affect:emphasis" in km.values_touched]
    assert len(emphasis_moments) == 0


@pytest.mark.asyncio
async def test_detector_emphasis_with_llm_analysis_logs_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """use_llm_analysis=True with emphasis input must not crash — HLE-23
    replaced the NotImplementedError with a logged warning so the emphasis
    pipeline keeps writing key moments even when the LLM classifier is
    unavailable."""
    captured: list[KeyMoment] = []

    def sink(_sid: UUID, km: KeyMoment) -> None:
        captured.append(km)

    det = AffectDetector(
        AffectDetectorConfig(cold_start_sessions=0, use_llm_analysis=True),
        workspace=tmp_path,
        append_moment=sink,
    )

    sid = UUID("018e5a2b-0000-0000-0000-000000000003")

    with caplog.at_level("WARNING", logger="atman.affect.detector"):
        await det.process("This **word** is emphasized", session_id=sid)
    assert any("emotion classification" in m.lower() for m in caplog.messages)


@pytest.mark.asyncio
async def test_detector_emphasis_stripped_before_metrics(tmp_path: Path) -> None:
    """Test that markdown is stripped before metric computation."""
    captured: list[KeyMoment] = []

    def sink(_sid: UUID, km: KeyMoment) -> None:
        captured.append(km)

    det = AffectDetector(
        AffectDetectorConfig(
            cold_start_sessions=0,
            random_sample_every_n=1,  # Always sample
        ),
        workspace=tmp_path,
        append_moment=sink,
    )

    sid = UUID("018e5a2b-0000-0000-0000-000000000004")
    # Text long enough to trigger metrics and has bold
    await det.process("**Important** message with sufficient length for analysis", session_id=sid)

    # Should have both emphasis and random-sample moments
    assert len(captured) >= 2
    emphasis_moments = [km for km in captured if "affect:emphasis" in km.values_touched]
    assert len(emphasis_moments) == 1

    # Check that demonstrates_thinks in emphasis record has signal
    km = emphasis_moments[0]
    meta = km.context_halo
    assert meta is not None
    demonstrates = meta.metadata.get("demonstrates_thinks")
    assert demonstrates is not None
    assert demonstrates["emphasized_count"] == 1
    assert demonstrates["emphasized_words"] == ["Important"]
