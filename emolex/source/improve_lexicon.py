#!/usr/bin/env python3
"""
improve_lexicon.py — улучшение русской версии NRC Emotion Lexicon через Claude API.

Что делает:
  - Читает Russian-NRC-EmoLex.txt
  - Для каждого слова формирует промпт с английским словом, эмоциональными флагами
    и текущим (часто кривым) русским переводом
  - Шлёт батчами в Claude (Sonnet 4.5 по умолчанию)
  - Использует эмоциональные флаги как контекст для дизамбигуации омонимов
    (adder+anger/fear → "гадюка", а не "сумматор")
  - Нормализует часть речи и форму, добавляет 1-4 синонима
  - Пишет улучшенный TSV (13 колонок: + Russian Synonyms)
  - Resumable: пишет каждую обработанную партию сразу, можно прервать и продолжить

Использование:
  export ANTHROPIC_API_KEY=sk-ant-...
  python improve_lexicon.py original_ru.tsv improved_ru.tsv

Параметры:
  --batch-size N   количество слов в одном запросе (по умолчанию 30)
  --model NAME     модель (по умолчанию claude-sonnet-4-5)
  --start N        начать со строки N (для resume — но скрипт сам определяет)
  --skip-neutral   пропустить слова без эмоциональных флагов (быстрее, дешевле)
  --dry-run        показать первую партию запроса/ответа и выйти

Стоимость для полного прогона ~14k слов: примерно $6-8 на Sonnet 4.5.
С --skip-neutral остаётся ~6.5k слов с эмоциональными флагами — ~$3-4.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

try:
    import anthropic
except ImportError:
    sys.stderr.write(
        "pip install anthropic\n"
        "Или: uv pip install anthropic\n"
    )
    sys.exit(1)


EMOTION_KEYS = [
    "anger", "anticipation", "disgust", "fear", "joy",
    "negative", "positive", "sadness", "surprise", "trust",
]


SYSTEM_PROMPT = """Ты — лингвист-эксперт по русско-английскому переводу и эмоциональной семантике, работаешь над улучшением русской версии NRC Emotion Lexicon.

Тебе даны английские слова с разметкой по 10 эмоциям и существующие русские переводы (машинный перевод 5+ летней давности, часто неточный).

Для КАЖДОГО слова сделай:
1. Выбери наиболее точный русский эквивалент. ЭМОЦИОНАЛЬНЫЕ ФЛАГИ — главный контекст для дизамбигуации омонимов:
   - "adder" с anger/disgust/fear → "гадюка" (не "сумматор")
   - "cross" с anger/fear/sadness → "крест" (не "пересекать")
   - "abba" с positive → "Авва" (религиозный термин, не группа)
   - "shot" с anger/fear → "выстрел" (сущ., не глагол "выстрелил")
2. Нормализуй форму:
   - существительные → им.п. ед.ч.
   - глаголы → инфинитив несовершенного вида (если возможно)
   - прилагательные → м.р. ед.ч. им.п.
   - причастия → м.р. ед.ч. им.п. (не деепричастия!)
3. Нижний регистр кроме имён собственных и религиозных терминов
4. Если однословный эквивалент существует — используй его вместо описательной фразы
   ("misbehavior" → "проступок", не "плохое поведение")
5. Добавь 1-4 синонима, если они реально близки по смыслу И эмоциональной окраске. Без воды и без откровенных дублей. Если хороших синонимов нет — пустой массив.
6. ВАЖНО: разговорные заимствования и транслитерации (бустер, хейт, кринж, фейк, шок) — это ВАЛИДНЫЕ синонимы, если они реально используются в русской речи. Добавляй их рядом с основным переводом, не выкидывай.
   Пример: booster → ru: "усилитель", syn: ["стимулятор","бустер"]
   Пример: hate → ru: "ненавидеть", syn: ["презирать","хейтить"]

Если текущий перевод уже корректен — оставь его как "ru" и добавь синонимы (или пустой массив).

ВАЖНО: верни СТРОГО валидный JSON-массив, без markdown-ограждений, без пояснений до или после. Длина массива РАВНА длине входного списка, порядок сохраняется.

Формат каждого элемента:
{"en":"english_word","ru":"основной_перевод","syn":["синоним1","синоним2"]}"""


# Few-shot примеры, демонстрирующие нужное качество и охват кейсов
FEW_SHOT_USER = """Слова:
adder [anger=1 disgust=1 fear=1 negative=1 sadness=1] // текущий: сумматор
abba [positive=1] // текущий: абба
charmed [joy=1 negative=1 positive=1] // текущий: Зачарованные
rejoicing [anticipation=1 joy=1 positive=1 surprise=1] // текущий: радуясь
freedom [anticipation=1 joy=1 positive=1 trust=1] // текущий: свобода
abacus [trust=1] // текущий: счеты
misbehavior [anger=1 disgust=1 negative=1 sadness=1] // текущий: плохое поведение
booster [(нейтральное)] // текущий: ракета-носитель
hate [anger=1 disgust=1 fear=1 negative=1 sadness=1] // текущий: ненавидеть"""

