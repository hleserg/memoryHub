"""
CLI для работы с Factual Memory Adapter.

Предоставляет команды для:
- Добавления фактов
- Поиска фактов по тексту и тегам
- Создания связей между фактами
- Просмотра последних фактов
"""

from pathlib import Path
from uuid import UUID

from atman.adapters.memory import FileBackend
from atman.core.models import FactRecord
from atman.core.ports import FactualMemory
from atman.term import (
    print_banner,
    print_err,
    print_fact,
    print_help_text,
    print_info,
    print_ok,
)


def cmd_add(backend: FactualMemory, args: list[str]) -> None:
    """Добавляет новый факт."""
    if len(args) < 2:
        print_info("Использование: add <content> <source> [tags...]")
        return

    content = args[0]
    source = args[1]
    tags = args[2:] if len(args) > 2 else []

    fact = FactRecord(content=content, source=source, tags=tags)
    added = backend.add_fact(fact)

    print_ok("Факт добавлен:")
    print_fact(added)


def cmd_get(backend: FactualMemory, args: list[str]) -> None:
    """Получает факт по ID."""
    if len(args) < 1:
        print_info("Использование: get <fact_id>")
        return

    try:
        fact_id = UUID(args[0])
    except ValueError:
        print_err("Ошибка: неверный формат UUID")
        return

    fact = backend.get_fact(fact_id)
    if fact:
        print_ok("Факт найден:")
        print_fact(fact)
    else:
        print_err("Факт не найден")


def cmd_search(backend: FactualMemory, args: list[str]) -> None:
    """Ищет факты по запросу и/или тегам."""
    if len(args) < 1:
        print_info("Использование: search <query> [--tags tag1,tag2]")
        return

    query = None
    tags = None
    limit = 10

    i = 0
    while i < len(args):
        if args[i] == "--tags" and i + 1 < len(args):
            tags = [t.strip() for t in args[i + 1].split(",")]
            i += 2
        elif args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        else:
            query = args[i]
            i += 1

    results = backend.search(query=query, tags=tags, limit=limit)

    if results:
        print_ok(f"Найдено фактов: {len(results)}")
        for fact in results:
            print_fact(fact, prefix="  ")
    else:
        print_err("Факты не найдены")


def cmd_link(backend: FactualMemory, args: list[str]) -> None:
    """Создает связь между фактами."""
    if len(args) < 3:
        print_info("Использование: link <source_id> <target_id> <relation_type>")
        return

    try:
        source_id = UUID(args[0])
        target_id = UUID(args[1])
    except ValueError:
        print_err("Ошибка: неверный формат UUID")
        return

    relation_type = args[2]

    success = backend.link(source_id, target_id, relation_type)
    if success:
        print_ok("Связь создана")
    else:
        print_err("Ошибка: один или оба факта не найдены")


def cmd_recent(backend: FactualMemory, args: list[str]) -> None:
    """Выводит последние факты."""
    limit = int(args[0]) if args and args[0].isdigit() else 10

    facts = backend.list_recent(limit=limit)

    if facts:
        print_ok(f"Последние {len(facts)} фактов:")
        for fact in facts:
            print_fact(fact, prefix="  ")
    else:
        print_err("Фактов нет")


def cmd_invalidate(backend: FactualMemory, args: list[str]) -> None:
    """Помечает факт как устаревший/недействительный."""
    if len(args) < 2:
        print_info("Использование: invalidate <fact_id> <reason>")
        return

    try:
        fact_id = UUID(args[0])
    except ValueError:
        print_err("Ошибка: неверный формат UUID")
        return

    reason = " ".join(args[1:])
    success = backend.invalidate_fact(fact_id, reason)

    if success:
        print_ok(f"Факт {fact_id} помечен как недействительный")
        print_info(f"Причина: {reason}")
    else:
        print_err("Факт не найден")


def cmd_list_invalidated(backend: FactualMemory, args: list[str]) -> None:
    """Выводит список недействительных фактов."""
    limit = int(args[0]) if args and args[0].isdigit() else 10

    facts = backend.list_invalidated(limit=limit)

    if facts:
        print_ok(f"Недействительных фактов: {len(facts)}")
        for fact in facts:
            print_fact(fact, prefix="  ")
            if fact.invalidated_reason:
                print_info(f"    Причина: {fact.invalidated_reason}")
    else:
        print_err("Недействительных фактов нет")


def cmd_help(_backend: FactualMemory, _args: list[str]) -> None:
    """Выводит справку."""
    print_help_text("""
Atman Factual Memory CLI

Команды:
  add <content> <source> [tags...]     Добавить новый факт
  get <fact_id>                        Получить факт по ID
  search <query> [--tags t1,t2]       Искать факты
  link <source_id> <target_id> <type>  Создать связь
  recent [limit]                       Показать последние факты
  invalidate <fact_id> <reason>        Пометить факт недействительным
  list-invalidated [limit]           Список недействительных фактов
  help                                 Показать эту справку
  exit                                 Выйти

Примеры:
  add "Пользователь попросил X" session_1 task request
  search "пользователь" --tags task
  link <uuid1> <uuid2> caused_by
  recent 5
  invalidate <uuid> "outdated information"
""")


COMMANDS = {
    "add": cmd_add,
    "get": cmd_get,
    "search": cmd_search,
    "link": cmd_link,
    "recent": cmd_recent,
    "invalidate": cmd_invalidate,
    "list-invalidated": cmd_list_invalidated,
    "help": cmd_help,
}


def main() -> None:
    """Точка входа CLI."""
    print_banner("Atman Factual Memory CLI", "Введите 'help' для справки")

    storage_path = Path.home() / ".atman" / "facts.jsonl"
    print_info(f"Используется file storage: {storage_path}\n")
    backend = FileBackend(storage_path)

    while True:
        try:
            line = input("atman> ").strip()
            if not line:
                continue

            if line == "exit":
                break

            parts = line.split()
            cmd = parts[0]
            args = parts[1:]

            if cmd in COMMANDS:
                COMMANDS[cmd](backend, args)
            else:
                print_err(f"Неизвестная команда: {cmd}")
                print_info("Введите 'help' для справки")

        except KeyboardInterrupt:
            print_info("\nДо свидания!")
            break
        except Exception as e:
            print_err(str(e))


if __name__ == "__main__":
    main()
