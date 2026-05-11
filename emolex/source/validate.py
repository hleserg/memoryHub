#!/usr/bin/env python3
"""
validate.py — проверка качества улучшенной русской версии лексикона.

Что проверяет (только реальные проблемы, без снобизма):
  - Пустые переводы
  - Синонимы, дублирующие основной перевод
  - Подозрительные кучи: когда десятки английских слов смапились в один русский
    (часто значит, что модель просто скопировала "аномальный" во все спорные случаи)
  - Несовпадение части речи между английским и русским (если установлен pymorphy3)
  - Слишком длинные описательные переводы (4+ слов) при коротких флагах

Транслитерации (бустер, хейтить) НЕ считаются ошибкой — они валидные синонимы.

Использование:
  python validate.py improved_ru.tsv [validation_report.tsv]

Выход:
  - validation_report.tsv (или stdout) — таблица "слово / тип проблемы / детали"
  - сводка в stderr
"""
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

try:
    import pymorphy3
    MORPH = pymorphy3.MorphAnalyzer()
except ImportError:
    MORPH = None


EMOTION_KEYS = [
    "anger", "anticipation", "disgust", "fear", "joy",
    "negative", "positive", "sadness", "surprise", "trust",
]

# Английские суффиксы → ожидаемая часть речи русского эквивалента.
# Только надёжные правила, чтобы не плодить ложные срабатывания.
EN_POS_HINTS = [
    # Существительные
    ("ness", "NOUN"), ("ment", "NOUN"), ("tion", "NOUN"), ("sion", "NOUN"),
    ("ity", "NOUN"), ("ship", "NOUN"), ("hood", "NOUN"),
    # Прилагательные — только самые однозначные
    ("ous", "ADJF"), ("ful", "ADJF"), ("less", "ADJF"),
    # -ing — приближённо причастие/деепричастие (часто ошибочно переведено сущ.)
    # ("ing", "PRTF"),  # выключено — много gerund-existительных (building, meeting)
]


def guess_en_pos(en: str) -> str | None:
    en = en.lower()
    for suf, pos in EN_POS_HINTS:
        if en.endswith(suf):
            return pos
    return None


def ru_pos(word: str) -> str | None:
    if not MORPH or not word:
        return None
    word = word.strip().split()[0]  # многословные — берём первое значимое
    if not word:
        return None
    parsed = MORPH.parse(word)
    if not parsed:
        return None
    return parsed[0].tag.POS  # NOUN, VERB, ADJF, INFN, PRTF, GRND, ...


# Группы совместимости частей речи: pymorphy иногда даёт NOUN там, где ожидали ADJF — это нормально
POS_GROUPS = {
    "NOUN": {"NOUN"},
    "ADJF": {"ADJF", "ADJS", "PRTF", "PRTS"},
    "INFN": {"INFN", "VERB"},
    "PRTF": {"PRTF", "PRTS", "ADJF"},
}


def pos_compatible(expected: str, actual: str | None) -> bool:
    if actual is None or expected is None:
        return True  # без морф-анализа — не ругаемся
    return actual in POS_GROUPS.get(expected, {expected})


def main():
    if len(sys.argv) < 2:
        sys.stderr.write(__doc__)
        sys.exit(1)
    in_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None

    rows = []
    with in_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for r in reader:
            rows.append(r)

    sys.stderr.write(f"Загружено {len(rows)} строк\n")
    if MORPH is None:
        sys.stderr.write("pymorphy3 не установлен — POS-проверка пропущена. "
                         "Поставь: pip install pymorphy3\n")

    # Сколько разных английских слов мапится в один русский?
    ru_to_en = defaultdict(list)
    for r in rows:
        ru = r.get("Russian Word", "").strip().lower()
        if ru:
            ru_to_en[ru].append(r["English Word"])

    issues = []

    for r in rows:
        en = r["English Word"]
        ru = r.get("Russian Word", "").strip()
        syn_raw = r.get("Russian Synonyms", "").strip()
        syns = [s.strip() for s in syn_raw.split(";") if s.strip()] if syn_raw else []
        flags_active = [k for k in EMOTION_KEYS if r.get(k) == "1"]

        # 1. Пустой перевод
        if not ru:
            issues.append((en, "EMPTY", "Russian Word пустой", ""))
            continue

        # 2. Синоним равен основному
        for s in syns:
            if s.lower() == ru.lower():
                issues.append((en, "SYN_DUP", f"Синоним «{s}» совпадает с основным переводом", ru))

        # 3. POS-несоответствие (только если морф-анализатор есть)
        if MORPH:
            expected = guess_en_pos(en)
            actual = ru_pos(ru)
            if expected and actual and not pos_compatible(expected, actual):
                issues.append((en, "POS_MISMATCH",
                               f"Ожидал {expected} (по англ. суффиксу), а {ru} — {actual}",
                               ru))

        # 4. Слишком длинный описательный перевод
        words = ru.split()
        if len(words) >= 4 and len(flags_active) >= 2:
            issues.append((en, "VERBOSE",
                           f"Перевод из {len(words)} слов при {len(flags_active)} эмоц. флагах",
                           ru))

    # 5. Подозрительные кучи: один русский для 8+ английских
    suspicious_clusters = []
    for ru, ens in ru_to_en.items():
        if len(ens) >= 8:
            suspicious_clusters.append((ru, ens))
    suspicious_clusters.sort(key=lambda x: -len(x[1]))

    # Запись отчёта
    if out_path:
        f = out_path.open("w", encoding="utf-8", newline="")
        sys.stderr.write(f"Пишу отчёт в {out_path}\n")
    else:
        f = sys.stdout

    writer = csv.writer(f, delimiter="\t")
    writer.writerow(["english", "issue_type", "details", "current_ru"])
    for issue in issues:
        writer.writerow(issue)

    # Кучи — отдельным блоком после основной таблицы
    writer.writerow([])
    writer.writerow(["# === Кучи: один русский перевод на много англ. слов ==="])
    writer.writerow(["russian", "count", "examples", ""])
    for ru, ens in suspicious_clusters[:30]:
        writer.writerow([ru, len(ens), ", ".join(ens[:10]) + ("..." if len(ens) > 10 else ""), ""])

    if out_path:
        f.close()

    # Сводка
    by_type = Counter(i[1] for i in issues)
    sys.stderr.write("\n=== СВОДКА ===\n")
    for issue_type, count in by_type.most_common():
        sys.stderr.write(f"  {issue_type}: {count}\n")
    sys.stderr.write(f"  Подозрительных куч (8+ слов в один перевод): {len(suspicious_clusters)}\n")
    sys.stderr.write(f"  Всего строк: {len(rows)}\n")
    sys.stderr.write(f"  Чистых строк: {len(rows) - len({i[0] for i in issues})}\n")


if __name__ == "__main__":
    main()
