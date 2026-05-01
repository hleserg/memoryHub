"""Build command argv preferring ``uv run`` when available."""

from __future__ import annotations

import shutil
import sys


def uv_or_python_argv(*parts: str) -> list[str]:
    """``uv run <parts>`` if ``uv`` is on PATH, else ``python -m`` / executable."""
    if shutil.which("uv"):
        return ["uv", "run", *parts]
    if parts[0] == "pytest":
        return [sys.executable, "-m", "pytest", *parts[1:]]
    if parts[0] == "python":
        return [sys.executable, *parts[1:]]
    return [sys.executable, *parts]


def pytest_cmd(*pytest_args: str) -> list[str]:
    return uv_or_python_argv("pytest", *pytest_args)


def python_script_cmd(*script_and_args: str) -> list[str]:
    """Run ``python src/demo.py`` style invocations (paths relative to repo root)."""
    return uv_or_python_argv("python", *script_and_args)
