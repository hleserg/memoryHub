"""Unit tests for affect.metrics."""

from __future__ import annotations

import pytest

from atman.affect.emolex.emolex import tokenize
from atman.affect.metrics import (
    disclaimer_density,
    hedge_density,
    length_anomaly_z,
    min_length_gate,
    negation_inversion_valence,
    nrc_emotion_score,
    question_tail,
    self_reference_density,
    sincerity_score,
)


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("Я очень рад сегодня", "ru"),
        ("I am very happy today", "en"),
    ],
)
def test_nrc_emotion_score_is_float(text: str, lang: str) -> None:
    v = nrc_emotion_score(text, lang)
    assert isinstance(v, float)


def test_hedge_density_ru_en() -> None:
    ru = "возможно я не уверен но попробую"
    en = "maybe perhaps I will try somewhat"
    tr = tokenize(ru)
    assert hedge_density(tr, "ru") > 0
    assert hedge_density(tokenize(en), "en") > 0


def test_self_reference_density() -> None:
    ru = "я думаю что мне нужно сказать нам правду"
    en = "I think we should tell ourselves the truth"
    assert self_reference_density(tokenize(ru), "ru") > 0.1
    assert self_reference_density(tokenize(en), "en") > 0.1


def test_disclaimer_density() -> None:
    ru = "это хорошо но сложно однако важно"
    en = "this is good but hard however important"
    assert disclaimer_density(tokenize(ru), "ru") > 0
    assert disclaimer_density(tokenize(en), "en") > 0


def test_length_anomaly_z() -> None:
    z = length_anomaly_z(100, 50.0, 10.0)
    assert abs(z - 5.0) < 1e-6
    assert length_anomaly_z(10, 10.0, 0.0) == 0.0


def test_question_tail_counts_end() -> None:
    long = "a" * 80 + "??"
    assert question_tail(long) >= 2.0


def test_negation_inversion_valence_returns_float() -> None:
    base = nrc_emotion_score("I am happy", "en")
    adj = negation_inversion_valence("I am not happy", "en", base)
    assert isinstance(adj, float)


def test_min_length_gate_exclamation_bypass() -> None:
    assert min_length_gate("Hi!", threshold=50) is True
    assert min_length_gate("short", threshold=50) is False


def test_sincerity_score_ru() -> None:
    text = "честно мне было трудно потому что задача была большой и непонятной?"
    tok = tokenize(text)
    assert sincerity_score(text, tok, "ru") >= 1


def test_sincerity_score_en() -> None:
    text = "honestly I was unsure because the requirements shifted?"
    tok = tokenize(text)
    assert sincerity_score(text, tok, "en") >= 1


def test_sincerity_score_ru_ne_znaiu_bigram() -> None:
    text = "не знаю что делать дальше это правда сложно?"
    tok = tokenize(text)
    assert sincerity_score(text, tok, "ru") >= 1


def test_sincerity_score_short_text_penalty() -> None:
    text = "честно"
    tok = tokenize(text)
    assert isinstance(sincerity_score(text, tok, "ru"), int)
