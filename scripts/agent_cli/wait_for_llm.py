#!/usr/bin/env python3
"""Poll LLM HTTP until /v1/models or /health responds (stdlib urllib)."""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any


def probe(base: str, timeout_sec: float) -> tuple[bool, str, dict[str, Any]]:
    base = base.rstrip("/")
    paths = (
        "/v1/models",
        "/health",
        "/",
    )
    errs: list[str] = []
    meta: dict[str, Any] = {}
    for p in paths:
        url = f"{base}{p}"
        req = urllib.request.Request(url, headers={"Accept": "*/*"})
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                status = int(resp.status) if hasattr(resp, "status") else int(resp.getcode())
                meta = {"path": p, "url": url, "status": status}
                return status < 500, "ok_response", meta
        except urllib.error.HTTPError as e:
            meta = {"path": p, "url": url, "status": int(e.code)}
            if int(e.code) < 500:
                return True, "http_answer", meta
            errs.append(f"{p}: HTTPError {e.code}")
        except OSError as e:
            errs.append(f"{p}: {type(e).__name__}: {e}")
    meta = {"errors": errs}
    return False, "failure", meta


def main() -> int:
    ap = argparse.ArgumentParser(description="Wait for LLM HTTP to accept requests.")
    ap.add_argument(
        "--llm-url",
        default=os.environ.get("ATMAN_LLM_URL", "http://localhost:8080"),
        help="HTTP base URL of the inference server.",
    )
    ap.add_argument(
        "--timeout-sec",
        type=float,
        default=120.0,
        help="Give up after this many seconds.",
    )
    ap.add_argument(
        "--interval-sec",
        type=float,
        default=2.0,
        help="Sleep between probes.",
    )
    ap.add_argument(
        "--per-try-timeout-sec",
        type=float,
        default=5.0,
        help="Timeout for each GET.",
    )
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        from rich.console import Console
        from rich.markup import escape

        console = Console(highlight=False, soft_wrap=True)

        def msg(s: str) -> None:
            console.print(escape(s))

    except ImportError:

        def msg(s: str) -> None:
            print(s, flush=True)

    base = args.llm_url.strip()
    deadline = time.monotonic() + args.timeout_sec
    last_ok = False
    last_reason = ""
    last_meta: dict[str, Any] = {}

    if not args.json:
        msg(
            f"Waiting for LLM at {base!r} (timeout {args.timeout_sec}s, "
            f"interval {args.interval_sec}s)..."
        )

    while time.monotonic() < deadline:
        ok_http, why, md = probe(base, args.per_try_timeout_sec)
        last_ok = ok_http
        last_reason = why
        last_meta = md
        if ok_http:
            if args.json:
                print(
                    json.dumps(
                        {
                            "ok": True,
                            "llm_url": base,
                            "reason": why,
                            "detail": md,
                        }
                    ),
                    flush=True,
                )
            elif not args.json:
                msg(f"[wait_for_llm] OK ({why}) {md}")
            return 0
        if not args.json:
            msg(f"[wait_for_llm] not ready ({md}); retrying...")
        time.sleep(max(0.1, args.interval_sec))

    if args.json:
        print(
            json.dumps(
                {
                    "ok": False,
                    "llm_url": base,
                    "reason": "timeout",
                    "last_attempt": {"ok": last_ok, "why": last_reason, "detail": last_meta},
                }
            ),
            flush=True,
        )
    elif not args.json:
        msg(f"[wait_for_llm] TIMEOUT waiting for {base!r}")

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
