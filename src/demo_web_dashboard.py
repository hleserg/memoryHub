#!/usr/bin/env python3
"""
Console walk-in for the Streamlit Web Dashboard (no browser).

See docs/features/web-dashboard/README.md (Russian: README-ru.md).
Run: ``python3 src/demo_web_dashboard.py`` or ``make demo-webui``.

Paced output (optional): ``ATMAN_DEMO_PACE=1`` — see ``atman.term.demo_pace``.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_src_on_path() -> Path:
    root = Path(__file__).resolve().parent.parent
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    return root


def main() -> int:
    _ensure_src_on_path()

    from atman.term import demo_pace, print_banner, print_help_text, print_ok

    print_banner("Web Dashboard (Streamlit)")
    print_ok("From repo root: make webui")
    print_ok("Or: python3 -m streamlit run src/atman/web_dashboard/app.py")
    print_help_text("Documentation: docs/features/web-dashboard/README.md")
    demo_pace()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