FEW_SHOT_ASSISTANT = """[
{"en":"adder","ru":"гадюка","syn":["змея","ехидна"]},
{"en":"abba","ru":"Авва","syn":["Отче"]},
{"en":"charmed","ru":"очарованный","syn":["зачарованный","пленённый"]},
{"en":"rejoicing","ru":"ликование","syn":["торжество","радость"]},
{"en":"freedom","ru":"свобода","syn":["воля","независимость"]},
{"en":"abacus","ru":"счёты","syn":[]},
{"en":"misbehavior","ru":"проступок","syn":["плохое поведение","шалость"]},
{"en":"booster","ru":"усилитель","syn":["стимулятор","бустер","ускоритель"]},
{"en":"hate","ru":"ненавидеть","syn":["презирать","хейтить","питать ненависть"]}
]"""


@dataclass
class Row:
    en: str
    emotions: dict  # name -> 0/1
    ru: str

    @property
    def active_flags(self) -> list[str]:
        return [k for k in EMOTION_KEYS if self.emotions.get(k) == 1]

    @property
    def is_neutral(self) -> bool:
        return not self.active_flags

    def to_prompt_line(self) -> str:
        flags = " ".join(f"{k}=1" for k in self.active_flags) or "(нейтральное)"
        return f'{self.en} [{flags}] // текущий: {self.ru}'


def parse_input(path: Path) -> tuple[list[str], list[Row]]:
    with path.open(encoding="utf-8") as f:
        header_line = f.readline().rstrip("\r\n")
        header = header_line.split("\t")
        rows = []
        for line in f:
            parts = line.rstrip("\r\n").split("\t")
            if len(parts) < 12:
                continue
            en = parts[0]
            emotions = {EMOTION_KEYS[i]: int(parts[i + 1]) for i in range(10)}
            ru = parts[11]
            rows.append(Row(en=en, emotions=emotions, ru=ru))
    return header, rows


def write_header(out_path: Path, header: list[str]) -> None:
    if out_path.exists():
        return
    new_header = header + ["Russian Synonyms"]
    with out_path.open("w", encoding="utf-8", newline="") as f:
        f.write("\t".join(new_header) + "\n")


def read_completed(out_path: Path) -> set[str]:
    """Список английских слов, уже записанных в выходной файл."""
    if not out_path.exists():
        return set()
    done = set()
    with out_path.open(encoding="utf-8") as f:
        f.readline()  # header
        for line in f:
            en = line.split("\t", 1)[0]
            if en:
                done.add(en)
    return done


def append_row(out_path: Path, row: Row, ru: str, syn: list[str]) -> None:
    flags = [str(row.emotions[k]) for k in EMOTION_KEYS]
    syn_str = ";".join(s.strip() for s in syn if s and s.strip())
    fields = [row.en] + flags + [ru, syn_str]
    with out_path.open("a", encoding="utf-8", newline="") as f:
        f.write("\t".join(fields) + "\n")


def chunked(seq: list, n: int) -> Iterator[list]:
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def make_user_prompt(batch: list[Row]) -> str:
    return "Слова:\n" + "\n".join(r.to_prompt_line() for r in batch)


def parse_response(text: str, batch: list[Row]) -> list[tuple[str, list[str]]]:
    """Парсим ответ модели; в случае проблем — fallback на исходный перевод."""
    # На случай если модель всё-таки обернула в markdown
    cleaned = text.strip()
    if cleaned.startswith("```"):
        # сорвать ограждение
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].lstrip()
        cleaned = cleaned.rsplit("```", 1)[0].strip() if "```" in cleaned else cleaned

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        sys.stderr.write(f"  ! JSON decode error: {e}\n  Raw: {text[:500]}\n")
        # fallback: оставить как есть, без синонимов
        return [(r.ru, []) for r in batch]

    if not isinstance(data, list):
        sys.stderr.write(f"  ! Response is not a list, got {type(data).__name__}\n")
        return [(r.ru, []) for r in batch]

    # Сопоставление по en (на случай если модель переставила порядок)
    by_en = {item.get("en", "").lower(): item for item in data if isinstance(item, dict)}
    result = []
    for r in batch:
        item = by_en.get(r.en.lower())
        if not item:
            result.append((r.ru, []))
            continue
        ru = (item.get("ru") or r.ru).strip()
        syn_raw = item.get("syn") or []
        if isinstance(syn_raw, str):
            syn = [s.strip() for s in syn_raw.split(",") if s.strip()]
        elif isinstance(syn_raw, list):
            syn = [str(s).strip() for s in syn_raw if str(s).strip()]
        else:
            syn = []
        result.append((ru, syn))
    return result


