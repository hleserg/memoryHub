#!/usr/bin/env bash
# run.sh — делает всё одной кнопкой.
# Использование:
#   export ANTHROPIC_API_KEY=sk-ant-...
#   bash run.sh
# Или с пропуском нейтральных слов (быстрее и дешевле в 2 раза):
#   bash run.sh --skip-neutral

set -e
cd "$(dirname "$0")"

echo "=== Atman lexicon improver ==="
echo

# 1. Проверка API-ключа
if [ -z "$ANTHROPIC_API_KEY" ]; then
    echo "ОШИБКА: ANTHROPIC_API_KEY не задан."
    echo "Сделай: export ANTHROPIC_API_KEY=sk-ant-..."
    exit 1
fi
echo "[OK] API-ключ есть"

# 2. Зависимости
echo "[..] Ставлю зависимости (anthropic, pymorphy3)..."
pip install -q anthropic pymorphy3 2>/dev/null || pip install -q anthropic
echo "[OK] Зависимости готовы"

# 3. Исходный файл
if [ ! -f original_ru.tsv ]; then
    echo "ОШИБКА: original_ru.tsv не найден в этой папке."
    exit 1
fi
echo "[OK] Исходник на месте ($(wc -l < original_ru.tsv) строк)"

# 4. Засеиваем эталонами (только если ещё не делали)
if [ ! -f improved_ru.tsv ]; then
    echo "[..] Засеиваю выверенные переводы..."
    python3 seed_output.py golden_seed.tsv improved_ru.tsv original_ru.tsv
    echo "[OK] Засеяно"
else
    echo "[OK] improved_ru.tsv уже есть — продолжаем с того места (resumable)"
fi

# 5. Прогон через Claude API
echo "[..] Запускаю улучшение через Claude API..."
echo "    Можно прервать Ctrl+C — продолжится с того же места при повторном запуске."
echo
python3 improve_lexicon.py original_ru.tsv improved_ru.tsv "$@"

# 6. Валидация
echo
echo "[..] Проверяю качество..."
python3 validate.py improved_ru.tsv validation_report.tsv

# 7. Итог
echo
echo "=== ГОТОВО ==="
echo "Улучшенный словарь:  improved_ru.tsv"
echo "Отчёт о проблемах:   validation_report.tsv"
echo
echo "Что дальше:"
echo "  1. Открой validation_report.tsv в Excel/Numbers/любом редакторе TSV"
echo "  2. Глянь сверху таблицы — там самые серьёзные косяки"
echo "  3. Поправь руками в improved_ru.tsv что не понравится"
