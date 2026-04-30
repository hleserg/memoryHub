#!/usr/bin/env python3
"""
Демо-скрипт для проверки работы Factual Memory Adapter.
"""

import sys
sys.path.insert(0, '/workspace/src')

from atman.adapters.memory import InMemoryBackend, FileBackend
from atman.core.models import FactRecord
from pathlib import Path

def demo_in_memory():
    """Демонстрация работы с InMemoryBackend."""
    print("=" * 60)
    print("ДЕМОНСТРАЦИЯ: InMemoryBackend")
    print("=" * 60)
    
    memory = InMemoryBackend()
    
    # Добавляем факты
    print("\n1. Добавление фактов...")
    fact1 = memory.add_fact(FactRecord(
        content="Пользователь попросил реализовать factual memory adapter",
        source="session_001",
        tags=["task", "request"]
    ))
    print(f"   ✓ Добавлен факт: {fact1.id}")
    
    fact2 = memory.add_fact(FactRecord(
        content="Factual memory adapter реализован",
        source="session_002",
        tags=["task", "done"]
    ))
    print(f"   ✓ Добавлен факт: {fact2.id}")
    
    fact3 = memory.add_fact(FactRecord(
        content="Все тесты прошли успешно",
        source="session_002",
        tags=["test", "done"]
    ))
    print(f"   ✓ Добавлен факт: {fact3.id}")
    
    # Поиск
    print("\n2. Поиск фактов по тегу 'task'...")
    results = memory.search(tags=["task"])
    print(f"   ✓ Найдено: {len(results)} фактов")
    for r in results:
        print(f"     - {r.content}")
    
    # Создание связи
    print("\n3. Создание связи между фактами...")
    success = memory.link(fact1.id, fact2.id, "led_to")
    print(f"   ✓ Связь создана: {success}")
    
    # Получение факта со связями
    print("\n4. Проверка связей...")
    retrieved = memory.get_fact(fact1.id)
    print(f"   ✓ Факт имеет {len(retrieved.relations)} связей")
    for rel in retrieved.relations:
        print(f"     - {rel.relation_type} -> {rel.target_id}")
    
    # Последние факты
    print("\n5. Последние факты...")
    recent = memory.list_recent(limit=3)
    print(f"   ✓ Получено {len(recent)} последних фактов:")
    for r in recent:
        print(f"     - [{r.created_at.strftime('%H:%M:%S')}] {r.content}")
    
    print(f"\n✓ Всего фактов в памяти: {memory.count()}")


def demo_file_backend():
    """Демонстрация работы с FileBackend."""
    print("\n" + "=" * 60)
    print("ДЕМОНСТРАЦИЯ: FileBackend (персистентное хранилище)")
    print("=" * 60)
    
    filepath = Path("/tmp/atman_demo_facts.jsonl")
    
    # Первая сессия - добавление фактов
    print("\n1. Первая сессия: добавление фактов...")
    memory1 = FileBackend(filepath)
    
    fact1 = memory1.add_fact(FactRecord(
        content="Демонстрация персистентности",
        source="demo_session",
        tags=["demo", "persistence"]
    ))
    print(f"   ✓ Добавлен факт: {fact1.id}")
    print(f"   ✓ Файл сохранен: {filepath}")
    
    # Вторая сессия - загрузка из файла
    print("\n2. Вторая сессия: загрузка из файла...")
    memory2 = FileBackend(filepath)
    print(f"   ✓ Загружено фактов: {memory2.count()}")
    
    retrieved = memory2.get_fact(fact1.id)
    if retrieved:
        print(f"   ✓ Факт успешно загружен из файла:")
        print(f"     - ID: {retrieved.id}")
        print(f"     - Содержание: {retrieved.content}")
    
    # Очистка
    print("\n3. Очистка демо-файла...")
    if filepath.exists():
        filepath.unlink()
        print(f"   ✓ Файл удален")


def main():
    """Запуск демонстраций."""
    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║  Atman Factual Memory Adapter - Демонстрация            ║")
    print("╚══════════════════════════════════════════════════════════╝")
    
    try:
        demo_in_memory()
        demo_file_backend()
        
        print("\n" + "=" * 60)
        print("✓ Все демонстрации успешно выполнены!")
        print("=" * 60)
        print("\nДля интерактивной работы запустите: python3 -m atman.cli")
        print()
        
    except Exception as e:
        print(f"\n✗ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
