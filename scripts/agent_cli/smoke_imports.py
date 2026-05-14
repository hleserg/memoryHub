#!/usr/bin/env python3
"""Verify `atman` + `atman.agent_cli` import chain without network."""

from __future__ import annotations

import argparse
import importlib
import sys
from dataclasses import fields
from pathlib import Path


def _bootstrap(repo: Path) -> None:
    here = Path(__file__).resolve().parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    bootstrap = importlib.import_module("_bootstrap")
    bootstrap.bootstrap_atman_agent_cli(repo)


def main() -> int:
    ap = argparse.ArgumentParser(description="Import smoke for Atman agent CLI.")
    ap.add_argument("--repo", default=".", type=Path)
    args = ap.parse_args()
    repo = args.repo.expanduser().resolve()

    try:
        from rich.console import Console
        from rich.markup import escape

        console = Console(highlight=False, soft_wrap=True)

        def msg(s: str) -> None:
            console.print(escape(s))

    except ImportError:

        def msg(s: str) -> None:
            print(s, flush=True)

    try:
        _bootstrap(repo)
    except Exception as exc:
        msg(f"[smoke_imports] bootstrap failed: {type(exc).__name__}: {exc}")
        return 1

    import atman.agent_cli as ac

    n = len(fields(ac.AgentConfig))
    msg("[smoke_imports] Imports OK: atman, atman.agent_cli")
    msg(f"[smoke_imports] AgentConfig dataclass field count: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