def call_claude(client, model: str, batch: list[Row], retries: int = 3) -> list[tuple[str, list[str]]]:
    user_msg = make_user_prompt(batch)
    last_err = None
    for attempt in range(retries):
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": FEW_SHOT_USER},
                    {"role": "assistant", "content": FEW_SHOT_ASSISTANT},
                    {"role": "user", "content": user_msg},
                ],
            )
            text = "".join(b.text for b in resp.content if hasattr(b, "text"))
            return parse_response(text, batch)
        except anthropic.APIError as e:
            last_err = e
            sleep_for = 2 ** attempt
            sys.stderr.write(f"  ! API error (attempt {attempt+1}/{retries}): {e}; sleeping {sleep_for}s\n")
            time.sleep(sleep_for)
    sys.stderr.write(f"  !! Giving up on batch starting with {batch[0].en}: {last_err}\n")
    return [(r.ru, []) for r in batch]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--batch-size", type=int, default=30)
    ap.add_argument("--model", default="claude-sonnet-4-5")
    ap.add_argument("--skip-neutral", action="store_true",
                    help="не отправлять в API слова без эмоциональных флагов (копировать as-is)")
    ap.add_argument("--dry-run", action="store_true",
                    help="показать первую партию запроса/ответа и выйти")
    ap.add_argument("--limit", type=int, default=None,
                    help="обработать только N слов (для теста)")
    args = ap.parse_args()

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        sys.stderr.write("ANTHROPIC_API_KEY не задан\n")
        sys.exit(1)

    header, rows = parse_input(args.input)
    sys.stderr.write(f"Загружено {len(rows)} строк из {args.input}\n")

    write_header(args.output, header)
    done = read_completed(args.output)
    sys.stderr.write(f"Уже обработано: {len(done)} слов; продолжаем с того места\n")

    todo = [r for r in rows if r.en not in done]
    if args.limit:
        todo = todo[:args.limit]
    sys.stderr.write(f"К обработке: {len(todo)} слов\n")

    # Раздел нейтральных
    if args.skip_neutral:
        neutral = [r for r in todo if r.is_neutral]
        loaded = [r for r in todo if not r.is_neutral]
        sys.stderr.write(f"  нейтральных (скопируем без API): {len(neutral)}\n")
        sys.stderr.write(f"  эмоциональных (через API): {len(loaded)}\n")
        for r in neutral:
            append_row(args.output, r, r.ru, [])
        todo = loaded

    client = anthropic.Anthropic(api_key=api_key)

    total_batches = (len(todo) + args.batch_size - 1) // args.batch_size
    t_start = time.time()

    for batch_idx, batch in enumerate(chunked(todo, args.batch_size), 1):
        if args.dry_run:
            print("=== SYSTEM ===")
            print(SYSTEM_PROMPT)
            print("\n=== FEW-SHOT USER ===")
            print(FEW_SHOT_USER)
            print("\n=== FEW-SHOT ASSISTANT ===")
            print(FEW_SHOT_ASSISTANT)
            print("\n=== USER (первая партия) ===")
            print(make_user_prompt(batch))
            print("\n=== Делаю один реальный вызов для проверки... ===")
            results = call_claude(client, args.model, batch)
            for r, (ru, syn) in zip(batch, results):
                print(f"  {r.en:25s} [{','.join(r.active_flags) or '-'}]")
                print(f"    было: {r.ru}")
                print(f"    стало: {ru}  syn=[{'; '.join(syn)}]")
            return

        results = call_claude(client, args.model, batch)
        for r, (ru, syn) in zip(batch, results):
            append_row(args.output, r, ru, syn)

        elapsed = time.time() - t_start
        rate = batch_idx / elapsed if elapsed else 0
        eta = (total_batches - batch_idx) / rate if rate else 0
        sys.stderr.write(
            f"  [{batch_idx}/{total_batches}] последнее слово: {batch[-1].en} | "
            f"{elapsed:.0f}с, ETA {eta:.0f}с\n"
        )

    sys.stderr.write(f"Готово. Записано в {args.output}\n")


if __name__ == "__main__":
    main()
