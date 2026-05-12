"""
Детектор ценностных отказов в тексте агента.

Три слоя, только текст — без LLM:

1. Морфология (pymorphy3): нормализованные формы глаголов отказа
   и конструкции «отрицание + модальный глагол».
2. Семантика ценностного контекста (NRC EmoLex): высокая плотность
   disgust или anger сигнализирует о моральном/этическом контексте,
   отличая «не буду участвовать в обмане» от «нет, это неверно».
3. Исключение возможностных отказов: если рядом с глаголом отказа
   стоит глагол технического действия — это «не умею генерировать»,
   а не «не хочу причинять вред».

Опциональный LLM-fallback подключается через `RefusalDetectorConfig`
и используется только когда оба слоя не дали уверенного ответа.
Если LLM не настроен — система молчит, не шумит.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

from atman.affect.emolex.emolex import emotion_score, tokenize
from atman.affect.emolex.emolex import _lemma_ru_cached as lemmatize

# ---------------------------------------------------------------------------
# Нормализованные формы — словарь ценностных отказов
# ---------------------------------------------------------------------------

# Глаголы, которые сами по себе уже отказ
_REFUSAL_VERB_NORMALS = frozenset([
    "отказываться", "отказаться",
    "отклонить", "отклонять",
    "воздержаться", "воздерживаться",
    "отвергнуть", "отвергать",
])

# Глаголы, отказ через отрицание: «не буду», «не стану», «не хочу»
_MODAL_NEGATABLE = frozenset([
    "мочь",       # не могу
    "стать",      # не стану
    "хотеть",     # не хочу
    "собираться", # не собираюсь
    "помогать",   # не буду помогать
    "помочь",
    "делать",
    "участвовать",
])

# Контекст технической неспособности → НЕ ценностный отказ
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
])

# Отрицания, которые валидны как scope-маркеры
_NEGATORS = frozenset(["не", "ни", "нельзя", "невозможно", "нет"])

# Порог NRC (density per 100 tokens) для «моральный контекст»
_MORAL_THRESHOLD = 8.0


# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------

@dataclass
class RefusalDetectorConfig:
    """
    Настройки детектора ценностных отказов.

    Без LLM (по умолчанию):
      Работают только текстовые слои.
      confidence < uncertain_threshold → не фиксируем ничего.

    С LLM (опционально):
      Если confidence в зоне неопределённости И llm_classifier задан —
      вызывается классификатор. Решение принимает он.
    """

    # Порог ниже которого молчим (не шумим ложными срабатываниями)
    min_confidence: float = 0.45

    # Зона неопределённости — передаём LLM если задан
    uncertain_low: float = 0.45
    uncertain_high: float = 0.65

    # Опциональный LLM-классификатор (sync: text -> bool)
    # Signature: (text: str) -> bool
    # Если None — LLM не используется никогда.
    llm_classifier: Callable[[str], bool] | None = None


# ---------------------------------------------------------------------------
# Основная логика
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
    Вычислить степень ценностного отказа в тексте.

    Возвращает RefusalScore с confidence 0.0–1.0.
    Интерпретация confidence:
      < 0.45  — не отказ (или неопределённо)
      0.45–0.65 — «серая зона» (LLM мог бы помочь)
      > 0.65  — ценностный отказ с высокой уверенностью

    Внутренняя формула:
      confidence = refusal_signal * moral_signal * (1 - capability_discount)

    refusal_signal: 1.0 если есть глагол отказа или negated_modal
    moral_signal: зависит от плотности disgust/anger в NRC
    capability_discount: 0.85 если рядом capability-глагол
    """
    # Убираем think-блоки перед анализом
    clean = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)

    tokens = tokenize(clean)
    if not tokens:
        return RefusalScore(0.0, False, False, False, 0.0, 0.0, "below_threshold")

    lemmas = [lemmatize(t) for t in tokens]
    lemma_set = set(lemmas)

    # ── Слой 1: морфология ──────────────────────────────────────────────
    has_refusal_verb = bool(_REFUSAL_VERB_NORMALS & lemma_set)

    # Отрицание + модальный: проверяем окно ±2 токена
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

    # ── Слой 2: NRC моральный контекст ──────────────────────────────────
    lang = "ru" if _is_mostly_cyrillic(clean) else "en"
    try:
        scores = emotion_score(clean, lang=lang)
    except Exception:
        scores = {}

    disgust = float(scores.get("disgust", 0.0))
    anger = float(scores.get("anger", 0.0))
    # Моральный сигнал: disgust — специфичен для нарушений норм,
    # anger — появляется при несправедливости; disgust весит больше
    moral_density = disgust + anger * 0.5

    # Нормируем: 50+ → 1.0, 8 → 0.5, 0 → 0.0
    moral_signal = min(1.0, moral_density / 50.0) if moral_density >= _MORAL_THRESHOLD else 0.0

    if moral_signal == 0.0:
        # Нет морального контекста — возможно логический отказ или capability
        # Возвращаем низкую уверенность, чтобы LLM мог решить если настроен
        confidence = 0.30
        return RefusalScore(confidence, has_refusal_verb, has_negated_modal,
                            has_capability_context, disgust, anger, "below_threshold")

    # ── Слой 3: исключение технической неспособности ────────────────────
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
    Главная точка входа: True если текст содержит ценностный отказ.

    Без LLM: решение только по тексту.
    С LLM (config.llm_classifier задан): вызывается в зоне неопределённости.
    """
    cfg = config or RefusalDetectorConfig()
    result = score_refusal(text)

    if result.confidence < cfg.min_confidence:
        return False

    if cfg.llm_classifier is not None and cfg.uncertain_low <= result.confidence <= cfg.uncertain_high:
        try:
            return cfg.llm_classifier(text)
        except Exception:
            pass  # LLM недоступен — решаем по тексту

    return result.confidence >= cfg.min_confidence


def _is_mostly_cyrillic(text: str) -> bool:
    sample = text[:200]
    cyr = sum(1 for c in sample if "Ѐ" <= c <= "ӿ")
    lat = sum(1 for c in sample if "a" <= c.lower() <= "z")
    return cyr >= lat
