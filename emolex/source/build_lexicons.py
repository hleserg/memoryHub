#!/usr/bin/env python3
"""
build_lexicons.py — собирает JSON-словари для emolex.py из TSV-источников.

Что делает:
  1. Английский: берёт English Word + 10 эмоциональных флагов из исходного NRC TSV,
     приводит к нижнему регистру.
  2. Русский: берёт Russian Word + синонимы (если есть), лемматизирует каждое слово
     через pymorphy3, мапит на эмоциональный вектор. Биграммы хранятся отдельно.

На выходе:
  emolex_en.json — {"_meta": {...}, "words": {слово: [10 флагов], ...}}
  emolex_ru.json — {"_meta": {...}, "words": {...}, "phrases": {"лемма1 лемма2": [...]}}

Использование:
  python build_lexicons.py [--ru russian.tsv] [--golden golden_seed.tsv] [--out-dir .]

По умолчанию ищет original_ru.tsv или improved_ru.tsv в текущей папке, плюс
golden_seed.tsv (если есть, перетирает им машинные переводы).
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

try:
    import pymorphy3
    MORPH = pymorphy3.MorphAnalyzer()
except ImportError:
    sys.stderr.write("pip install pymorphy3\n")
    sys.exit(1)


EMOTION_KEYS = [
    "anger", "anticipation", "disgust", "fear", "joy",
    "negative", "positive", "sadness", "surprise", "trust",
]

# Считаем слово "русским", если в нём есть кириллица
RU_RE = re.compile(r"[а-яёА-ЯЁ]")


def lemma_ru(word: str) -> str:
    """Привести русское слово к нормальной форме."""
    word = word.strip().lower().replace("ё", "е")
    if not word:
        return ""
    parsed = MORPH.parse(word)
    if not parsed:
        return word
    return parsed[0].normal_form


def lemmatize_phrase(phrase: str) -> str:
    """Лемматизировать каждое слово фразы."""
    parts = re.split(r"\s+", phrase.strip().lower())
    return " ".join(lemma_ru(p) for p in parts if p)


def merge_vectors(a: list, b: list) -> list:
    """Поэлементный максимум — если слово покрывает несколько эмо-векторов,
    собираем все ненулевые сигналы."""
    return [max(x, y) for x, y in zip(a, b)]


def parse_row(parts: list) -> tuple[str, list, list]:
    """Возвращает (english, vector, synonyms)."""
    en = parts[0].strip()
    vec = [int(parts[i + 1] or 0) for i in range(10)]
    ru = parts[11].strip() if len(parts) > 11 else ""
    syns = []
    if len(parts) > 12 and parts[12].strip():
        syns = [s.strip() for s in parts[12].split(";") if s.strip()]
    all_ru = [ru] + syns if ru else syns
    return en, vec, all_ru


def build_english(rows: list, slang_rows: list | None = None) -> dict:
    """Английский словарь — слово в нижнем регистре → эмо-вектор."""
    words: dict[str, list] = {}
    for parts in rows:
        en = parts[0].strip().lower()
        if not en:
            continue
        vec = [int(parts[i + 1] or 0) for i in range(10)]
        if any(vec):
            if en in words:
                words[en] = merge_vectors(words[en], vec)
            else:
                words[en] = vec

    # Накладываем слой сленга/эмодзи поверх (последнее слово за ним —
    # для эмодзи в NRC всё равно ничего нет, для сленга наши пометки точнее)
    if slang_rows:
        for parts in slang_rows:
            if not parts or not parts[0] or parts[0].startswith("#"):
                continue
            tok = parts[0].strip()  # эмодзи нельзя лоуэркейсить
            if not tok:
                continue
            # Эмодзи и аббревиатуры регистр-нечувствительны на стороне лукапа,
            # но в JSON сохраняем как есть для слов и эмодзи отдельно
            key = tok if not tok.isalpha() else tok.lower()
            try:
                vec = [int(parts[i + 1] or 0) for i in range(10)]
            except (ValueError, IndexError):
                sys.stderr.write(f"  пропускаю кривую строку: {parts}\n")
                continue
            if any(vec):
                words[key] = vec  # сленг перетирает NRC, если конфликт
    return words


def build_russian(rows: list, golden_rows: list | None = None,
                  slang_rows: list | None = None) -> tuple[dict, dict, Counter]:
    """Русский: лемматизирует слова, разделяет на одиночные/биграммы.

    Поверх машинного перевода накатывает golden_rows (если переданы).
    Слой slang_rows (эмодзи, англ. сленг) добавляется as-is — он
    языко-независимый и полезен в смешанном тексте."""
    # Сначала собираем сырые маппинги, потом накатываем golden поверх
    overrides: dict[str, list] = {}  # english_lower → vector (golden)
    overrides_ru: dict[str, list[str]] = {}  # english_lower → [primary, synonyms...]

    if golden_rows:
        for parts in golden_rows:
            en, vec, all_ru = parse_row(parts)
            overrides[en.lower()] = vec
            overrides_ru[en.lower()] = all_ru

    words: dict[str, list] = {}
    phrases: dict[str, list] = {}
    coverage_stats = Counter()

    for parts in rows:
        en, vec, all_ru = parse_row(parts)
        en_key = en.lower()

        # Если есть golden override — берём оттуда русские слова, но НЕ вектор
        # (вектор — это эмоциональная разметка NRC, она не меняется)
        if en_key in overrides_ru:
            all_ru = overrides_ru[en_key]

        if not any(vec):
            coverage_stats["neutral_skipped"] += 1
            continue

        for ru_word in all_ru:
            if not ru_word:
                continue
            # Очистка
            ru_clean = re.sub(r"[^\w\sёЁ\-]", "", ru_word.lower())
            ru_clean = ru_clean.strip()
            if not ru_clean or not RU_RE.search(ru_clean):
                continue

            tokens = [t for t in re.split(r"\s+", ru_clean) if t]
            if not tokens:
                continue

            if len(tokens) == 1:
                lemma = lemma_ru(tokens[0])
                if not lemma:
                    continue
                if lemma in words:
                    words[lemma] = merge_vectors(words[lemma], vec)
                else:
                    words[lemma] = vec[:]
                coverage_stats["single_word"] += 1
            else:
                # Многословное: храним как биграмму (первые два слова) +
                # каждое слово отдельно как одиночное (для повышения покрытия)
                lemmatized = [lemma_ru(t) for t in tokens]
                lemmatized = [l for l in lemmatized if l]
                if len(lemmatized) >= 2:
                    bigram = f"{lemmatized[0]} {lemmatized[1]}"
                    if bigram in phrases:
                        phrases[bigram] = merge_vectors(phrases[bigram], vec)
                    else:
                        phrases[bigram] = vec[:]
                    coverage_stats["phrase"] += 1

    # Языко-независимый слой: эмодзи и интернет-сленг — добавляем в РУ-словарь.
    # ВАЖНО: для слов кладём И исходную форму, И pymorphy-лемму, потому что
    # лемматизатор может выдать неожиданное (лол → лола, кек → кеки).
    if slang_rows:
        for parts in slang_rows:
            if not parts or not parts[0] or parts[0].startswith("#"):
                continue
            tok = parts[0].strip()
            if not tok:
                continue
            try:
                vec = [int(parts[i + 1] or 0) for i in range(10)]
            except (ValueError, IndexError):
                continue
            if not any(vec):
                continue
            # Эмодзи и не-буквенные токены — только сами по себе
            if not tok.isalpha():
                words[tok] = vec
            else:
                # Буквенные — кладём ОБЕ формы (raw и lemmatized),
                # чтобы лукап через нормализацию точно нашёл
                key_raw = tok.lower()
                words[key_raw] = vec
                key_lemma = lemma_ru(key_raw)
                if key_lemma and key_lemma != key_raw:
                    words[key_lemma] = vec
            coverage_stats["slang_emoji"] += 1

    return words, phrases, coverage_stats


def load_tsv(path: Path, skip_comments: bool = False) -> tuple[list[str], list[list[str]]]:
    rows = []
    header = []
    with path.open(encoding="utf-8") as f:
        header = f.readline().rstrip("\r\n").split("\t")
        for line in f:
            line = line.rstrip("\r\n")
            if skip_comments and line.lstrip().startswith("#"):
                continue
            if not line.strip():
                continue
            parts = line.split("\t")
            rows.append(parts)
    return header, rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ru", type=Path, default=None,
                    help="Русский TSV (12 или 13 колонок); по умолчанию ищет improved_ru.tsv или original_ru.tsv")
    ap.add_argument("--golden", type=Path, default=Path("golden_seed.tsv"),
                    help="Эталонные переводы (13 колонок); накладываются поверх машинных")
    ap.add_argument("--slang", type=Path, default=Path("slang_emoji_en.tsv"),
                    help="Слой сленга и эмодзи для английского (11 колонок); накладывается поверх NRC")
    ap.add_argument("--out-dir", type=Path, default=Path("."))
    args = ap.parse_args()

    # Найти русский файл
    ru_path = args.ru
    if ru_path is None:
        for cand in ["improved_ru.tsv", "original_ru.tsv"]:
            if Path(cand).exists():
                ru_path = Path(cand)
                break
    if ru_path is None or not ru_path.exists():
        sys.stderr.write("Не найден русский TSV. Укажи через --ru\n")
        sys.exit(1)

    sys.stderr.write(f"Читаю {ru_path}\n")
    header, rows = load_tsv(ru_path)
    sys.stderr.write(f"  {len(rows)} строк, {len(header)} колонок\n")

    golden_rows = None
    if args.golden and args.golden.exists():
        sys.stderr.write(f"Читаю эталоны {args.golden}\n")
        _, golden_rows = load_tsv(args.golden)
        sys.stderr.write(f"  {len(golden_rows)} эталонных переводов будут наложены поверх\n")

    slang_rows = None
    if args.slang and args.slang.exists():
        sys.stderr.write(f"Читаю сленг/эмодзи {args.slang}\n")
        _, slang_rows = load_tsv(args.slang, skip_comments=True)
        sys.stderr.write(f"  {len(slang_rows)} слов/эмодзи будут добавлены к английскому\n")

    args.out_dir.mkdir(exist_ok=True)

    # Английский
    sys.stderr.write("Собираю английский словарь...\n")
    en_words = build_english(rows, slang_rows)
    en_meta = {
        "language": "en",
        "source": "NRC Emotion Lexicon v0.92 + slang/emoji layer",
        "emotion_keys": EMOTION_KEYS,
        "entries": len(en_words),
        "slang_layer": bool(slang_rows),
    }
    en_path = args.out_dir / "emolex_en.json"
    with en_path.open("w", encoding="utf-8") as f:
        json.dump({"_meta": en_meta, "words": en_words}, f, ensure_ascii=False)
    sys.stderr.write(f"  → {en_path} ({len(en_words)} слов)\n")

    # Русский
    sys.stderr.write("Собираю русский словарь (это медленно — лемматизация ~14k слов)...\n")
    ru_words, ru_phrases, stats = build_russian(rows, golden_rows, slang_rows)
    ru_meta = {
        "language": "ru",
        "source": "NRC Emotion Lexicon v0.92 (translated + curated)",
        "emotion_keys": EMOTION_KEYS,
        "entries": len(ru_words),
        "phrases": len(ru_phrases),
        "build_stats": dict(stats),
    }
    ru_path_out = args.out_dir / "emolex_ru.json"
    with ru_path_out.open("w", encoding="utf-8") as f:
        json.dump({"_meta": ru_meta, "words": ru_words, "phrases": ru_phrases}, f, ensure_ascii=False)
    sys.stderr.write(f"  → {ru_path_out} ({len(ru_words)} лемм + {len(ru_phrases)} биграмм)\n")
    sys.stderr.write(f"  статистика сборки: {dict(stats)}\n")

    sys.stderr.write("\nГотово.\n")


if __name__ == "__main__":
    main()
