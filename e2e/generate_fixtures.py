"""
Generate realistic session JSON fixtures via Anthropic (two-pass: skeleton + per session).

Not run in CI. Requires ``ANTHROPIC_API_KEY`` and ``pip install 'atman[e2e]'``.

Default: 20 English + 20 Russian sessions under ``en/`` and ``ru/`` (parallel API runs).

Usage::

    python -m e2e.generate_fixtures --model claude-haiku-4-5
    python -m e2e.generate_fixtures --count-en 5 --count-ru 5 --no-parallel-locales
    python -m e2e.generate_fixtures --count 5   # legacy: English only → en/

See https://github.com/hleserg/atman/issues/141
"""

from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from e2e.llm import CorpusPolicy
from e2e.models import SessionFixtureDocument
from e2e.prompts import Locale


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _generate_one_locale(
    model: str,
    count: int,
    locale: Locale,
    output_dir: Path,
    *,
    corpus_policy: CorpusPolicy,
    max_corpus_regen: int,
) -> tuple[Locale, list[SessionFixtureDocument]]:
    from e2e.llm import anthropic_client, generate_corpus_with_retries

    if count <= 0:
        return locale, []
    print(f"[{locale}] start generation for {count} sessions", flush=True)
    client = anthropic_client()
    fixtures = generate_corpus_with_retries(
        client,
        model,
        count,
        locale,
        output_dir=output_dir,
        corpus_policy=corpus_policy,
        max_corpus_regen_sessions=max_corpus_regen,
    )
    print(f"[{locale}] generation complete", flush=True)
    return locale, fixtures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate session fixtures via LLM (issue #141).")
    parser.add_argument(
        "--model",
        default="claude-haiku-4-5",
        help="Anthropic model id (default: claude-haiku-4-5)",
    )
    parser.add_argument(
        "--count-en",
        type=int,
        default=20,
        metavar="N",
        help="Sessions for English corpus (default: 20; 0 to skip)",
    )
    parser.add_argument(
        "--count-ru",
        type=int,
        default=20,
        metavar="N",
        help="Sessions for Russian corpus (default: 20; 0 to skip)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        metavar="N",
        help="Legacy shorthand: only English corpus with N sessions (--count-ru forced to 0)",
    )
    parser.add_argument(
        "--parallel-locales",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run en and ru corpora in parallel when both counts > 0 (default: true)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Base directory; writes en/ and ru/ beneath it (default: e2e/fixtures/sessions)",
    )
    parser.add_argument(
        "--corpus-policy",
        choices=("strict", "soft"),
        default="strict",
        help="strict: re-generate a failing tail when validate_corpus fails (within "
        "--max-corpus-regen). soft: never delete on corpus failure; warn and keep files.",
    )
    parser.add_argument(
        "--max-corpus-regen",
        type=int,
        default=12,
        metavar="N",
        help="Strict mode only: if corpus repair would drop more than N sessions, keep "
        "all files and finish with a warning instead (0 = no limit). Default: 12.",
    )
    args = parser.parse_args(argv)

    count_en = args.count_en
    count_ru = args.count_ru
    if args.count is not None:
        count_en = args.count
        count_ru = 0

    for label, n in (("count-en", count_en), ("count-ru", count_ru)):
        if n < 0 or n > 32:
            print(f"error: {label} must be between 0 and 32", file=sys.stderr)
            return 2

    if count_en == 0 and count_ru == 0:
        print("error: at least one of count-en / count-ru must be > 0", file=sys.stderr)
        return 2

    if args.max_corpus_regen < 0:
        print("error: --max-corpus-regen must be >= 0 (0 means no limit)", file=sys.stderr)
        return 2

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("error: ANTHROPIC_API_KEY is not set", file=sys.stderr)
        return 2

    base = args.output_dir or (_repo_root() / "e2e" / "fixtures" / "sessions")

    from e2e.llm import print_summary

    results: dict[str, list[SessionFixtureDocument]] = {"en": [], "ru": []}
    parallel = args.parallel_locales and count_en > 0 and count_ru > 0
    corpus_policy: CorpusPolicy = args.corpus_policy
    max_regen = args.max_corpus_regen

    if parallel:
        executor = ThreadPoolExecutor(max_workers=2)
        f_en = executor.submit(
            _generate_one_locale,
            args.model,
            count_en,
            "en",
            base / "en",
            corpus_policy=corpus_policy,
            max_corpus_regen=max_regen,
        )
        f_ru = executor.submit(
            _generate_one_locale,
            args.model,
            count_ru,
            "ru",
            base / "ru",
            corpus_policy=corpus_policy,
            max_corpus_regen=max_regen,
        )
        interrupted = False
        try:
            _, results["en"] = f_en.result()
            _, results["ru"] = f_ru.result()
        except KeyboardInterrupt:
            interrupted = True
            print(
                "\nInterrupted by user. Stopping background locale workers "
                "(already saved session files are kept).",
                file=sys.stderr,
                flush=True,
            )
            executor.shutdown(wait=False, cancel_futures=True)
            raise SystemExit(130) from None
        finally:
            if not interrupted:
                executor.shutdown(wait=True)
    else:
        if count_en > 0:
            _, results["en"] = _generate_one_locale(
                args.model,
                count_en,
                "en",
                base / "en",
                corpus_policy=corpus_policy,
                max_corpus_regen=max_regen,
            )
        if count_ru > 0:
            _, results["ru"] = _generate_one_locale(
                args.model,
                count_ru,
                "ru",
                base / "ru",
                corpus_policy=corpus_policy,
                max_corpus_regen=max_regen,
            )

    all_paths: list[Path] = []
    for loc, fixtures in results.items():
        if not fixtures:
            continue
        sub = base / loc
        paths = sorted(sub.glob("session_*.json"))
        all_paths.extend(paths)
        print(f"=== locale {loc} ({len(fixtures)} sessions) ===")
        print_summary(fixtures)
        for p in paths:
            print(f"  wrote {p}")

    print(f"=== done: {len(all_paths)} files under {base} ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
