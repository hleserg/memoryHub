"""
CLI для работы с Factual Memory Adapter.

Предоставляет команды для:
- Добавления фактов
- Поиска фактов по тексту и тегам
- Создания связей между фактами
- Просмотра последних фактов
"""

import sys
from pathlib import Path
from uuid import UUID

from atman.adapters.memory import FileBackend, InMemoryBackend
from atman.core.models import FactRecord


def print_fact(fact: FactRecord, prefix: str = ""):
    """Выводит информацию о факте."""
    print(f"{prefix}ID: {fact.id}")
    print(f"{prefix}Содержание: {fact.content}")
    print(f"{prefix}Источник: {fact.source}")
    print(f"{prefix}Теги: {', '.join(fact.tags) if fact.tags else 'нет'}")
    print(f"{prefix}Создан: {fact.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
    if fact.relations:
        print(f"{prefix}Связи:")
        for rel in fact.relations:
            print(f"{prefix}  - {rel.relation_type} -> {rel.target_id}")
    if fact.metadata:
        print(f"{prefix}Метаданные: {fact.metadata}")
    print()


def cmd_add(backend, args):
    """Добавляет новый факт."""
    if len(args) < 2:
        print("Использование: add <content> <source> [tags...]")
        return
    
    content = args[0]
    source = args[1]
    tags = args[2:] if len(args) > 2 else []
    
    fact = FactRecord(content=content, source=source, tags=tags)
    added = backend.add_fact(fact)
    
    print("✓ Факт добавлен:")
    print_fact(added)


def cmd_get(backend, args):
    """Получает факт по ID."""
    if len(args) < 1:
        print("Использование: get <fact_id>")
        return
    
    try:
        fact_id = UUID(args[0])
    except ValueError:
        print("✗ Ошибка: неверный формат UUID")
        return
    
    fact = backend.get_fact(fact_id)
    if fact:
        print("✓ Факт найден:")
        print_fact(fact)
    else:
        print("✗ Факт не найден")


def cmd_search(backend, args):
    """Ищет факты по запросу и/или тегам."""
    if len(args) < 1:
        print("Использование: search <query> [--tags tag1,tag2]")
        return
    
    query = None
    tags = None
    limit = 10
    
    i = 0
    while i < len(args):
        if args[i] == '--tags' and i + 1 < len(args):
            tags = [t.strip() for t in args[i + 1].split(',')]
            i += 2
        elif args[i] == '--limit' and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        else:
            query = args[i]
            i += 1
    
    results = backend.search(query=query, tags=tags, limit=limit)
    
    if results:
        print(f"✓ Найдено фактов: {len(results)}\n")
        for fact in results:
            print_fact(fact, prefix="  ")
    else:
        print("✗ Факты не найдены")


def cmd_link(backend, args):
    """Создает связь между фактами."""
    if len(args) < 3:
        print("Использование: link <source_id> <target_id> <relation_type>")
        return
    
    try:
        source_id = UUID(args[0])
        target_id = UUID(args[1])
    except ValueError:
        print("✗ Ошибка: неверный формат UUID")
        return
    
    relation_type = args[2]
    
    success = backend.link(source_id, target_id, relation_type)
    if success:
        print("✓ Связь создана")
    else:
        print("✗ Ошибка: один или оба факта не найдены")


def cmd_recent(backend, args):
    """Выводит последние факты."""
    limit = int(args[0]) if args and args[0].isdigit() else 10
    
    facts = backend.list_recent(limit=limit)
    
    if facts:
        print(f"✓ Последние {len(facts)} фактов:\n")
        for fact in facts:
            print_fact(fact, prefix="  ")
    else:
        print("✗ Фактов нет")


def cmd_help(_backend, _args):
    """Выводит справку."""
    print("""
Atman Factual Memory CLI

Команды:
  add <content> <source> [tags...]     Добавить новый факт
  get <fact_id>                        Получить факт по ID
  search <query> [--tags t1,t2]       Искать факты
  link <source_id> <target_id> <type>  Создать связь
  recent [limit]                       Показать последние факты
  help                                 Показать эту справку
  exit                                 Выйти

Примеры:
  add "Пользователь попросил X" session_1 task request
  search "пользователь" --tags task
  link <uuid1> <uuid2> caused_by
  recent 5
""")


COMMANDS = {
    'add': cmd_add,
    'get': cmd_get,
    'search': cmd_search,
    'link': cmd_link,
    'recent': cmd_recent,
    'help': cmd_help,
}


def main():
    """Точка входа CLI."""
    print("Atman Factual Memory CLI")
    print("Введите 'help' для справки\n")
    
    # Определяем storage
    storage_path = Path.home() / '.atman' / 'facts.jsonl'
    print(f"Используется file storage: {storage_path}\n")
    backend = FileBackend(storage_path)
    
    # REPL
    while True:
        try:
            line = input("atman> ").strip()
            if not line:
                continue
            
            if line == 'exit':
                break
            
            parts = line.split()
            cmd = parts[0]
            args = parts[1:]
            
            if cmd in COMMANDS:
                COMMANDS[cmd](backend, args)
            else:
                print(f"✗ Неизвестная команда: {cmd}")
                print("Введите 'help' для справки")
        
        except KeyboardInterrupt:
            print("\nДо свидания!")
            break
        except Exception as e:
            print(f"✗ Ошибка: {e}")


if __name__ == '__main__':
    main()
