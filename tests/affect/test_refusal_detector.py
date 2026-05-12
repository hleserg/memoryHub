"""
Tests for refusal_detector.py — three-layer text-only refusal detection.

Test categories:
  1. True positives — clear value-based refusals (should return True)
  2. True negatives — logical "no" or capability gaps (should return False)
  3. Capability refusals — "не умею генерировать" (should return False)
  4. English support — both value refusals and capability noes
  5. Edge cases — empty text, think-block stripping, LLM fallback

Known limitations (gray zone — LLM fallback handles these):
  - "I am afraid I cannot help" — polite EN capability form, NRC scores "afraid" as fear.
    Without LLM configured this is a false positive. Rare in practice; LLM fallback catches it.
"""

from __future__ import annotations

import pytest

from atman.affect.refusal_detector import (
    RefusalDetectorConfig,
    is_value_refusal,
    score_refusal,
)

# ── True positives ──────────────────────────────────────────────────────────

VALUE_REFUSALS = [
    # Explicit refusal verbs
    "Я отказываюсь помогать с этим, потому что это причиняет вред людям.",
    "Я вынужден отклонить этот запрос — он противоречит этическим принципам.",
    # Negated modal + moral context
    "Нет, я не буду участвовать в этом. Это обман и манипуляция людьми.",
    "Я не стану помогать с тем, что сеет ненависть и вызывает отвращение у людей.",
    "Не хочу этого делать — это нарушает доверие и причиняет вред.",
    # Longer moral context
    (
        "Я не могу помочь с этим запросом. Это связано с обманом пользователей "
        "и нарушает базовые этические принципы честности и доверия."
    ),
]


@pytest.mark.parametrize("text", VALUE_REFUSALS)
def test_value_refusals_detected(text: str) -> None:
    assert is_value_refusal(text), f"Expected value refusal, got False for: {text[:60]}"


# ── True negatives — logical "no" ───────────────────────────────────────────

LOGICAL_NOS = [
    "Нет, это неверно.",
    "Нет, Земля не плоская.",
    "Неправда. 2+2=4, а не 5.",
    "Нет, так не работает алгоритм.",
    "Это неправильный ответ на вопрос.",
]


@pytest.mark.parametrize("text", LOGICAL_NOS)
def test_logical_no_not_detected(text: str) -> None:
    assert not is_value_refusal(text), f"Expected False, got True for: {text[:60]}"


# ── Capability refusals ──────────────────────────────────────────────────────

CAPABILITY_NOS = [
    "Я не умею генерировать изображения.",
    "Я не могу открывать файлы на твоём компьютере.",
    "К сожалению, не могу загружать данные с интернета.",
    "Не могу запустить код — у меня нет доступа к среде выполнения.",
    "Я не умею рисовать, это не в моих возможностях.",
]


@pytest.mark.parametrize("text", CAPABILITY_NOS)
def test_capability_refusals_not_detected(text: str) -> None:
    assert not is_value_refusal(text), f"Expected False, got True for: {text[:60]}"


# ── score_refusal internals ──────────────────────────────────────────────────


def test_value_refusal_high_confidence() -> None:
    text = "Я отказываюсь помогать — это неэтично и причиняет вред людям."
    score = score_refusal(text)
    assert score.has_refusal_verb or score.has_negated_modal
    assert score.confidence >= 0.45, f"confidence={score.confidence}"


def test_logical_no_zero_confidence() -> None:
    score = score_refusal("Нет, это неверно.")
    assert score.confidence < 0.45, f"Expected low confidence, got {score.confidence}"


def test_capability_discount_applied() -> None:
    score = score_refusal("Я не могу генерировать изображения — это не в моих возможностях.")
    # Either flagged as capability or low confidence
    assert score.has_capability_context or score.confidence < 0.45


def test_think_block_stripped() -> None:
    text = "<think>размышления агента</think>Нет, это неверно."
    assert not is_value_refusal(text)


