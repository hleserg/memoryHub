#!/usr/bin/env python3
"""
Запуск Atman агента.

    uv run src/run_agent.py                      # создать нового агента
    uv run src/run_agent.py --agent 1            # запустить агента #1
    uv run src/run_agent.py --new "Мой агент"    # создать с описанием
    uv run src/run_agent.py --list               # список агентов
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from rich import box
from rich.table import Table

_DEFAULT_WORKSPACE_ROOT = Path("~/.atman/agents")
_DEFAULT_MODEL = "ollama:qwen3.5:9b"


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    env_file = Path(__file__).resolve().parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                v = v.strip()
                # Strip surrounding quotes (single or double) from value
                if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
                    v = v[1:-1]
                env[k.strip()] = v
    # Overlay full process environment so deploy-time vars (e.g. DATABASE_URL) are
    # always visible even when .env defines other keys only.
    env.update(os.environ)
    return env


def main() -> None:
    from atman.term import console, print_err, print_info, print_ok, print_plain

    parser = argparse.ArgumentParser(description="Atman agent REPL")
    parser.add_argument("--agent", type=int, metavar="ID", help="Числовой ID агента")
    parser.add_argument(
        "--new", metavar="DESCRIPTION", nargs="?", const="", help="Создать нового агента"
    )
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--model", default=_DEFAULT_MODEL)
    parser.add_argument("--workspace-root", type=Path, default=_DEFAULT_WORKSPACE_ROOT)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)

    env = _load_env()
    os.environ.update({k: v for k, v in env.items() if k not in os.environ})
    app_url = env.get("DATABASE_URL")
    admin_url = env.get("ATMAN_ADMIN_DATABASE_URL") or app_url

    if not app_url:
        print_err("DATABASE_URL не найден. Проверь .env или переменные окружения.")
        raise SystemExit(1)

    from atman.agents_registry import AgentsRegistry

    registry = AgentsRegistry(app_url=app_url, admin_url=admin_url)

    if args.list:
        agents = registry.list_all()
        if not agents:
            print_info("Агентов нет. Создай: uv run src/run_agent.py --new 'Имя'")
            return
        table = Table(title="Агенты", box=box.ROUNDED, show_lines=False)
        table.add_column("#", justify="right", style="term.dim")
        table.add_column("UUID", style="term.label", overflow="fold")
        table.add_column("Описание", ratio=1)
        for a in agents:
            desc = a.description or a.name or "—"
            table.add_row(str(a.serial_id), str(a.uuid), desc)
        console.print(table)
        return

    if args.new is not None:
        record = registry.create(description=args.new, name=args.new or "agent")
        print_ok(f"Создан агент #{record.serial_id}  {record.uuid}")
        if args.new:
            print_plain(f"  {args.new}")
    elif args.agent is not None:
        record = registry.get_by_serial(args.agent)
        if record is None:
            print_err(f"Агент #{args.agent} не найден. Список: --list")
            raise SystemExit(1)
    else:
        record = registry.create(description="", name="agent")
        print_ok(f"Новый агент #{record.serial_id}. Повторный запуск: --agent {record.serial_id}")

    workspace = args.workspace_root.expanduser() / str(record.serial_id)
    desc = record.description or record.name or ""
    if desc:
        print_info(f"Агент #{record.serial_id}: {desc}")
    print_plain(f"UUID: {record.uuid}\n")

    from atman.adapters.agent.config import AgentConfig, ModelConfig
    from atman.adapters.agent.runner import AtmanRunner

    config = AgentConfig(model=ModelConfig(model=args.model))
    runner = AtmanRunner(workspace=workspace, agent_id=record.uuid, config=config)

    try:
        asyncio.run(runner.chat())
    except KeyboardInterrupt:
        print_info("\nBye.")
        sys.exit(0)


if __name__ == "__main__":
    main()
