#!/usr/bin/env python3
"""Pre-flight checks for local Atman agent CLI development (stdout + optional JSON)."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _python_ok() -> tuple[bool, str]:
    ok = sys.version_info >= (3, 12)
    v = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    return ok, v


OPTIONAL_MODULES: tuple[tuple[str, str], ...] = (
    ("numpy", "numpy"),
    ("requests", "requests"),
    ("textual", "textual"),
    ("trafilatura", "trafilatura"),
    ("cohere", "cohere"),
    ("anthropic", "anthropic"),
    ("FlagEmbedding", "FlagEmbedding"),
    ("tree_sitter", "tree_sitter"),
    ("duckduckgo_search", "duckduckgo_search"),
    ("playwright", "playwright"),
    ("telegram", "telegram"),
    ("plyer", "plyer"),
)


def _try_import_optional(_label: str, mod: str) -> str:
    spec = importlib.util.find_spec(mod)
    return "OK" if spec is not None else "MISSING"


def _http_probe(base: str, timeout_sec: float) -> tuple[str, dict[str, Any]]:
    base = base.rstrip("/")
    urls = [f"{base}/v1/models", f"{base}/"]

    errs: list[str] = []

    def _attempt(url: str) -> tuple[bool, dict[str, Any]]:
        req = urllib.request.Request(url, headers={"Accept": "*/*"})
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            preview = resp.read(512).decode(errors="replace")
            status = int(resp.status) if hasattr(resp, "status") else int(resp.getcode())
            hint = (
                "<500 indicates server replied (auth may yield 401/403)." if status >= 400 else ""
            )
            return (
                status < 500,
                {"url": url, "status": status, "body_preview_chars": len(preview), "hint": hint},
            )

    for url in urls:
        try:
            ok_http, meta = _attempt(url)
            if ok_http:
                return "reachable", meta | {"successful_url": url}
            errs.append(f"{url}: HTTP status {meta.get('status')}")
        except urllib.error.HTTPError as e:
            if e.code < 500:
                return "reachable", {"url": url, "status": e.code, "via": "HTTPError"}
            errs.append(f"{url}: HTTPError {e.code}")
        except OSError as e:
            errs.append(f"{url}: {type(e).__name__}: {e}")

    return "failure", {"tried_urls": urls, "errors": errs}


def _bootstrap_imports(repo: Path) -> None:
    """See `_bootstrap.py` next to this script."""

    import importlib

    here = Path(__file__).resolve().parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    bootstrap = importlib.import_module("_bootstrap")
    bootstrap.bootstrap_atman_agent_cli(repo)


def main() -> int:

    ap = argparse.ArgumentParser(description="Atman agent CLI preflight.")
    ap.add_argument(
        "--llm-url",
        default=os.environ.get("ATMAN_LLM_URL", "http://localhost:8080"),
        help="LLM HTTP base URL (OpenAI-compat, e.g. llama.cpp server).",
    )
    ap.add_argument(
        "--repo",
        default=".",
        type=Path,
        help="Repository root containing atman_agent_cli/ and src/atman/.",
    )
    ap.add_argument("--json", action="store_true", help="Machine-readable JSON on stdout.")
    args = ap.parse_args()

    try:
        from rich.console import Console
        from rich.markup import escape

        console = Console(highlight=False, soft_wrap=True)

        def out(msg: str) -> None:
            console.print(escape(msg))

    except ImportError:

        def out(msg: str) -> None:
            print(msg, flush=True)

    repo = args.repo.expanduser().resolve()

    payload: dict[str, Any] = {
        "python_ok": False,
        "agent_cli_layout_ok": False,
        "core_atman_ok": False,
        "imports_ok": False,
        "optional_modules": {},
        "llm": {},
    }

    py_ok, py_ver = _python_ok()
    payload["python_ok"] = py_ok
    payload["python_version"] = py_ver

    agent_cli_pkg = repo / "atman_agent_cli" / "src" / "atman" / "agent_cli"
    core_atman = repo / "src" / "atman"
    layout_agent = agent_cli_pkg.is_dir()
    layout_core = core_atman.is_dir()
    payload["agent_cli_layout_ok"] = layout_agent
    payload["core_atman_ok"] = layout_core

    if args.json:
        pass
    else:
        out("[preflight] Atman agent CLI")

    # ordered checks per spec

    msg_py = f"Python: {py_ver} [{'OK' if py_ok else 'FAIL — need ≥3.12'}]"
    if args.json:
        pass
    else:
        out(msg_py)

    msg_layout = (
        f"Layout atman_agent_cli/src/atman/agent_cli: [{'OK' if layout_agent else 'MISSING'}]"
    )
    if not args.json:
        out(msg_layout)

    msg_core = f"Layout src/atman (core package): [{'OK' if layout_core else 'MISSING'}]"
    if not args.json:
        out(msg_core)

    imports_ok = False

    imports_err: str | None = None
    if py_ok and layout_agent and layout_core:
        try:
            _bootstrap_imports(repo)
            import atman.agent_cli  # noqa: F401

            imports_ok = True
            if not args.json:
                out("Imports atman + atman.agent_cli: OK")
        except Exception as exc:
            imports_err = f"{type(exc).__name__}: {exc}"
            if not args.json:
                out(f"Imports atman + atman.agent_cli: FAIL — {imports_err}")
    else:
        if not args.json:
            out("Imports atman + atman.agent_cli: SKIPPED (layout or Python)")

    payload["imports_ok"] = imports_ok
    if imports_err:
        payload["import_error"] = imports_err

    opt_status: dict[str, str] = {}
    if not args.json:
        out("Optional modules:")
    for label, modname in OPTIONAL_MODULES:
        st = _try_import_optional(label, modname)
        opt_status[label] = st
        if not args.json:
            out(f"  {label}: {st}")
    payload["optional_modules"] = opt_status

    llm_url = args.llm_url.strip()
    llm_kind, llm_detail = _http_probe(llm_url, timeout_sec=5.0)
    payload["llm"] = {"kind": llm_kind, **llm_detail}
    payload["warnings"] = []
    if llm_kind != "reachable":
        w = (
            "LLM HTTP probe did not succeed as expected (offline training is OK). "
            f"Detail: {llm_detail}"
        )
        payload["warnings"].append(w)
        if not args.json:
            out(f"[WARN] {w}")

    payload["overall_ok"] = bool(
        imports_ok and layout_agent and layout_core and py_ok,
    )

    if args.json:
        print(json.dumps(payload, indent=2), flush=True)

    rc = 0 if payload["overall_ok"] else 1

    if not args.json:
        out(f"[preflight] exit={rc}")

    return rc


if __name__ == "__main__":
    raise SystemExit(main())
