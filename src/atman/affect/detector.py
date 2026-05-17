"""AffectDetector orchestrates metrics, triggers, and key_moment writes."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from atman.affect.baseline import METRIC_KEYS, RollingBaseline
from atman.affect.emolex.emolex import emotion_score, tokenize
from atman.affect.metrics import (
    disclaimer_density,
    emotion_lexical_energy,
    emphasis_signal,
    hedge_density,
    length_anomaly_z,
    min_length_gate,
    negation_inversion_valence,
    nrc_emotion_score,
    nrc_emotion_vector,
    question_tail,
    self_reference_density,
    sincerity_score,
    strip_markdown,
)
from atman.affect.models import AffectMetrics, AffectRecord, AgentMemoryReport, TriggerReason
from atman.core.models.experience import ContextHalo, EmotionalDepth, FeltSense, KeyMoment
from atman.core.ports.linguistic import LinguisticAnalyzer

_LOG = logging.getLogger(__name__)


class AffectDetectorConfig(BaseModel):
    """Configuration for :class:`AffectDetector`."""

    default_lang: str = Field(default="ru", description="Fallback language for short strings")
    sigma_threshold: float = Field(default=2.0, ge=0.0)
    strong_signal_threshold: int = Field(default=2, ge=1)
    random_sample_every_n: int = Field(default=5, ge=1)
    divergence_threshold: float = Field(default=25.0, ge=0.0)
    cold_start_sessions: int = Field(default=10, ge=0)
    baseline_window: int = Field(default=200, ge=2)
    min_text_length: int = Field(default=12, ge=1)
    use_llm_analysis: bool = Field(
        default=False,
        description="Reserved; LLM sincerity path is not implemented",
    )


def _detect_lang(text: str, default_lang: str) -> str:
    sample = text[:100]
    cyr = sum(1 for ch in sample if "\u0400" <= ch <= "\u04ff")
    lat = sum(1 for ch in sample if "a" <= ch.lower() <= "z")
    if cyr >= 20:
        return "ru"
    if lat >= 20:
        return "en"
    return default_lang


def _valence_to_felt(nrc_valence: float, coverage: float) -> FeltSense:
    """Map NRC density-derived valence into FeltSense ranges."""
    v = max(-1.0, min(1.0, math.tanh(nrc_valence / 45.0)))
    intensity = max(0.0, min(1.0, abs(nrc_valence) / 55.0 + coverage / 120.0))
    depth = EmotionalDepth.MEANINGFUL if intensity > 0.35 else EmotionalDepth.SURFACE
    return FeltSense(emotional_valence=v, emotional_intensity=intensity, depth=depth)


class AffectDetector:
    """
    Computes behavioural metrics and appends tagged :class:`KeyMoment` rows.

    ``append_moment`` must be thread-safe (typically ``SessionManager.append_key_moment``).
    """

    def __init__(
        self,
        config: AffectDetectorConfig,
        *,
        workspace: Path,
        append_moment: Callable[[UUID, KeyMoment], None],
        linguistic_analyzer: LinguisticAnalyzer | None = None,
    ) -> None:
        self.config = config
        self._workspace = workspace
        self._append = append_moment
        self._linguistic_analyzer = linguistic_analyzer
        self._baseline = RollingBaseline(
            workspace / "affect_baseline.jsonl",
            window=config.baseline_window,
        )
        self._random_counter = 0
        self._session_index: dict[UUID, int] = {}

    def _session_order(self, session_id: UUID | None) -> int:
        if session_id is None:
            return 10**9
        if session_id not in self._session_index:
            self._session_index[session_id] = len(self._session_index) + 1
        return self._session_index[session_id]

    def _is_cold_start(self, session_id: UUID | None) -> bool:
        return self._session_order(session_id) <= self.config.cold_start_sessions

    @staticmethod
    def _metrics_vector(m: AffectMetrics) -> dict[str, float]:
        return {k: float(getattr(m, k)) for k in METRIC_KEYS}

    def _compute_metrics(self, text: str, lang: str) -> AffectMetrics:
        tokens = tokenize(text)
        nrc_v = nrc_emotion_score(text, lang)
        vec = nrc_emotion_vector(text, lang)
        energy = emotion_lexical_energy(vec)
        char_count = len(text.strip())
        mean_c, std_c = self._baseline.char_mean_std()
        length_z = length_anomaly_z(char_count, mean_c, std_c)
        neg_adj = negation_inversion_valence(text, lang, nrc_v)
        sinc = sincerity_score(text, tokens, lang)
        return AffectMetrics(
            nrc_valence=nrc_v,
            hedge_density=hedge_density(tokens, lang),
            length_z=length_z,
            question_tail_density=question_tail(text),
            self_reference_density=self_reference_density(tokens, lang),
            disclaimer_density=disclaimer_density(tokens, lang),
            negation_adjusted_valence=neg_adj,
            emotion_lexical_energy=energy,
            sincerity_score=sinc,
        )

    async def process(
        self,
        text: str,
        *,
        thinking: str | None = None,
        session_id: UUID | None = None,
    ) -> AffectRecord | None:
        """Analyse agent message text and optionally thinking; may append a key moment."""
        self._random_counter += 1

        # Strip markdown and extract emphasized words
        clean_text, emphasized = strip_markdown(text)

        if not min_length_gate(clean_text, self.config.min_text_length):
            return None

        lang = _detect_lang(clean_text, self.config.default_lang)
        raw_score = emotion_score(clean_text, lang=lang)
        coverage = float(raw_score.get("_meta", {}).get("coverage", 0.0))
        metrics = self._compute_metrics(clean_text, lang)
        vec = self._metrics_vector(metrics)
        z = self._baseline.z_scores(vec)

        char_count = len(clean_text.strip())
        self._baseline.update(vec, char_count=char_count, extra={"phase": "process"})

        # Handle emphasis trigger unconditionally if emphasized words present
        if emphasized:
            await self._handle_emphasis(
                emphasized=emphasized,
                clean_text=clean_text,
                lang=lang,
                session_id=session_id,
            )

        tags: list[str] = []
        reasons: list[TriggerReason] = []
        divergence: float | None = None

        cold = self._is_cold_start(session_id)

        if thinking and thinking.strip():
            t_lang = _detect_lang(thinking, self.config.default_lang)
            m_score = metrics.nrc_valence
            th_score = nrc_emotion_score(thinking, t_lang)
            divergence = abs(m_score - th_score)
            if not cold and divergence > self.config.divergence_threshold:
                tags.append("affect:divergence")
                reasons.append(TriggerReason.DIVERGENCE)

        # Linguistic enrichment: when a LinguisticAnalyzer is wired in, run a
        # full agent-message analysis so downstream code (e.g. DivergenceDetector)
        # can consume the structured result.  The analysis is stored on the
        # AffectRecord via demonstrates_thinks if no other value has been set.
        # TODO(injection-point): merge analysis.divergence_signals into tags /
        # reasons and pass analysis to _append_key_moment for structured_markers
        # enrichment once KeyMomentBuilder is integrated into the affect pipeline.
        _linguistic_analysis = None
        if self._linguistic_analyzer is not None:
            try:
                _linguistic_analysis = self._linguistic_analyzer.analyze_agent_message(
                    message=clean_text,
                    thinking=thinking if thinking and thinking.strip() else None,
                )
            except Exception:
                _LOG.warning("LinguisticAnalyzer failed; continuing without it", exc_info=True)

        if not cold:
            strong = sum(1 for k in METRIC_KEYS if abs(z.get(k, 0.0)) > self.config.sigma_threshold)
            if strong >= self.config.strong_signal_threshold:
                tags.append("affect:anomaly")
                reasons.append(TriggerReason.ANOMALY)
            if self._random_counter % self.config.random_sample_every_n == 0:
                tags.append("affect:random-sample")
                reasons.append(TriggerReason.RANDOM_SAMPLE)

        if not tags:
            return None

        if TriggerReason.DIVERGENCE in reasons:
            primary = TriggerReason.DIVERGENCE
        elif TriggerReason.ANOMALY in reasons:
            primary = TriggerReason.ANOMALY
        else:
            primary = TriggerReason.RANDOM_SAMPLE
        excerpt = clean_text.strip()[:500]
        says_writes = {"text_excerpt": excerpt, "lang": lang}
        demonstrates = metrics.model_dump()
        felt = _valence_to_felt(metrics.nrc_valence, coverage)
        record = AffectRecord(
            trigger_reason=primary,
            tags=tags,
            says_writes=says_writes,
            demonstrates_thinks=demonstrates,
            divergence_score=divergence,
        )
        if session_id is not None:
            self._append_key_moment(session_id, excerpt, felt, record)
        return record

    async def _handle_emphasis(
        self,
        *,
        emphasized: list[str],
        clean_text: str,
        lang: str,
        session_id: UUID | None,
    ) -> None:
        """Handle emphasis detection: write key_moment and optionally trigger LLM analysis."""
        signal = emphasis_signal(emphasized)
        excerpt = clean_text.strip()[:500]
        says_writes = {
            "text_excerpt": excerpt,
            "lang": lang,
            "emphasized_words": emphasized,
        }

        # Neutral felt sense for emphasis trigger
        felt = FeltSense(
            emotional_valence=0.0,
            emotional_intensity=0.5,
            depth=EmotionalDepth.SURFACE,
        )

        record = AffectRecord(
            trigger_reason=TriggerReason.EMPHASIS,
            tags=["affect:emphasis"],
            says_writes=says_writes,
            demonstrates_thinks=signal,
        )

        if session_id is not None:
            self._append_key_moment(session_id, excerpt, felt, record)

        # LLM emotion classification (reserved — logs and continues so callers aren't broken)
        if self.config.use_llm_analysis:
            _LOG.warning(
                "use_llm_analysis=True is reserved; LLM emotion classification not yet implemented"
            )

    def _append_key_moment(
        self,
        session_id: UUID,
        excerpt: str,
        felt: FeltSense,
        record: AffectRecord,
    ) -> None:
        meta: dict[str, Any] = {
            "tags": record.tags,
            "trigger_reason": record.trigger_reason.value,
            "says_writes": record.says_writes,
            "demonstrates_thinks": record.demonstrates_thinks,
            "divergence_score": record.divergence_score,
        }
        km = KeyMoment(
            what_happened=excerpt if excerpt else "[affect:detector]",
            when=datetime.now(UTC),
            how_i_felt=felt,
            why_it_matters=f"AffectDetector tagged moment ({record.trigger_reason.value}).",
            values_touched=list(dict.fromkeys(record.tags)),
            context_halo=ContextHalo(description="atman:affect-detector", metadata=meta),
        )
        self._append(session_id, km)

    async def submit_self_report(
        self,
        report: AgentMemoryReport,
        *,
        session_id: UUID | None = None,
    ) -> AffectRecord:
        """Agent-originated memory with optional objective enrichment."""
        if self.config.use_llm_analysis:
            _LOG.warning(
                "use_llm_analysis=True is reserved; LLM sincerity path not yet implemented"
            )

        tags = list(dict.fromkeys([*report.tags, "affect:self-report"]))
        demonstrates: dict[str, Any] | None = None
        divergence: float | None = None
        lang = _detect_lang(report.content or "", self.config.default_lang)

        if report.content and report.content.strip():
            metrics = self._compute_metrics(report.content.strip(), lang)
            vec = self._metrics_vector(metrics)
            self._baseline.update(
                vec,
                char_count=len(report.content.strip()),
                extra={"phase": "self_report"},
            )
            demonstrates = metrics.model_dump()
            obj_v = max(-1.0, min(1.0, math.tanh(metrics.nrc_valence / 45.0)))
            divergence = abs(float(report.emotional_valence) - obj_v)

        depth = report.emotional_depth or EmotionalDepth.MEANINGFUL
        felt = FeltSense(
            emotional_valence=report.emotional_valence,
            emotional_intensity=report.emotional_intensity,
            depth=depth,
        )
        what = (
            report.content.strip()[:500]
            if report.content and report.content.strip()
            else "[affect:self-report:no-content]"
        )
        why = report.why_it_matters or "Self-reported memory captured by AffectDetector."
        record = AffectRecord(
            trigger_reason=TriggerReason.SELF_REPORT,
            tags=tags,
            says_writes={
                "self_reported_emotions": report.self_reported_emotions,
                "emotional_valence": report.emotional_valence,
                "emotional_intensity": report.emotional_intensity,
                "content_excerpt": (report.content or "")[:500] or None,
            },
            demonstrates_thinks=demonstrates,
            divergence_score=divergence,
        )
        meta: dict[str, Any] = {
            "tags": record.tags,
            "trigger_reason": record.trigger_reason.value,
            "says_writes": record.says_writes,
            "demonstrates_thinks": record.demonstrates_thinks,
            "divergence_score": record.divergence_score,
        }
        km = KeyMoment(
            what_happened=what,
            when=datetime.now(UTC),
            how_i_felt=felt,
            why_it_matters=why,
            values_touched=list(dict.fromkeys(tags)),
            context_halo=ContextHalo(description="atman:affect-detector", metadata=meta),
        )
        if session_id is not None:
            self._append(session_id, km)
        return record


def _demo_run(fixture: Path, workspace: Path) -> None:
    rows: list[str] = []
    with fixture.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(line)
    stored: list[KeyMoment] = []

    def sink(_sid: UUID, km: KeyMoment) -> None:
        stored.append(km)

    cfg = AffectDetectorConfig(
        cold_start_sessions=0,
        random_sample_every_n=3,
        strong_signal_threshold=1,
        sigma_threshold=1.0,
        divergence_threshold=5.0,
    )
    det = AffectDetector(cfg, workspace=workspace, append_moment=sink)

    async def body() -> None:
        sid = UUID("018e5a2b-7c3d-7b2a-9f01-2a3b4c5d6e7f")
        for i, line in enumerate(rows):
            thinking = "I am extremely joyful and grateful!" if i % 7 == 0 else None
            await det.process(line, thinking=thinking, session_id=sid)
        await det.submit_self_report(
            AgentMemoryReport(
                content="Я честно признаюсь: мне было трудно, но я справился.",
                emotional_valence=0.2,
                emotional_intensity=0.6,
                why_it_matters="Honesty about difficulty matters to me.",
            ),
            session_id=sid,
        )

    asyncio.run(body())
    print(json.dumps([km.model_dump(mode="json") for km in stored], ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="AffectDetector demo runner")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Run the bundled synthetic fixture through the detector and print key_moments JSON",
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "fixtures" / "affect_demo_responses.txt",
    )
    parser.add_argument("--workspace", type=Path, default=Path.cwd() / ".affect_demo_workspace")
    args = parser.parse_args()
    if not args.demo:
        parser.print_help()
        sys.exit(2)
    if not args.fixture.exists():
        print(f"Fixture not found: {args.fixture}", file=sys.stderr)
        sys.exit(1)
    _demo_run(args.fixture, args.workspace)


if __name__ == "__main__":
    main()
