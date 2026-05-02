"""Command building utilities for web dashboard."""

from __future__ import annotations

import sys
from pathlib import Path
from shutil import which


def demo_subprocess_env(
    base: dict[str, str] | None = None,
    *,
    paced: bool,
) -> dict[str, str]:
    """Build env for a demo child process; ``paced`` sets ``ATMAN_DEMO_PACE``."""
    out = dict(base or {})
    out["ATMAN_DEMO_PACE"] = "1" if paced else "off"
    return out


def python_script_cmd(*script_path_parts: str) -> list[str]:
    """Build command to run Python script, preferring uv if available."""
    if which("uv"):
        return ["uv", "run", "python", *list(script_path_parts)]
    return [sys.executable, *list(script_path_parts)]


def pytest_cmd(*args: str) -> list[str]:
    """Build pytest command, preferring uv if available."""
    if which("uv"):
        return ["uv", "run", "pytest", *list(args)]
    return [sys.executable, "-m", "pytest", *list(args)]


def get_demo_command(
    script_path: str,
    paced: bool = True,
    repo_root: Path | None = None,
) -> tuple[list[str], dict[str, str]]:
    """
    Build demo command with environment.

    Args:
        script_path: Path to demo script (relative to repo root)
        paced: If True, use paced demo (ATMAN_DEMO_PACE=1)
        repo_root: Repository root path (unused, for future)

    Returns:
        Tuple of (command_args, env_dict)
    """
    cmd = python_script_cmd(script_path)
    return cmd, demo_subprocess_env(paced=paced)
