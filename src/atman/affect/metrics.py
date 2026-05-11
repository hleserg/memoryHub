"""Behavioural metrics over text; delegates NRC scoring to vendored emolex."""

from __future__ import annotations

import math
from collections.abc import Sequence

from atman.affect.emolex.emolex import EMOTION_KEYS, emotion_score, tokenize

RU_HEDGES = frozenset(
    {
        "возможно",
        "наверное",
        "кажется",
        "похоже",
        "вроде",
        "типа",
        "как",
        "будто",
        "наверно",
        "вероятно",
        "скорее",
    }
)
EN_HEDGES = frozenset(
    {
        "maybe",
        "perhaps",
        "possibly",
        "likely",
        "probably",
        "seems",
        "appears",
        "might",
        "could",
        "sort",
        "kinda",
        "somewhat",
    }
)

RU_SELF = frozenset(
    {
        "я",
        "мне",
        "меня",
        "мной",
        "мною",
        "мы",
        "нас",
        "нам",
        "нами",
        "наш",
        "наша",
        "наше",
        "наши",
        "мой",
        "моя",
        "моё",
        "мои",
    }
)
EN_SELF = frozenset(
    {
        "i",
        "me",
        "my",
        "mine",
        "myself",
        "we",
        "us",
        "our",
        "ours",
        "ourselves",
    }
)

# Token-level markers only (no standalone "не"/"тем"/"менее" — too common in Russian).
# Phrase "тем не менее" is detected separately in _disclaimer_hit_count.
RU_DISCLAIMERS = frozenset({"но", "однако", "хотя", "зато", "впрочем"})
EN_DISCLAIMERS = frozenset(
    {"but", "however", "although", "though", "yet", "still", "nevertheless", "nonetheless"}
)

