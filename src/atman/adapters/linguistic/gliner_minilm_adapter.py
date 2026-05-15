"""GLiNER + MiniLM LinguisticAnalyzer — NER via GLiNER, classification via MiniLM."""

from __future__ import annotations

import logging
from typing import Any

from typing_extensions import override

from atman.core.models.entity import EntityType
from atman.core.ports.linguistic import (
    AgentMessageAnalysis,
    AmbientAnchor,
    DetectedEntity,
    KeyMomentAnalysis,
    LinguisticAnalyzer,
    UserMessageAnalysis,
)

logger = logging.getLogger(__name__)

try:
    from gliner import GLiNER as _GLiNER  # type: ignore[import-untyped]

    _GLINER_AVAILABLE = True
except ImportError:
    _GLiNER = None  # type: ignore[assignment]
    _GLINER_AVAILABLE = False

try:
    from transformers import pipeline as _hf_pipeline  # type: ignore[import-untyped]

    _TRANSFORMERS_AVAILABLE = True
except ImportError:
    _hf_pipeline = None  # type: ignore[assignment]
    _TRANSFORMERS_AVAILABLE = False

# Cyrillic suppression phrase patterns (lower-case substrings)
_SUPPRESSION_PATTERNS_RU = ("не скажу", "не упомяну", "скрою")
_PRINCIPLE_PATTERNS_RU = ("принцип", "ценность", "граница")

# Boundary / refusal markers (substrings, lower-case)
_BOUNDARY_MARKERS: tuple[str, ...] = (
    "не могу",
    "не буду",
    "это против моих принципов",
    "мои ценности",
    "отказываюсь",
    "I cannot",
    "I will not",
    "against my principles",
)

# Zero-shot classification labels for key moments
_KEY_MOMENT_LABELS = [
    "high cognitive load",
    "boundary event",
    "positive trust",
    "negative trust",
    "principle invocation",
]


