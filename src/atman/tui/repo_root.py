"""Locate repository root (directory containing pyproject.toml)."""

from __future__ import annotations

from pathlib import Path


def _candidates(start: Path | None) -> list[Path]:
    out: list[Path] = []
    if start is not None:
        out.append(start.resolve())
    out.append(Path.cwd().resolve())
    here = Path(__file__).resolve()
    out.append(here.parent.parent.parent.parent)  # src/atman/tui -> repo root
    return out


def find_repo_root(start: Path | None = None) -> Path:
    """Walk parents from ``start``, cwd, and package-relative path for ``pyproject.toml``."""
    tried: list[Path] = []
    for candidate in _candidates(start):
        if candidate in tried:
            continue
        tried.append(candidate)
        p = candidate
        while True:
            if (p / "pyproject.toml").is_file():
                return p
            if p.parent == p:
                break
            p = p.parent
    msg = "Could not find pyproject.toml (not inside the Atman repository?)."
    raise FileNotFoundError(msg)
