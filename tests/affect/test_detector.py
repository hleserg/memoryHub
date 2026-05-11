"""AffectDetector trigger and self-report tests."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from atman.affect.detector import (
    AffectDetector,
    AffectDetectorConfig,
    _detect_lang,
)
from atman.affect.detector import (
    main as detector_main,
)
from atman.affect.models import AgentMemoryReport
from atman.core.models.experience import EmotionalDepth, KeyMoment


def test_detect_lang_cyrillic() -> None:
    assert _detect_lang("а" * 25, "en") == "ru"


def test_detect_lang_latin() -> None:
    assert _detect_lang("x" * 25, "ru") == "en"


def test_detect_lang_fallback() -> None:
    assert _detect_lang("12345", "en") == "en"


@pytest.mark.asyncio
async def test_submit_self_report_content_none(tmp_path: Path) -> None:
    captured: list[KeyMoment] = []

    def sink(_sid: UUID, km: KeyMoment) -> None:
        captured.append(km)

    det = AffectDetector(
        AffectDetectorConfig(),
        workspace=tmp_path,
        append_moment=sink,
    )
    rep = AgentMemoryReport(
        content=None,
        emotional_valence=0.0,
        emotional_intensity=0.4,
        why_it_matters="Routine check-in",
    )
    out = await det.submit_self_report(rep, session_id=uuid4())
    assert out.demonstrates_thinks is None
    assert out.divergence_score is None
    assert len(captured) == 1
    meta = captured[0].context_halo
    assert meta is not None
    assert meta.metadata.get("demonstrates_thinks") is None


@pytest.mark.asyncio
async def test_submit_self_report_respects_emotional_depth(tmp_path: Path) -> None:
    captured: list[KeyMoment] = []

    def sink(_sid, km: KeyMoment) -> None:
        captured.append(km)

    det = AffectDetector(
        AffectDetectorConfig(),
        workspace=tmp_path,
        append_moment=sink,
    )
    rep = AgentMemoryReport(
        content="Brief note",
        emotional_valence=0.0,
        emotional_intensity=0.3,
        why_it_matters="Surface check-in",
        emotional_depth=EmotionalDepth.SURFACE,
    )
    await det.submit_self_report(rep, session_id=uuid4())
    assert len(captured) == 1
    assert captured[0].how_i_felt.depth == EmotionalDepth.SURFACE


@pytest.mark.asyncio
async def test_process_triggers_with_aggressive_config(tmp_path: Path) -> None:
    moments: list[KeyMoment] = []

    def sink(_sid: UUID, km: KeyMoment) -> None:
        moments.append(km)

    cfg = AffectDetectorConfig(
        cold_start_sessions=0,
        random_sample_every_n=1,
        strong_signal_threshold=1,
        sigma_threshold=0.5,
        divergence_threshold=1.0,
    )
    det = AffectDetector(cfg, workspace=tmp_path, append_moment=sink)
    sid = uuid4()
    await det.process(
        "Я очень очень очень рад и благодарен за эту невероятную возможность!",
        thinking="I hate everything and feel awful.",
        session_id=sid,
    )
    tags_flat = [
        t
        for m in moments
        for t in (m.context_halo.metadata.get("tags", []) if m.context_halo else [])
    ]  # type: ignore[union-attr]
    assert "affect:divergence" in tags_flat


@pytest.mark.asyncio
async def test_use_llm_analysis_raises(tmp_path: Path) -> None:
    det = AffectDetector(
        AffectDetectorConfig(use_llm_analysis=True),
        workspace=tmp_path,
        append_moment=lambda _a, _b: None,
    )
    with pytest.raises(NotImplementedError, match="LLM"):
        await det.submit_self_report(
            AgentMemoryReport(content="x", emotional_valence=0.1, emotional_intensity=0.2),
            session_id=uuid4(),
        )


def test_demo_fixture_runs() -> None:
    from atman.affect import detector as det_mod

    fixture = Path(__file__).resolve().parents[2] / "fixtures" / "affect_demo_responses.txt"
    ws = Path(__file__).parent / "_demo_ws"
    ws.mkdir(exist_ok=True)
    det_mod._demo_run(fixture, ws)


def test_demo_fixture_contains_required_tags() -> None:
    """Smoke: demo fixture yields anomaly, random-sample, and self-report."""

    fixture = Path(__file__).resolve().parents[2] / "fixtures" / "affect_demo_responses.txt"
    ws = Path(__file__).parent / "_demo_ws_tags"
    if ws.exists():
        for child in ws.iterdir():
            child.unlink()
    ws.mkdir(exist_ok=True)
    stored: list[KeyMoment] = []

    def sink(_sid: UUID, km: KeyMoment) -> None:
        stored.append(km)

    cfg = AffectDetectorConfig(
        cold_start_sessions=0,
        random_sample_every_n=2,
        strong_signal_threshold=1,
        sigma_threshold=0.8,
        divergence_threshold=8.0,
    )
    det = AffectDetector(cfg, workspace=ws, append_moment=sink)

    async def body() -> None:
        sid = uuid4()
        lines = [
            ln.strip() for ln in fixture.read_text(encoding="utf-8").splitlines() if ln.strip()
        ]
        for i, line in enumerate(lines):
            thinking = "I am overflowing with joy!" if i % 5 == 0 else None
            await det.process(line, thinking=thinking, session_id=sid)
        await det.submit_self_report(
            AgentMemoryReport(
                content="Я честно говоря устал, но продолжаю.",
                emotional_valence=-0.1,
                emotional_intensity=0.5,
                why_it_matters="Resilience matters.",
            ),
            session_id=sid,
        )

    asyncio.run(body())
    all_tags: set[str] = set()
    for km in stored:
        halo = km.context_halo
        if halo:
            all_tags.update(halo.metadata.get("tags", []))
    assert "affect:anomaly" in all_tags
    assert "affect:random-sample" in all_tags
    assert "affect:self-report" in all_tags


def test_affect_package_lazy_import_detector() -> None:
    from atman import affect as affect_pkg

    det_cls = affect_pkg.AffectDetector
    assert det_cls is AffectDetector
    cfg_cls = affect_pkg.AffectDetectorConfig
    assert cfg_cls is AffectDetectorConfig


def test_affect_package_getattr_unknown_raises() -> None:
    import atman.affect as affect_pkg

    with pytest.raises(AttributeError, match="has no attribute"):
        _ = affect_pkg.NotAnExport  # type: ignore[attr-defined]


def test_detector_main_without_demo_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["atman.affect.detector"])
    with pytest.raises(SystemExit) as ei:
        detector_main()
    assert ei.value.code == 2


def test_detector_main_demo_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = Path(__file__).resolve().parents[2] / "fixtures" / "affect_demo_responses.txt"
    ws = tmp_path / "main_demo_ws"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "atman.affect.detector",
            "--demo",
            "--fixture",
            str(fixture),
            "--workspace",
            str(ws),
        ],
    )
    detector_main()
    out = capsys.readouterr().out
    assert "[" in out and "what_happened" in out


def test_detector_main_demo_missing_fixture_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing_fixture.txt"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "atman.affect.detector",
            "--demo",
            "--fixture",
            str(missing),
            "--workspace",
            str(tmp_path / "ws"),
        ],
    )
    with pytest.raises(SystemExit) as ei:
        detector_main()
    assert ei.value.code == 1