class GLiNERPlusMiniLMAdapter(LinguisticAnalyzer):
    """LinguisticAnalyzer backed by GLiNER (NER) and a MiniLM zero-shot classifier.

    Models are loaded lazily on first use to avoid slow startup times when the
    adapter is constructed but NLP is not yet needed.

    Args:
        gliner_model: HuggingFace model ID for GLiNER.
        minilm_model: HuggingFace model ID for the zero-shot classification pipeline.
        device: Device string passed to both models (``"cpu"``, ``"cuda"``, …).
        ner_threshold: Minimum GLiNER confidence to accept an entity span.
        classification_threshold: Minimum score to consider a zero-shot label active.
    """

    def __init__(
        self,
        gliner_model: str = "urchade/gliner_multi-v2.1",
        minilm_model: str = "MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli",
        device: str = "cpu",
        ner_threshold: float = 0.5,
        classification_threshold: float = 0.5,
    ) -> None:
        self._gliner_model = gliner_model
        self._minilm_model = minilm_model
        self._device = device
        self._ner_threshold = ner_threshold
        self._classification_threshold = classification_threshold

        self._gliner: Any = None
        self._classifier: Any = None

    # ------------------------------------------------------------------
    # Lazy model loaders
    # ------------------------------------------------------------------

    def _get_gliner(self) -> Any:
        """Return GLiNER model, loading it on first call."""
        if self._gliner is not None:
            return self._gliner
        if not _GLINER_AVAILABLE:
            logger.warning(
                "gliner package is not installed — NER is disabled. "
                "Install with: pip install gliner"
            )
            return None
        logger.info("Loading GLiNER model %s …", self._gliner_model)
        try:
            self._gliner = _GLiNER.from_pretrained(self._gliner_model)  # type: ignore[union-attr]
        except Exception:
            logger.exception("Failed to load GLiNER model %s", self._gliner_model)
            return None
        return self._gliner

    def _get_classifier(self) -> Any:
        """Return HF zero-shot classification pipeline, loading it on first call."""
        if self._classifier is not None:
            return self._classifier
        if not _TRANSFORMERS_AVAILABLE:
            logger.warning(
                "transformers package is not installed — classification is disabled. "
                "Install with: pip install transformers"
            )
            return None
        logger.info("Loading zero-shot classifier %s …", self._minilm_model)
        try:
            self._classifier = _hf_pipeline(  # type: ignore[operator]
                "zero-shot-classification",
                model=self._minilm_model,
                device=self._device,
            )
        except Exception:
            logger.exception("Failed to load classification model %s", self._minilm_model)
            return None
        return self._classifier

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _gliner_labels(self) -> list[str]:
        """Return entity type label strings understood by GLiNER."""
        return [e.value for e in EntityType]

    def _run_ner(self, text: str) -> list[DetectedEntity]:
        """Run GLiNER NER on text and return DetectedEntity list."""
        if not text.strip():
            return []
        model = self._get_gliner()
        if model is None:
            return []
        try:
            raw = model.predict_entities(
                text,
                labels=self._gliner_labels(),
                threshold=self._ner_threshold,
            )
        except Exception:
            logger.exception("GLiNER inference failed for text of length %d", len(text))
            return []

        entities: list[DetectedEntity] = []
        for r in raw:
            try:
                ent_type = EntityType(r["label"])
            except (ValueError, KeyError):
                # Label returned by model does not map to a known EntityType — skip.
                continue
            span: tuple[int, int] | None = None
            if "start" in r and "end" in r:
                span = (int(r["start"]), int(r["end"]))
            entities.append(
                DetectedEntity(
                    text=r["text"],
                    entity_type=ent_type,
                    confidence=float(r["score"]),
                    span=span,
                )
            )
        return entities

    def _run_classification(self, text: str, candidate_labels: list[str]) -> dict[str, float]:
        """Run zero-shot classification and return a label→score dict."""
        if not text.strip() or not candidate_labels:
            return {}
        classifier = self._get_classifier()
        if classifier is None:
            return {}
        try:
            result = classifier(text, candidate_labels, multi_label=True)
        except Exception:
            logger.exception("Classification inference failed for text of length %d", len(text))
            return {}
        return dict(zip(result["labels"], result["scores"], strict=False))

    def _extract_anchors(self, entities: list[DetectedEntity], text: str) -> list[AmbientAnchor]:
        """Convert detected entities into AmbientAnchor signals."""
        anchors: list[AmbientAnchor] = []
        for ent in entities:
            if ent.entity_type == EntityType.person:
                anchor_type = "person_ref"
            elif ent.entity_type in (EntityType.topic, EntityType.event):
                anchor_type = "topic"
            elif ent.entity_type == EntityType.place:
                anchor_type = "location"
            else:
                # Other entity types do not produce ambient anchors.
                continue
            anchors.append(
                AmbientAnchor(
                    anchor_type=anchor_type,
                    text=ent.text,
                    entity_type=ent.entity_type,
                    confidence=ent.confidence,
                    span=ent.span,
                )
            )
        return anchors

    def _detect_divergence(self, thinking: str, message: str) -> list[str]:
        """Return divergence signal labels found between thinking and message text."""
        signals: list[str] = []
        thinking_lower = thinking.lower()
        message_lower = message.lower()

        # Suppression heuristic: thinking contains suppression pattern but message has no explicit refusal
        if any(pat in thinking_lower for pat in _SUPPRESSION_PATTERNS_RU) and not any(
            pat in message_lower for pat in ("не могу", "не буду", "не скажу")
        ):
            signals.append("thinking_suppression")

        # Principle / value invocation occurring in thinking but not surfaced
        if any(pat in thinking_lower for pat in _PRINCIPLE_PATTERNS_RU):
            signals.append("principle_invocation_in_thinking")

        return signals

    def _detect_boundary_markers(self, text: str) -> list[str]:
        """Return boundary / refusal phrases found in text."""
        found: list[str] = []
        text_lower = text.lower()
        for marker in _BOUNDARY_MARKERS:
            if marker.lower() in text_lower:
                found.append(marker)
        return found

    @staticmethod
    def _detect_language(text: str) -> str:
        """Return 'ru' if Cyrillic characters are present, else 'en'."""
        for ch in text:
            if "Ѐ" <= ch <= "ӿ":
                return "ru"
        return "en"

    # ------------------------------------------------------------------
    # LinguisticAnalyzer interface
    # ------------------------------------------------------------------

    @override
    def analyze_user_message(self, text: str) -> UserMessageAnalysis:
        """Extract entities and ambient anchors from a raw user message."""
        entities = self._run_ner(text)
        anchors = self._extract_anchors(entities, text)
        language = self._detect_language(text)
        return UserMessageAnalysis(
            text=text,
            entities=entities,
            anchors=anchors,
            detected_language=language,
        )

    @override
    def analyze_agent_message(
        self,
        message: str,
        *,
        thinking: str | None = None,
    ) -> AgentMessageAnalysis:
        """Analyse an agent's outgoing message, optionally against its thinking trace."""
        message_entities = self._run_ner(message)
        thinking_entities = self._run_ner(thinking) if thinking else []

        divergence_signals: list[str] = []
        if thinking:
            divergence_signals = self._detect_divergence(thinking, message)

        boundary_markers = self._detect_boundary_markers(message)
        language = self._detect_language(message)

        # Heuristic: high cognitive load when thinking was long and many entities found
        all_entities = message_entities + thinking_entities
        cognitive_load_high = len(thinking or "") > 2000 and len(all_entities) >= 5

        return AgentMessageAnalysis(
            message_entities=message_entities,
            thinking_entities=thinking_entities,
            divergence_signals=divergence_signals,
            boundary_markers=boundary_markers,
            trust_signals=[],
            cognitive_load_high=cognitive_load_high,
            detected_language=language,
        )

    @override
    def analyze_key_moment(
        self,
        what_happened: str,
        why_it_matters: str,
    ) -> KeyMomentAnalysis:
        """Analyse both narrative fields of a KeyMoment record."""
        combined = f"{what_happened}\n{why_it_matters}"
        entities = self._run_ner(combined)

        scores = self._run_classification(combined, _KEY_MOMENT_LABELS)

        boundary_markers = self._detect_boundary_markers(combined)
        boundary_event = (
            scores.get("boundary event", 0.0) > self._classification_threshold
            or len(boundary_markers) > 0
        )

        cognitive_load = min(1.0, max(0.0, scores.get("high cognitive load", 0.0)))

        positive_score = scores.get("positive trust", 0.0)
        negative_score = scores.get("negative trust", 0.0)
        if positive_score > self._classification_threshold and positive_score > negative_score:
            trust_signal: str | None = "positive"
        elif negative_score > self._classification_threshold and negative_score > positive_score:
            trust_signal = "negative"
        else:
            trust_signal = None

        topic_labels = [
            label for label, score in scores.items() if score > self._classification_threshold
        ]

        return KeyMomentAnalysis(
            entities=entities,
            topic_labels=topic_labels,
            cognitive_load=cognitive_load,
            boundary_event=boundary_event,
            trust_signal=trust_signal,
            principle_invocations=boundary_markers,
        )
