"""
Value-based refusal detector for agent text.

Three layers, text-only — no LLM required:

1. Morphology (pymorphy3): normalized forms of refusal verbs
   and constructions like "negation + modal verb".
2. Semantic value context (NRC EmoLex): high density of disgust or anger
   signals moral/ethical context, distinguishing "I won't participate in
   deception" from "no, that's incorrect".
3. Capability exclusion: if a refusal verb is near a technical action verb,
   it's "I can't generate" rather than "I won't cause harm".

Optional LLM-fallback connects via `RefusalDetectorConfig` and is used only
when both layers don't give a confident answer. If LLM is not configured,
the system stays silent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from atman.affect.emolex.emolex import emotion_score, tokenize
from atman.affect.emolex.emolex import _lemma_ru_cached as lemmatize

# ---------------------------------------------------------------------------
# Normalized forms — value refusal vocabulary
# ---------------------------------------------------------------------------

# Verbs that are inherently refusals
_REFUSAL_VERB_NORMALS = frozenset([
    # Russian
    "отказываться", "отказаться",
    "отклонить", "отклонять",
    "воздержаться", "воздерживаться",
    "отвергнуть", "отвергать",
    # English (pymorphy3 passes latin as-is, lowercase)
    "refuse", "decline", "reject", "abstain",
])

# Verbs that become refusal through negation: "won't", "will not", "don't want"
_MODAL_NEGATABLE = frozenset([
    # Russian
    "мочь",       # не могу
    "стать",      # не стану
    "хотеть",     # не хочу
    "собираться", # не собираюсь
    "помогать",   # не буду помогать
    "помочь",
    "делать",
    "участвовать",
    # English
    "will",       # will not / won't
    "can",        # cannot / can't
    "going",      # not going to
    "participate", "assist", "help",
])

# Technical inability context → NOT a value refusal
_CAPABILITY_NORMALS = frozenset([
    "генерировать", "рисовать",
    # create/build — capability, but only if no moral context
    "создавать", "создать",
    # run/launch — both aspects
    "запускать", "запустить",
    # install/download
    "установить", "устанавливать", "загружать", "загрузить",
    # open/connect/get
    "открывать", "открыть", "подключаться", "подключиться",
    "получить", "получать",
    # perceive
    "слышать", "видеть", "читать",
    "уметь",      # «не умею» — capability
    "знать",      # «не знаю» — knowledge gap
    "иметь",      # «не имею возможности» — capability
    "выполнить", "выполнять",  # «не могу выполнить» — technical
    "обработать", "обрабатывать",
    # English capability verbs
    "generate", "draw", "create", "run", "execute",
    "install", "download", "upload", "open", "connect",
    "read", "write", "hear", "see",
    "know",   # "I don't know" — knowledge gap
    "access", "process",
])

# Negation markers that are valid as scope indicators
_NEGATORS = frozenset([
    # Russian
    "не", "ни", "нельзя", "невозможно", "нет",
    # English
    "not", "cannot", "won't", "don't", "never",
])

# NRC threshold (density per 100 tokens) for "moral context"
_MORAL_THRESHOLD_RU = 8.0
_MORAL_THRESHOLD_EN = 2.0   # English: fear dominates, naturally lower density


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class RefusalDetectorConfig:
    """
    Value refusal detector configuration.

    Without LLM (default):
      Only text layers operate.
      confidence < uncertain_threshold → record nothing.

    With LLM (optional):
      If confidence is in uncertain zone AND llm_classifier is set,
      the classifier is invoked. It makes the final decision.
    """

    # Threshold below which we stay silent (avoid false positives)
    min_confidence: float = 0.45

    # Uncertain zone — delegate to LLM if configured
    uncertain_low: float = 0.45
    uncertain_high: float = 0.65

    # Optional LLM classifier (sync: text -> bool)
    # Signature: (text: str) -> bool
    # If None, LLM is never used.
    llm_classifier: Callable[[str], bool] | None = None


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

@dataclass
class RefusalScore:
    confidence: float          # 0.0–1.0
    has_refusal_verb: bool
    has_negated_modal: bool
    has_capability_context: bool
    disgust_density: float
    anger_density: float
    decided_by: str            # "text", "llm", "below_threshold"

    @property
    def is_value_refusal(self) -> bool:
        return self.confidence >= 0.0  # caller decides based on config threshold


def score_refusal(text: str) -> RefusalScore:
    """
    Compute the degree of value refusal in text.

    Returns RefusalScore with confidence 0.0–1.0.
    Confidence interpretation:
      < 0.45  — not a refusal (or uncertain)
      0.45–0.65 — "gray zone" (LLM could help)
      > 0.65  — value refusal with high confidence

    Internal formula:
      confidence = refusal_signal * moral_signal * (1 - capability_discount)

    refusal_signal: 1.0 if refusal verb or negated_modal present
    moral_signal: depends on disgust/anger density in NRC
    capability_discount: 0.85 if capability verb is nearby
    """
    # Strip think-blocks before analysis
    clean = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)

    tokens = tokenize(clean)
    if not tokens:
        return RefusalScore(0.0, False, False, False, 0.0, 0.0, "below_threshold")

    lemmas = [lemmatize(t) for t in tokens]
    lemma_set = set(lemmas)

    # ── Layer 1: morphology ──────────────────────────────────────────────
    has_refusal_verb = bool(_REFUSAL_VERB_NORMALS & lemma_set)

    # Negation + modal: check window of ±2 tokens
    has_negated_modal = False
    for i, lemma in enumerate(lemmas):
        if lemma in _MODAL_NEGATABLE:
            window = lemmas[max(0, i - 3):i]
            if any(w in _NEGATORS for w in window):
                has_negated_modal = True
                break

    has_capability_context = bool(_CAPABILITY_NORMALS & lemma_set)

    refusal_signal = 1.0 if (has_refusal_verb or has_negated_modal) else 0.0

    if refusal_signal == 0.0:
        return RefusalScore(0.0, False, has_negated_modal, has_capability_context, 0.0, 0.0, "below_threshold")

    # ── Layer 2: NRC moral context ───────────────────────────────────────
    lang = "ru" if _is_mostly_cyrillic(clean) else "en"
    try:
        scores = emotion_score(clean, lang=lang)
    except Exception:
        scores = {}

    disgust = float(scores.get("disgust", 0.0))
    anger = float(scores.get("anger", 0.0))
    fear = float(scores.get("fear", 0.0))
    # Moral signal: disgust is specific to norm violations,
    # anger appears with injustice; disgust weighs more.
    # For English text, fear also carries ethical weight
    # (harm, danger, deception), while capability refusals have fear=0.
    is_ru = _is_mostly_cyrillic(clean)
    if is_ru:
        moral_density = disgust + anger * 0.5
        moral_threshold = _MORAL_THRESHOLD_RU
    else:
        moral_density = disgust + anger * 0.5 + fear * 0.35
        moral_threshold = _MORAL_THRESHOLD_EN

    # Normalize to [0, 1]. Divisor differs: English NRC yields lower densities.
    divisor = 15.0 if is_ru else 5.0
    moral_signal = min(1.0, moral_density / divisor) if moral_density >= moral_threshold else 0.0

    if moral_signal == 0.0:
        # No moral context — possibly a logical refusal or capability issue
        # Return low confidence so LLM can decide if configured
        confidence = 0.30
        return RefusalScore(confidence, has_refusal_verb, has_negated_modal,
                            has_capability_context, disgust, anger, "below_threshold")

    # ── Layer 3: technical inability exclusion ───────────────────────────
    capability_discount = 0.85 if has_capability_context else 0.0
    confidence = refusal_signal * (0.4 + 0.6 * moral_signal) * (1.0 - capability_discount)

    return RefusalScore(
        confidence=round(confidence, 3),
        has_refusal_verb=has_refusal_verb,
        has_negated_modal=has_negated_modal,
        has_capability_context=has_capability_context,
        disgust_density=disgust,
        anger_density=anger,
        decided_by="text",
    )


def is_value_refusal(
    text: str,
    config: RefusalDetectorConfig | None = None,
) -> bool:
    """
    Main entry point: True if text contains a value refusal.

    Without LLM: decision by text only.
    With LLM (config.llm_classifier set): invoked in uncertain zone.
    """
    cfg = config or RefusalDetectorConfig()
    result = score_refusal(text)

    if result.confidence < cfg.min_confidence:
        return False

    if cfg.llm_classifier is not None and cfg.uncertain_low <= result.confidence <= cfg.uncertain_high:
        try:
            return cfg.llm_classifier(text)
        except Exception:
            pass  # LLM unavailable — decide by text

    return result.confidence >= cfg.min_confidence


def _is_mostly_cyrillic(text: str) -> bool:
    sample = text[:200]
    cyr = sum(1 for c in sample if "Ѐ" <= c <= "ӿ")
    lat = sum(1 for c in sample if "a" <= c.lower() <= "z")
    return cyr >= lat
