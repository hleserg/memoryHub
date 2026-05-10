#!/usr/bin/env python3
"""
Non-interactive demo for the Factual Memory adapter.

See docs/features/factual-memory/README.md (Russian: docs/features/factual-memory/README-ru.md).
Run: ``python3 src/demo.py`` or ``make demo-factual``.

Paced output (optional): ``ATMAN_DEMO_PACE=1`` or ``ATMAN_DEMO_PACE=0.6`` — short pauses
between sections; see ``atman.term.demo_pace``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory


def _ensure_src_on_path() -> Path:
    root = Path(__file__).resolve().parent.parent
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    return root


def main() -> int:
    _ensure_src_on_path()

    from atman.adapters.memory import FileBackend, InMemoryBackend
    from atman.core.models import FactRecord
    from atman.term import (
        demo_pace,
        print_banner,
        print_err,
        print_info,
        print_ok,
        print_section,
    )

    print_banner(
        "Atman Factual Memory Adapter",
        "Демонстрация InMemoryBackend и FileBackend",
    )
    demo_pace()

    try:
        print_section("ДЕМОНСТРАЦИЯ: InMemoryBackend")
        demo_pace()
        memory = InMemoryBackend()

        print_info("\n[bold]1.[/bold] Добавление фактов...")
        fact1 = memory.add_fact(
            FactRecord(
                content="Пользователь попросил реализовать factual memory adapter",
                source="session_001",
                tags=["task", "request"],
            )
        )
        print_ok(f"Добавлен факт: {fact1.id}")

        fact2 = memory.add_fact(
            FactRecord(
                content="Factual memory adapter реализован",
                source="session_002",
                tags=["task", "done"],
            )
        )
        print_ok(f"Добавлен факт: {fact2.id}")

        fact3 = memory.add_fact(
            FactRecord(
                content="Все тесты прошли успешно", source="session_002", tags=["test", "done"]
            )
        )
        print_ok(f"Добавлен факт: {fact3.id}")

        print_info("\n[bold]2.[/bold] Поиск фактов по тегу 'task'...")
        results = memory.search(tags=["task"])
        print_ok(f"Найдено: {len(results)} фактов")
        for r in results:
            print_info(f"  • {r.content}")

        print_info("\n[bold]3.[/bold] Создание связи между фактами...")
        success = memory.link(fact1.id, fact2.id, "led_to")
        print_ok(f"Связь создана: {success}")

        print_info("\n[bold]4.[/bold] Проверка связей...")
        retrieved = memory.get_fact(fact1.id)
        assert retrieved is not None, f"Факт {fact1.id} не найден"
        print_ok(f"Факт имеет {len(retrieved.relations)} связей")
        for rel in retrieved.relations:
            print_info(f"  • {rel.relation_type} → {rel.target_id}")

        print_info("\n[bold]5.[/bold] Последние факты...")
        recent = memory.list_recent(limit=3)
        print_ok(f"Получено {len(recent)} последних фактов:")
        for r in recent:
            print_info(f"  • [{r.created_at.strftime('%H:%M:%S')}] {r.content}")

        print_ok(f"Всего фактов в памяти: {memory.count()}")
        demo_pace()

        print_section("ДЕМОНСТРАЦИЯ: FileBackend (персистентное хранилище)")
        demo_pace()
        with TemporaryDirectory(prefix="atman_demo_") as tmpdir:
            filepath = Path(tmpdir) / "facts.jsonl"

            print_info("\n[bold]1.[/bold] Первая сессия: добавление фактов...")
            memory1 = FileBackend(filepath)

            fact1f = memory1.add_fact(
                FactRecord(
                    content="Демонстрация персистентности",
                    source="demo_session",
                    tags=["demo", "persistence"],
                )
            )
            print_ok(f"Добавлен факт: {fact1f.id}")
            print_ok(f"Файл сохранен: {filepath}")

            print_info("\n[bold]2.[/bold] Вторая сессия: загрузка из файла...")
            memory2 = FileBackend(filepath)
            print_ok(f"Загружено фактов: {memory2.count()}")

            retrieved2 = memory2.get_fact(fact1f.id)
            if retrieved2:
                print_ok("Факт успешно загружен из файла:")
                print_info(f"  • ID: {retrieved2.id}")
                print_info(f"  • Содержание: {retrieved2.content}")

            print_info("\n[bold]3.[/bold] Очистка демо-файла...")
            if filepath.exists():
                filepath.unlink()
                print_ok("Файл удален")

        print_section("Готово")
        demo_pace()
        print_ok("Все демонстрации успешно выполнены!")
        print_info("\nДля интерактивной работы запустите: python3 -m atman.cli\n")

    except Exception as e:
        print_err(str(e))
        import traceback

        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
