#!/usr/bin/env python3
"""
emolex.py — анализатор тональности по NRC Emotion Lexicon (русский + английский).

Использование:
    from emolex import emotion_score, load_lexicons

    score = emotion_score("Я очень счастлив сегодня", lang="ru")
    print(score)
    # {'anger': 0.0, 'joy': 30.0, ..., '_meta': {'tokens': 4, 'hits': 1, ...}}

Что считает:
    Для каждой из 10 эмоций (anger, anticipation, disgust, fear, joy,
    negative, positive, sadness, surprise, trust) — плотность сигнала
    на 100 токенов с учётом усилителей/ослабителей/отрицаний.

Скользящее окно модификаторов: 3 токена назад. Если в окне:
    усилитель → умножаем на 1.3-1.7
    ослабитель → умножаем на 0.4-0.7
    отрицание → демпфируем до 0.3 (не флипаем, простая модель)
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Sequence

try:
    import pymorphy3

    _MORPH = pymorphy3.MorphAnalyzer()
except ImportError:
    _MORPH = None


EMOTION_KEYS = [
    "anger",
    "anticipation",
    "disgust",
    "fear",
    "joy",
    "negative",
    "positive",
    "sadness",
    "surprise",
    "trust",
]

_HERE = Path(__file__).parent


# ============== Модификаторы ==============

RU_AMPLIFIERS = {
    "очень": 1.5,
    "крайне": 1.7,
    "чрезвычайно": 1.7,
    "безумно": 1.6,
    "страшно": 1.5,
    "сильно": 1.4,
    "жутко": 1.5,
    "чертовски": 1.5,
    "дико": 1.5,
    "безмерно": 1.6,
    "абсолютно": 1.5,
    "совершенно": 1.4,
    "полностью": 1.3,
    "невероятно": 1.6,
    "ужасающе": 1.7,
    "ужасно": 1.5,
    "поразительно": 1.4,
    "максимально": 1.5,
    "глубоко": 1.4,
    "невыносимо": 1.6,
    "столько": 1.3,
    "так": 1.3,
    "очень-очень": 1.8,
    "донельзя": 1.6,
    "просто": 1.2,
}

RU_WEAKENERS = {
    "чуть": 0.5,
    "немного": 0.6,
    "слегка": 0.5,
    "едва": 0.4,
    "чуточку": 0.4,
    "малость": 0.5,
    "несколько": 0.7,
    "слабо": 0.5,
    "слегонца": 0.5,
    "капельку": 0.5,
}

RU_NEGATORS = {"не", "ни", "нет", "никогда", "никак", "ничуть", "нисколько"}

EN_AMPLIFIERS = {
    "very": 1.5,
    "extremely": 1.7,
    "really": 1.4,
    "so": 1.3,
    "super": 1.4,
    "incredibly": 1.6,
    "terribly": 1.5,
    "awfully": 1.5,
    "absolutely": 1.5,
    "completely": 1.4,
    "utterly": 1.6,
    "totally": 1.4,
    "highly": 1.4,
    "deeply": 1.4,
    "intensely": 1.5,
    "exceptionally": 1.5,
    "remarkably": 1.4,
    "particularly": 1.3,
    "quite": 1.2,
    "too": 1.3,
}

EN_WEAKENERS = {
    "slightly": 0.5,
    "somewhat": 0.6,
    "kinda": 0.6,
    "kind": 0.6,
    "barely": 0.4,
    "hardly": 0.4,
    "little": 0.6,
    "bit": 0.7,
    "mildly": 0.5,
    "marginally": 0.5,
    "rather": 0.7,
}

EN_NEGATORS = {
    "not",
    "never",
    "no",
    "none",
    "nothing",
    "neither",
    "nor",
    "nobody",
    "without",
    "cannot",
    "cant",
    "wont",
    "dont",
    "doesnt",
    "didnt",
    "isnt",
    "arent",
    "wasnt",
    "werent",
    "havent",
    "hasnt",
}


# ============== Загрузка словарей ==============

_LEXICONS: dict[str, dict] = {}  # lang → {"words": {...}, "phrases": {...}}


def load_lexicons(path_ru: Path | str | None = None, path_en: Path | str | None = None) -> None:
    """Загрузить JSON-словари. Вызывается при импорте автоматически, если файлы
    лежат рядом с emolex.py. Можно вызвать вручную с другими путями."""
    global _LEXICONS
    if path_ru is None:
        path_ru = _HERE / "emolex_ru.json"
    if path_en is None:
        path_en = _HERE / "emolex_en.json"

    for lang, p in [("ru", path_ru), ("en", path_en)]:
        p = Path(p)
        if not p.exists():
            continue
        with p.open(encoding="utf-8") as f:
            data = json.load(f)
        _LEXICONS[lang] = {
            "words": data.get("words", {}),
            "phrases": data.get("phrases", {}),
            "meta": data.get("_meta", {}),
        }


# Автозагрузка при импорте
load_lexicons()


# ============== Токенизация и лемматизация ==============

_TOKEN_RE = re.compile(r"[^\W\d_]+", re.UNICODE)  # буквы любого алфавита
_EMOJI_RE = re.compile(
    "["
    "\U0001f600-\U0001f64f"  # smileys
    "\U0001f300-\U0001f5ff"  # symbols & pictographs
    "\U0001f680-\U0001f6ff"  # transport
    "\U0001f700-\U0001f77f"
    "\U0001f780-\U0001f7ff"
    "\U0001f800-\U0001f8ff"
    "\U0001f900-\U0001f9ff"  # supplemental symbols
    "\U0001fa00-\U0001faff"
    "\U00002600-\U000027bf"  # misc symbols + dingbats (включая ⭐, ✨, ☠, ❤)
    "\U0001f1e0-\U0001f1ff"  # flags
    "]"
    "[\U0000fe00-\U0000fe0f\U0001f3fb-\U0001f3ff\U0000200d\U000020e3]*"  # модификаторы + ZWJ-цепочки
)


def tokenize(text: str) -> list[str]:
    """Разбить текст на слова и эмодзи. Цифры/пунктуация пропускаются."""
    tokens: list[tuple[int, str]] = []
    for m in _TOKEN_RE.finditer(text.lower()):
        tokens.append((m.start(), m.group()))
    for m in _EMOJI_RE.finditer(text):
        tokens.append((m.start(), m.group()))
    tokens.sort(key=lambda x: x[0])
    return [t for _, t in tokens]


@lru_cache(maxsize=50000)
def _lemma_ru_cached(word: str) -> str:
    if _MORPH is None:
        return word
    word = word.replace("ё", "е")
    parsed = _MORPH.parse(word)
    if not parsed:
        return word
    return parsed[0].normal_form


def _en_base_form_candidates(word: str) -> list[str]:
    """Английский: NRC хранит базовые формы (terror, не terrified). Делаем дешёвую
    де-инфлекцию: пробуем сам токен и несколько суффиксных вариантов."""
    w = word.lower()
    cands = [w]
    # -ied → -y (terrified → terrify? нет, у NRC нет terrify, есть terror;
    # но scary → scare работает)
    if w.endswith("ied"):
        cands.append(w[:-3] + "y")
    # -ed
    if w.endswith("ed"):
        cands.append(w[:-2])
        cands.append(w[:-1])
        if len(w) > 3 and w[-3] == w[-4]:  # stopped → stop
            cands.append(w[:-3])
    # -ing
    if w.endswith("ing"):
        cands.append(w[:-3])
        cands.append(w[:-3] + "e")
        if len(w) > 4 and w[-4] == w[-5]:  # running → run
            cands.append(w[:-4])
    # plural / 3rd person
    if w.endswith("ies"):
        cands.append(w[:-3] + "y")
    if w.endswith("es"):
        cands.append(w[:-2])
        cands.append(w[:-1])
    if w.endswith("s") and not w.endswith("ss") and len(w) > 3:
        cands.append(w[:-1])
    # adverb
    if w.endswith("ly") and len(w) > 4:
        cands.append(w[:-2])
    # comparative / superlative
    if w.endswith("er") and len(w) > 4:
        cands.append(w[:-2])
    if w.endswith("est") and len(w) > 5:
        cands.append(w[:-3])
    # dedupe preserving order
    seen = set()
    result = []
    for c in cands:
        if c not in seen and c:
            seen.add(c)
            result.append(c)
    return result


def normalize(tokens: Sequence[str], lang: str) -> list[str]:
    if lang == "ru":
        return [_lemma_ru_cached(t) for t in tokens]
    return [t.lower() for t in tokens]


def _lookup(words_dict: dict, lemma: str, lang: str) -> list | None:
    """Лукап с базовыми формами для английского."""
    if lang == "en":
        for cand in _en_base_form_candidates(lemma):
            v = words_dict.get(cand)
            if v is not None:
                return v
        return None
    return words_dict.get(lemma)


# ============== Подсчёт эмоций ==============


def emotion_score(text: str, lang: str = "ru", window: int = 3) -> dict:
    """Посчитать эмо-вектор текста.

    Параметры:
        text — входной текст
        lang — "ru" или "en"
        window — сколько токенов назад смотреть на модификаторы (по умолчанию 3)

    Возвращает dict с 10 эмо-полями (плотность на 100 токенов) + _meta:
        {
            'anger': 0.0, 'anticipation': 25.0, ..., 'trust': 25.0,
            '_meta': {'tokens': 4, 'hits': 1, 'coverage': 25.0, 'matched': [...]}
        }
    """
    tokens = tokenize(text)
    zero = {k: 0.0 for k in EMOTION_KEYS}
    if not tokens:
        zero["_meta"] = {"tokens": 0, "hits": 0, "coverage": 0.0, "matched": []}
        return zero

    if lang not in _LEXICONS:
        raise ValueError(f"Словарь для языка '{lang}' не загружен. Запусти build_lexicons.py")

    lex = _LEXICONS[lang]
    words_dict = lex["words"]
    phrases_dict = lex["phrases"]

    if lang == "ru":
        amps, weaks, negs = RU_AMPLIFIERS, RU_WEAKENERS, RU_NEGATORS
    else:
        amps, weaks, negs = EN_AMPLIFIERS, EN_WEAKENERS, EN_NEGATORS

    # Множество модификаторов — эти токены не лукапим как обычные эмо-слова
    modifier_set = set(amps) | set(weaks) | negs

    lemmas = normalize(tokens, lang)

    acc = [0.0] * 10
    hits = 0
    matched: list[tuple[str, float]] = []  # для дебага
    consumed = [False] * len(lemmas)  # чтобы биграмма не считалась дважды

    def modifier_multiplier(i: int) -> tuple[float, bool]:
        """Посмотреть N токенов назад, вернуть (множитель, было_ли_отрицание)."""
        mult = 1.0
        negated = False
        for j in range(max(0, i - window), i):
            if consumed[j]:
                continue
            prev = lemmas[j]
            if prev in negs:
                negated = not negated
            elif prev in amps:
                mult *= amps[prev]
            elif prev in weaks:
                mult *= weaks[prev]
        return mult, negated

    # Сначала проходим биграммы (приоритет)
    if phrases_dict:
        i = 0
        while i < len(lemmas) - 1:
            if not consumed[i] and not consumed[i + 1]:
                bigram = f"{lemmas[i]} {lemmas[i + 1]}"
                vec = phrases_dict.get(bigram)
                if vec is not None:
                    mult, negated = modifier_multiplier(i)
                    if negated:
                        mult *= 0.3
                    for k in range(10):
                        acc[k] += vec[k] * mult
                    consumed[i] = consumed[i + 1] = True
                    hits += 1
                    matched.append((bigram, round(mult, 2)))
                    i += 2
                    continue
            i += 1

    # Потом одиночные слова — но НЕ модификаторы
    for i, lemma in enumerate(lemmas):
        if consumed[i]:
            continue
        if lemma in modifier_set:
            continue  # модификаторы не считаются как эмо-сигналы
        vec = _lookup(words_dict, lemma, lang)
        if vec is None:
            continue
        mult, negated = modifier_multiplier(i)
        if negated:
            mult *= 0.3
        for k in range(10):
            acc[k] += vec[k] * mult
        hits += 1
        matched.append((lemma, round(mult, 2)))

    n = len(tokens)
    result = {k: round(acc[idx] / n * 100, 2) for idx, k in enumerate(EMOTION_KEYS)}
    result["_meta"] = {
        "tokens": n,
        "hits": hits,
        "coverage": round(hits / n * 100, 1) if n else 0.0,
        "matched": matched,
    }
    return result


def dominant_emotion(score: dict) -> tuple[str, float]:
    """Найти доминирующую эмоцию (исключая суммирующие positive/negative)."""
    candidates = {
        k: score[k] for k in EMOTION_KEYS if k not in {"positive", "negative"} and k in score
    }
    if not candidates or max(candidates.values()) == 0:
        return ("neutral", 0.0)
    top = max(candidates, key=candidates.get)
    return (top, candidates[top])


def valence(score: dict) -> float:
    """Простая шкала: positive - negative, в условных единицах."""
    return score.get("positive", 0) - score.get("negative", 0)


if __name__ == "__main__":
    # smoke test
    import sys

    text = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Я очень счастлив"
    lang = "ru" if re.search(r"[а-яё]", text.lower()) else "en"
    print(f"Текст: {text}")
    print(f"Язык:  {lang}")
    s = emotion_score(text, lang=lang)
    meta = s.pop("_meta")
    for k, v in s.items():
        bar = "█" * int(v / 5) if v > 0 else ""
        print(f"  {k:13s} {v:6.2f}  {bar}")
    print(f"Найдено: {meta['hits']}/{meta['tokens']} ({meta['coverage']}%)")
    top, val = dominant_emotion({**s, "_meta": meta})
    print(f"Доминирующая: {top} ({val:.1f})")
    print(f"Валентность:  {valence(s):+.1f}")
