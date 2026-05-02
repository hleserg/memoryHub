"""Streamlit web dashboard for Atman project."""

from __future__ import annotations

__all__ = ["main"]


def main() -> None:
    """Entry point for web dashboard."""
    import subprocess  # nosec B404
    import sys
    from pathlib import Path

    dashboard_path = Path(__file__).parent / "app.py"
    result = subprocess.run(  # nosec B603
        [sys.executable, "-m", "streamlit", "run", str(dashboard_path)],
        check=False,
    )
    raise SystemExit(result.returncode)
