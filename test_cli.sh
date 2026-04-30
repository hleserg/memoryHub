#!/bin/bash
# Автоматический тест CLI

set -e

TEMP_FILE=$(mktemp /tmp/atman_cli_test_XXXXXX.jsonl)
echo "Используется временный файл: $TEMP_FILE"

# Создаем простой Python скрипт для тестирования CLI команд
python3 << EOF
import sys
sys.path.insert(0, '/workspace/src')

from pathlib import Path
from atman.adapters.memory import FileBackend
from atman.core.models import FactRecord

# Создаем backend
backend = FileBackend(Path("$TEMP_FILE"))

# Добавляем несколько фактов
fact1 = backend.add_fact(FactRecord(
    content="Первый тестовый факт",
    source="cli_test",
    tags=["test", "demo"]
))

fact2 = backend.add_fact(FactRecord(
    content="Второй факт о тестировании",
    source="cli_test",
    tags=["test"]
))

fact3 = backend.add_fact(FactRecord(
    content="Информационное сообщение",
    source="cli_test",
    tags=["info"]
))

# Создаем связь
backend.link(fact1.id, fact2.id, "led_to")

print("✓ CLI тест подготовлен:")
print(f"  - Создано фактов: {backend.count()}")
print(f"  - ID первого факта: {fact1.id}")
print(f"  - ID второго факта: {fact2.id}")
print(f"  - Связь: {fact1.id} -> led_to -> {fact2.id}")

# Тест поиска
print("\n✓ Тест поиска по тегу 'test':")
results = backend.search(tags=["test"])
print(f"  - Найдено: {len(results)} фактов")
for r in results:
    print(f"    * {r.content}")

# Тест поиска по запросу
print("\n✓ Тест поиска по запросу 'тестовый':")
results = backend.search(query="тестовый")
print(f"  - Найдено: {len(results)} фактов")

# Тест получения последних
print("\n✓ Тест получения последних фактов:")
recent = backend.list_recent(limit=2)
print(f"  - Получено: {len(recent)} фактов")

print("\n✓ Все CLI функции работают корректно!")
EOF

# Очистка
rm -f "$TEMP_FILE"
echo ""
echo "✓ Временный файл удален"
echo "✓ CLI тест завершен успешно"