RU_NEGATORS = frozenset({"не", "ни", "нет", "никогда", "никак", "ничуть", "нисколько"})
EN_NEGATORS = frozenset(
    {
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
)

RU_POSITIVE_SINCERITY_MARKERS = frozenset(
    {
        "честно",
        "правда",
        "искренне",
        "признаю",
        "сомневаюсь",
        "неуверен",
    }
)
EN_POSITIVE_SINCERITY_MARKERS = frozenset(
    {
        "honestly",
        "frankly",
        "truthfully",
        "unsure",
        "uncertain",
        "admit",
        "confess",
        "doubt",
    }
)

RU_EXPANSION_AFTER = frozenset({"потому", "так", "как", "поскольку", "из-за", "это", "значит"})
EN_EXPANSION_AFTER = frozenset({"because", "since", "therefore", "thus", "specifically", "namely"})


def nrc_emotion_vector(text: str, lang: str) -> dict[str, float]:
    """Return full NRC vector including positive/negative (no _meta)."""
    raw = emotion_score(text, lang=lang)
    return {k: float(raw[k]) for k in EMOTION_KEYS}


def nrc_emotion_score(text: str, lang: str) -> float:
    """Single valence signal: positive density minus negative density."""
    vec = emotion_score(text, lang=lang)
    return float(vec["positive"]) - float(vec["negative"])


def emotion_lexical_energy(score: dict[str, float]) -> float:
    """L2 norm over primary emotion channels (excludes positive/negative aggregates)."""
    primary = ("anger", "anticipation", "disgust", "fear", "joy", "sadness", "surprise", "trust")
    return float(math.sqrt(sum(score.get(k, 0.0) ** 2 for k in primary)))


def hedge_density(tokens: Sequence[str], lang: str) -> float:
    """Hedge marker count divided by token count."""
    if not tokens:
        return 0.0
    hedges = RU_HEDGES if lang == "ru" else EN_HEDGES
    lowered = [t.lower() for t in tokens]
    hits = sum(1 for t in lowered if t in hedges)
    return hits / len(tokens)


def length_anomaly_z(char_count: int, baseline_mean: float, baseline_std: float) -> float:
    """Z-score for length; 0.0 when std is degenerate."""
    if baseline_std <= 1e-9:
        return 0.0
    return (float(char_count) - baseline_mean) / baseline_std


def question_tail(text: str) -> float:
    """Count of '?' in the last 20% of the string (minimum 1 char window)."""
    if not text:
        return 0.0
    n = len(text)
    start = int(max(0, math.floor(n * 0.8)))
    tail = text[start:]
    return float(tail.count("?"))


def self_reference_density(tokens: Sequence[str], lang: str) -> float:
    if not tokens:
        return 0.0
    bag = RU_SELF if lang == "ru" else EN_SELF
    lowered = [t.lower() for t in tokens]
    hits = sum(1 for t in lowered if t in bag)
    return hits / len(tokens)


def _disclaimer_hit_count(tokens: Sequence[str], lang: str) -> int:
    """Token-aligned disclaimer hits (plus Russian trigram 'тем не менее')."""
    if not tokens:
        return 0
    bag = RU_DISCLAIMERS if lang == "ru" else EN_DISCLAIMERS
    lowered = [t.lower() for t in tokens]
    hits = sum(1 for t in lowered if t in bag)
    if lang == "ru" and len(lowered) >= 3:
        for i in range(len(lowered) - 2):
            if lowered[i] == "тем" and lowered[i + 1] == "не" and lowered[i + 2] == "менее":
                hits += 1
    return hits


def disclaimer_density(tokens: Sequence[str], lang: str) -> float:
    if not tokens:
        return 0.0
    return _disclaimer_hit_count(tokens, lang) / len(tokens)


def negation_inversion_valence(text: str, lang: str, base_valence: float) -> float:
    """
    Flip valence when an odd number of negation markers appear in a 3-token look-back window.
    """
    tokens = tokenize(text)
    if not tokens:
        return base_valence
    negs = RU_NEGATORS if lang == "ru" else EN_NEGATORS
    lowered = [t.lower() for t in tokens]
    adjusted_tokens: list[float] = []
    for i, _tok in enumerate(lowered):
        window = lowered[max(0, i - 3) : i]
        neg_count = sum(1 for w in window if w in negs)
        flip = -1.0 if (neg_count % 2 == 1) else 1.0
        # reuse per-token nrc contribution proxy: distribute base_valence uniformly
        adjusted_tokens.append(flip)
    # Average flip weighted signal
    avg_flip = sum(adjusted_tokens) / len(adjusted_tokens)
    return float(base_valence * avg_flip)


def min_length_gate(text: str, threshold: int) -> bool:
    """True when analysis should run (length OK or exclamation present)."""
    stripped = text.strip()
    if "!" in text:
        return True
    return len(stripped) >= threshold


def sincerity_score(text: str, tokens: Sequence[str], lang: str) -> int:
    """
    Four-factor sincerity heuristic (simplified to A+B+C sum per issue spec).

    A: early positive sincerity marker; B: elaboration after marker / length / questions;
    C: disclaimer presence.
    """
    markers = RU_POSITIVE_SINCERITY_MARKERS if lang == "ru" else EN_POSITIVE_SINCERITY_MARKERS
    expansion = RU_EXPANSION_AFTER if lang == "ru" else EN_EXPANSION_AFTER
    lowered_tokens = [t.lower() for t in tokens]

    score = 0
    first_idx: int | None = None
    i = 0
    while i < len(lowered_tokens):
        tok = lowered_tokens[i]
        if (
            lang == "ru"
            and i + 1 < len(lowered_tokens)
            and tok == "не"
            and lowered_tokens[i + 1] == "знаю"
        ):
            first_idx = i
            score += 1
            break
        if tok in markers:
            first_idx = i
            score += 1
            break
        i += 1

    if first_idx is not None:
        skip_after = (
            2
            if (
                lang == "ru"
                and first_idx + 1 < len(lowered_tokens)
                and lowered_tokens[first_idx] == "не"
                and lowered_tokens[first_idx + 1] == "знаю"
            )
            else 1
        )
        after = tokens[first_idx + skip_after :]
        wc_after = len(after)
        has_q = "?" in text
        has_exp = any(t.lower() in expansion for t in after)
        if wc_after >= 4 or has_q or has_exp:
            score += 1

    if _disclaimer_hit_count(tokens, lang) > 0:
        score += 1

    # Penalise very short performative praise without substance
    if len(tokens) < 4 and score > 0 and "?" not in text:
        score -= 1

    return score
