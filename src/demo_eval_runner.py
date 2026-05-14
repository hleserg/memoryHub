#!/usr/bin/env python3
"""Reproducible walkthrough for E1 Evaluation Runner framework."""

from __future__ import annotations

import sys
from pathlib import Path
from tempfile import NamedTemporaryFile


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _ensure_src_on_path() -> Path:
    root = _repo_root()
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    return root


def main() -> int:
    _ensure_src_on_path()

    from atman.eval.registry import list_benchmarks
    from atman.eval.reporters.jsonl_reporter import JsonlReporter
    from atman.eval.runner_core import RunnerCore
    from atman.term import demo_pace, print_banner, print_info, print_ok, print_section

    print_banner(
        "Atman Eval Runner (E1)",
        "Runnable demo · noop benchmark · JSONL reporter",
    )
    demo_pace()

    print_section("Step 1: Discover registered benchmarks")
    for key in list_benchmarks():
        print_info(f"- {key}")
    demo_pace()

    with NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".jsonl", delete=False) as tmp:
        output_path = Path(tmp.name)

    print_section("Step 2: Run noop benchmark with JSONL reporting")
    runner = RunnerCore(reporters=[JsonlReporter(output_path)])
    outcome = runner.run("noop", git_sha="demo-e1-sha", seed=42)
    print_info(f"status={outcome.status}")
    print_info(f"run_id={outcome.context.run_id}")
    print_info(f"passed={outcome.passed_items}/{outcome.total_items}")
    demo_pace()

    print_section("Step 3: Re-run noop with same git SHA (idempotent skip)")
    second = runner.run("noop", git_sha="demo-e1-sha", seed=777)
    print_info(f"status={second.status}")
    print_info(f"idempotent_reuse={second.metadata.get('idempotent_reuse', False)}")
    demo_pace()

    print_ok(f"Demo finished. JSONL artifact: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
