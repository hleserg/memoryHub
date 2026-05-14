"""SYSTEM_MAP §1.6 / issue #158: full corpus demo and fixture ordering."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from e2e.full_loop import load_all_fixture_sessions_sorted

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_load_all_fixture_sessions_sorted_is_ordered_by_session_number():
    paths = load_all_fixture_sessions_sorted("en")
    if len(paths) < 2:
        pytest.skip("need at least 2 English fixtures")

    numbers: list[int] = []
    for p in paths:
        # filename convention: session_NN_... for EN
        name = p.stem
        part = name.split("_", 2)
        assert part[0] == "session"
        numbers.append(int(part[1]))
    assert numbers == sorted(numbers)


@pytest.mark.parametrize("locale", ["en", "ru"])
def test_demo_full_corpus_runs_with_limit(locale: str):
    """Smoke: ``src/demo_full_corpus.py`` exits zero (fast path: first 2 sessions)."""
    script = REPO_ROOT / "src" / "demo_full_corpus.py"
    paths = load_all_fixture_sessions_sorted(locale)
    if len(paths) < 1:
        pytest.skip(f"no fixtures for locale={locale}")

    env = {
        **os.environ,
        "ATMAN_DEMO_PACE": "off",
        "PYTHONPATH": str(REPO_ROOT),
    }
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--locale",
            locale,
            "--limit",
            "2",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, (
        f"demo_full_corpus exited {result.returncode}\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
