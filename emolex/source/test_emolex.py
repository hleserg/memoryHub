#!/usr/bin/env python3
"""
test_emolex.py — прогон 20 примеров через анализатор + красивый вывод.

Запуск:
    python test_emolex.py
"""
from emolex import emotion_score, dominant_emotion, valence, EMOTION_KEYS


TESTS = [
    # ===== РУССКИЕ =====
    ("ru", "Я очень счастлив сегодня",
     "усилитель + радость → joy↑"),
    ("ru", "Это ужасно грустно",
     "усилитель + печаль"),
    ("ru", "Я немного расстроен",
     "ослабитель + печаль → демпфирование"),
    ("ru", "Я не боюсь темноты",
     "отрицание + страх → демпфирование"),
    ("ru", "Меня переполняет любовь и нежность",
     "несколько positive слов"),
    ("ru", "Купил молоко в магазине вечером",
     "нейтральный текст"),
    ("ru", "Война принесла столько боли и страха",
     "fear + sadness"),
    ("ru", "Я полностью доверяю своему лучшему другу",
     "trust + усилитель"),
    ("ru", "Какой отвратительный мерзкий поступок",
     "disgust + anger"),
    ("ru", "Я разочарован результатом и злюсь",
     "anger + sadness"),

    # ===== АНГЛИЙСКИЕ =====
    ("en", "I am very happy today",
     "amplifier + happy"),
    ("en", "This is absolutely horrible",
     "amplifier + horrible"),
    ("en", "I'm slightly disappointed in you",
     "weakener + disappointed"),
    ("en", "I do not hate it",
     "negation + hate"),
    ("en", "What a beautiful and joyful day",
     "multiple positive"),
    ("en", "I bought milk at the store",
     "neutral text"),
    ("en", "The war brought so much pain and fear",
     "fear + sadness"),
    ("en", "I trust my best friend completely",
     "trust"),
    ("en", "What a disgusting act of betrayal",
     "disgust + anger"),
    ("en", "I am completely shocked by the news",
     "surprise"),

    # ===== СЛЕНГ И ЭМОДЗИ =====
    ("en", "lmao that's so based and lit 🔥💯",
     "сленг + эмодзи → positive стэк"),
    ("en", "this is straight up cringe, what a yikes moment 🤡",
     "сленг негатив + эмодзи"),
    ("en", "omg I am completely devastated 😭",
     "shock + sadness через сленг"),
    ("en", "I'm stoked, this game is an absolute banger",
     "amplifier + slang positive"),
    ("en", "ngl that meal was bussin 😍",
     "slang positive + эмодзи"),
    ("ru", "это полный кринж 🤡",
     "англ. сленг в русском тексте"),
    ("ru", "лол это вообще пушка 🔥",
     "code-switching сленг"),
    ("ru", "я очень устал 😴 ничего не хочется",
     "нейтральные эмодзи + усталость"),
    ("ru", "обожаю тебя ❤️ ты лучший",
     "love + эмодзи"),
    ("ru", "RIP моим планам на выходные 💀",
     "ирония: 💀 как смех + RIP как мем"),
]


def fmt_bar(value: float, scale: float = 50.0) -> str:
    blocks = int(value / scale * 20)
    return "█" * max(0, min(blocks, 20))


def print_report(lang: str, text: str, expected: str) -> None:
    print(f"\n{'─' * 70}")
    print(f"[{lang}] {text}")
    print(f"    ожидание: {expected}")
    score = emotion_score(text, lang=lang)
    meta = score.pop("_meta")
    top, top_val = dominant_emotion({**score, "_meta": meta})
    val = valence(score)

    # компактный вывод: только ненулевые эмоции
    nonzero = [(k, v) for k, v in score.items() if v > 0]
    nonzero.sort(key=lambda x: -x[1])
    if not nonzero:
        print(f"    ⚪ нейтрально (покрытие: {meta['coverage']}%)")
    else:
        for k, v in nonzero:
            mark = "★" if k == top else " "
            print(f"    {mark} {k:13s} {v:6.2f}  {fmt_bar(v)}")
    matched = meta['matched']
    matched_str = ", ".join(f"{w}×{m}" if m != 1.0 else w for w, m in matched) if matched else "—"
    print(f"    итог: dominant={top}({top_val:.1f}), valence={val:+.1f}, "
          f"hits={meta['hits']}/{meta['tokens']} ({meta['coverage']}%)")
    print(f"    сматчилось: {matched_str}")


def main():
    print("=" * 70)
    print("Atman EmoLex — прогон 20 тестовых примеров")
    print("=" * 70)
    for lang, text, expected in TESTS:
        print_report(lang, text, expected)
    print("\n" + "=" * 70)
    print("Готово. Если что-то не сматчилось — это значит слова нет в исходном")
    print("NRC v0.92 (например 'terrified' там действительно отсутствует),")
    print("либо плохой машинный перевод. После прогона improve_lexicon.py")
    print("покрытие вырастет за счёт синонимов.")


if __name__ == "__main__":
    main()
