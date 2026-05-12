#!/usr/bin/env python3
"""
Запустить все e2e сценарии последовательно.

Запуск:
    PYTHONPATH=src OLLAMA_BASE_URL=http://localhost:11434/v1 \
        python3 e2e/run_all.py

    # Только быстрые (без LLM):
    PYTHONPATH=src python3 e2e/run_all.py --no-llm

    # Один конкретный:
    PYTHONPATH=src python3 e2e/run_all.py --only restart
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434/v1")

DIVIDER = "═" * 70

SCENARIOS = [
    # (module_path, label, needs_llm)
    ("e2e/scenarios/test_signal_interrupt.py", "signal_interrupt", False),
    ("e2e/scenarios/test_token_monitor.py", "token_monitor", True),
    ("e2e/scenarios/test_unexamined_facts.py", "unexamined_facts", True),
    ("e2e/scenarios/test_restart_with_handoff.py", "restart_with_handoff", True),
    ("e2e/live_scenario.py", "live_full", True),
]


async def run_scenario(path: str, label: str) -> tuple[str, int, float]:
    print(f"\n{DIVIDER}")
    print(f"  СЦЕНАРИЙ: {label}")
    print(DIVIDER)

    spec = importlib.util.spec_from_file_location(label, path)
    if spec is None or spec.loader is None:
        print(f"  ⚠ Не удалось загрузить модуль {label}")
        return (label, 1, 0.0)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    start = time.monotonic()
    try:
        if asyncio.iscoroutinefunction(mod.main):
            code = await mod.main()
        else:
            code = mod.main()
    except Exception as e:
        print(f"\n  [EXCEPTION] {e}")
        code = 1
    elapsed = time.monotonic() - start

    status = "PASS" if code == 0 else "FAIL"
    print(f"\n  {status} ({elapsed:.1f}s)")
    return label, code, elapsed


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-llm", action="store_true", help="пропустить сценарии требующие LLM")
    parser.add_argument("--only", help="запустить только этот сценарий")
    args = parser.parse_args()

    root = Path(__file__).parent.parent

    selected = []
    for path, label, needs_llm in SCENARIOS:
        if args.only and args.only not in label:
            continue
        if args.no_llm and needs_llm:
            print(f"  skip (--no-llm): {label}")
            continue
        full_path = root / path
        if not full_path.exists():
            print(f"  skip (not found): {path}")
            continue
        selected.append((str(full_path), label))

    if not selected:
        print("Нет сценариев для запуска.")
        return

    results = []
    for path, label in selected:
        label, code, elapsed = await run_scenario(path, label)
        results.append((label, code, elapsed))

    print(f"\n{DIVIDER}")
    print("  ИТОГО")
    print(DIVIDER)
    total_fail = 0
    for label, code, elapsed in results:
        status = "✓ PASS" if code == 0 else "✗ FAIL"
        print(f"  {status}  {label:40s}  {elapsed:.1f}s")
        if code != 0:
            total_fail += 1

    print(f"\n  {len(results) - total_fail}/{len(results)} прошло")
    sys.exit(1 if total_fail else 0)


if __name__ == "__main__":
    asyncio.run(main())