def test_think_block_with_refusal_stripped() -> None:
    # Value refusal in <think> block must not leak
    text = "<think>Я отказываюсь, это обман людей и противоречит этике</think>Нет, это неверно."
    # The <think> block is stripped, so only "Нет, это неверно." remains
    assert not is_value_refusal(text)


def test_empty_text_returns_false() -> None:
    assert not is_value_refusal("")
    assert not is_value_refusal("   ")


# ── English support ──────────────────────────────────────────────────────────

EN_VALUE_REFUSALS = [
    "I refuse to help with this — it causes harm to people and violates ethics.",
    "I will not participate in deception — this is against my values and causes harm.",
    "I decline to assist with something that spreads hate and disgust.",
]


@pytest.mark.parametrize("text", EN_VALUE_REFUSALS)
def test_english_value_refusals_detected(text: str) -> None:
    assert is_value_refusal(text), f"Expected EN value refusal, got False for: {text[:60]}"


EN_CAPABILITY_NOS = [
    "I cannot generate images.",
    "I do not have access to the internet.",
    "I cannot run code on your machine.",
]


@pytest.mark.parametrize("text", EN_CAPABILITY_NOS)
def test_english_capability_noes_not_detected(text: str) -> None:
    assert not is_value_refusal(text), f"Expected False, got True for: {text[:60]}"


def test_english_logical_no_not_detected() -> None:
    assert not is_value_refusal("No, that is incorrect.")
    assert not is_value_refusal("That statement is false.")


# ── LLM fallback ────────────────────────────────────────────────────────────


def test_llm_fallback_called_in_uncertain_zone() -> None:
    """LLM fallback should be invoked when confidence is in uncertain zone."""
    called: list[str] = []

    def mock_classifier(text: str) -> bool:
        called.append(text)
        return True

    # Borderline text — has refusal signal but weak moral context
    text = "Нет, не буду это делать."
    base_score = score_refusal(text)

    cfg = RefusalDetectorConfig(
        min_confidence=0.25,  # lower threshold to test LLM fallback zone
        uncertain_low=0.0,
        uncertain_high=1.0,  # force any confidence into uncertain zone
        llm_classifier=mock_classifier,
    )

    result = is_value_refusal(text, cfg)

    # Precondition: base confidence must be >= min_confidence for LLM to be invoked
    assert base_score.confidence >= cfg.min_confidence, (
        f"Test precondition failed: base confidence {base_score.confidence} "
        f"< min_confidence {cfg.min_confidence}. Adjust test text or thresholds."
    )
    assert called, "LLM fallback was not called"
    assert result is True  # mock returns True


def test_llm_fallback_not_called_when_none() -> None:
    """Without LLM config, decision is made by text alone."""
    text = "Нет, не буду это делать."
    cfg = RefusalDetectorConfig(llm_classifier=None)
    # Should not raise, just use text layer
    result = is_value_refusal(text, cfg)
    assert isinstance(result, bool)


def test_llm_fallback_exception_falls_back_to_text() -> None:
    """If LLM raises, fall back to text-layer decision."""

    def failing_classifier(text: str) -> bool:
        raise RuntimeError("network error")

    cfg = RefusalDetectorConfig(
        uncertain_low=0.0,
        uncertain_high=1.0,
        llm_classifier=failing_classifier,
    )
    # Should not propagate exception
    result = is_value_refusal("Нет, не буду это делать.", cfg)
    assert isinstance(result, bool)


# ── decided_by field ─────────────────────────────────────────────────────────


def test_decided_by_text_for_strong_signal() -> None:
    text = "Я отказываюсь помогать с этим — это вредит людям и нарушает этику."
    score = score_refusal(text)
    # Precondition: confidence must be high enough for this test to be meaningful
    assert score.confidence >= 0.45, (
        f"Test precondition failed: confidence {score.confidence} < 0.45. "
        "Adjust test text to ensure strong value refusal signal."
    )
    assert score.decided_by == "text"


def test_decided_by_below_threshold_for_weak_signal() -> None:
    score = score_refusal("Нет, это неверно.")
    assert score.decided_by == "below_threshold"
