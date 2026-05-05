"""
Generate realistic session JSON fixtures via Anthropic (two-pass: skeleton + per session).

Not run in CI. Requires ``ANTHROPIC_API_KEY`` and ``pip install 'atman[e2e]'``.

Usage::

    python -m e2e.generate_fixtures --model claude-sonnet-4-6 --count 5

See https://github.com/hleserg/atman/issues/141
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate session fixtures via LLM (issue #141).")
    parser.add_argument(
        "--model",
        default="claude-sonnet-4-6",
        help="Anthropic model id (default: claude-sonnet-4-6)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=5,
        help="Number of sessions in the corpus (default: 5)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory for session_NN_<slug>.json (default: e2e/fixtures/sessions under repo root)",
    )
    args = parser.parse_args(argv)

    if args.count < 1 or args.count > 20:
        print("error: --count must be between 1 and 20", file=sys.stderr)
        return 2

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("error: ANTHROPIC_API_KEY is not set", file=sys.stderr)
        return 2

    out = args.output_dir or (_repo_root() / "e2e" / "fixtures" / "sessions")

    from e2e.llm import (
        anthropic_client,
        generate_corpus_with_retries,
        print_summary,
        write_fixture_files,
    )

    client = anthropic_client()
    fixtures = generate_corpus_with_retries(client, args.model, args.count)
    paths = write_fixture_files(fixtures, out)
    print_summary(fixtures)
    for p in paths:
        print(f"  wrote {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
