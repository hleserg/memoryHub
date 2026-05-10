#!/usr/bin/env python3
"""
Suggest PLAYBOOK markers for recent commits that may have missed them.

Analyzes git log diffs through an LLM and identifies changes that introduce
generalizable engineering patterns without PLAYBOOK markers.

This script is MANUAL and OPTIONAL. Run it when you want to verify that
agents have not missed any markers. It does NOT modify files — output only.

Usage:
    python scripts/suggest_playbook.py [options]

Options:
    --days N             Analyze commits from last N days (default: 30)
    --provider           LLM provider: ollama | claude (default: ollama)
    --ollama-model       Ollama model name (default: llama3.1:8b)
    --claude-model       Anthropic model (default: claude-haiku-4-5)
    --ollama-url         Ollama API URL (default: http://localhost:11434)
    --source-repo PATH   Repo root (default: current directory)
    --raw-markers PATH   Path to extracted markers file for context
                         (default: ../agent-playbook/raw/extracted-from-atman.md)
    --max-diff-chars N   Truncate diff at N characters to fit context (default: 12000)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import textwrap
from datetime import UTC, datetime, timedelta
from pathlib import Path


def _get_recent_commits(repo_root: Path, days: int) -> list[dict[str, str]]:
    """Return list of {hash, message, diff} for commits in last N days."""
    since = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")
    result = subprocess.run(
        ["git", "log", f"--since={since}", "--format=%H|%s", "--name-only"],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    if result.returncode != 0:
        return []

    commits = []
    lines = result.stdout.strip().splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if "|" in line:
            parts = line.split("|", 1)
            commit_hash = parts[0]
            message = parts[1] if len(parts) > 1 else ""
            i += 1
            # Collect changed files until next commit or end
            changed_files = []
            while i < len(lines) and "|" not in lines[i] and lines[i].strip():
                changed_files.append(lines[i].strip())
                i += 1
            # Skip blank separator
            while i < len(lines) and not lines[i].strip():
                i += 1

            # Get diff for this commit
            diff_result = subprocess.run(
                [
                    "git",
                    "show",
                    "--stat",
                    "--patch",
                    "--unified=3",
                    commit_hash,
                    "--",
                    "src/",
                    "docs/",
                ],
                capture_output=True,
                text=True,
                cwd=repo_root,
            )
            diff = diff_result.stdout if diff_result.returncode == 0 else ""

            commits.append(
                {
                    "hash": commit_hash[:8],
                    "message": message,
                    "files": changed_files,
                    "diff": diff,
                }
            )
        else:
            i += 1

    return commits


def _read_existing_marker_ids(raw_markers_path: Path) -> list[str]:
    """Extract existing marker IDs from the extracted markers file."""
    if not raw_markers_path.exists():
        return []
    ids = []
    for line in raw_markers_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("### "):
            marker_id = line[4:].strip()
            if marker_id:
                ids.append(marker_id)
    return ids


def _build_prompt(
    commits: list[dict[str, str]], existing_ids: list[str], max_diff_chars: int
) -> str:
    """Build the LLM prompt."""
    commits_text_parts = []
    total_chars = 0
    for c in commits:
        diff_snippet = c["diff"][:max_diff_chars]
        if len(c["diff"]) > max_diff_chars:
            diff_snippet += "\n... [diff truncated] ..."
        part = f"Commit {c['hash']}: {c['message']}\n{diff_snippet}"
        if total_chars + len(part) > max_diff_chars * 2:
            commits_text_parts.append("... [remaining commits omitted to fit context] ...")
            break
        commits_text_parts.append(part)
        total_chars += len(part)

    commits_text = "\n\n---\n\n".join(commits_text_parts)

    existing_ids_text = (
        "\n".join(f"- {mid}" for mid in existing_ids) if existing_ids else "(none yet)"
    )

    return textwrap.dedent(f"""
    You are reviewing recent code and documentation changes in the Atman project
    (a psychological layer for AI agents). The project uses PLAYBOOK markers to
    flag generalizable engineering patterns applicable beyond this specific project.

    Existing PLAYBOOK marker IDs already in the codebase:
    {existing_ids_text}

    Your task: analyze the following recent commits and identify changes that
    introduce generalizable engineering patterns but do NOT have a PLAYBOOK marker.

    For each missed pattern you find:
    1. Pattern name (concise, kebab-case id)
    2. File and approximate line where marker should be added
    3. Suggested marker text (id, category, title, status: draft, 2-3 line body)
    4. Confidence: high / medium / low

    GENERALIZABLE means: the pattern can be described without project-specific
    terms ("reflection engine", "atman", "session manager", "experience store",
    "eigenstate"). Apply the substitution test: replace those terms with generic
    equivalents. If the resulting description still makes engineering sense — it
    is generalizable.

    SKIP changes that are:
    - Pure refactoring without new conceptual structure
    - Standard idiomatic code (using asyncio, pytest fixtures, Pydantic models)
    - Project-specific data model changes (adding a field to a model)
    - Bug fixes without new design patterns
    - Documentation corrections without new architectural concepts

    Output format for each suggestion:
    ---
    PATTERN: <kebab-case-id>
    FILE: <path>:<approximate_line>
    CONFIDENCE: high|medium|low
    MARKER:
    # id: <kebab-case-id>
    # category: design-patterns|process-patterns|architecture-decisions|failure-modes|templates
    # title: <Title>
    # status: draft
    #
    # <2-3 sentences describing the pattern without project-specific terms>
    ---

    If no patterns are missed, output: NO PATTERNS MISSED

    Recent commits to analyze:

    {commits_text}
    """).strip()


def _call_ollama(prompt: str, model: str, base_url: str) -> str:
    """Call Ollama API and return the response text."""
    try:
        import urllib.request

        payload = json.dumps(
            {
                "model": model,
                "prompt": prompt,
                "stream": False,
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            f"{base_url.rstrip('/')}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("response", "")
    except Exception as e:
        print(f"ERROR calling Ollama: {e}", file=sys.stderr)
        print("Make sure Ollama is running: ollama serve", file=sys.stderr)
        return ""


def _call_claude(prompt: str, model: str) -> str:
    """Call Anthropic Claude API and return the response text."""
    try:
        import anthropic

        client = anthropic.Anthropic()
        message = client.messages.create(
            model=model,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text
    except ImportError:
        print(
            "ERROR: 'anthropic' package not installed. Run: pip install anthropic", file=sys.stderr
        )
        return ""
    except Exception as e:
        print(f"ERROR calling Claude: {e}", file=sys.stderr)
        return ""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Suggest PLAYBOOK markers for recent commits that may have missed them."
    )
    parser.add_argument("--days", type=int, default=30, help="Analyze commits from last N days")
    parser.add_argument(
        "--provider",
        choices=["ollama", "claude"],
        default="ollama",
        help="LLM provider (default: ollama)",
    )
    parser.add_argument(
        "--ollama-model",
        default="llama3.1:8b",
        help="Ollama model name (default: llama3.1:8b)",
    )
    parser.add_argument(
        "--claude-model",
        default="claude-haiku-4-5",
        help="Anthropic model (default: claude-haiku-4-5)",
    )
    parser.add_argument(
        "--ollama-url",
        default="http://localhost:11434",
        help="Ollama API base URL",
    )
    parser.add_argument(
        "--source-repo",
        type=Path,
        default=Path("."),
        help="Repository root (default: current directory)",
    )
    parser.add_argument(
        "--raw-markers",
        type=Path,
        default=Path("../agent-playbook/raw/extracted-from-atman.md"),
        help="Path to extracted markers file for context",
    )
    parser.add_argument(
        "--max-diff-chars",
        type=int,
        default=12000,
        help="Truncate diff at N characters (default: 12000)",
    )
    args = parser.parse_args()

    repo_root = args.source_repo.resolve()
    if not repo_root.is_dir():
        print(f"ERROR: --source-repo path does not exist: {repo_root}", file=sys.stderr)
        return 1

    print(f"Analyzing commits from last {args.days} day(s)...", file=sys.stderr)
    commits = _get_recent_commits(repo_root, args.days)

    if not commits:
        print(f"No commits found in the last {args.days} day(s).", file=sys.stderr)
        return 0

    print(f"Found {len(commits)} commit(s). Reading existing markers...", file=sys.stderr)
    existing_ids = _read_existing_marker_ids(args.raw_markers.resolve())
    print(f"Existing marker IDs: {len(existing_ids)}", file=sys.stderr)

    prompt = _build_prompt(commits, existing_ids, args.max_diff_chars)

    print(f"Calling {args.provider}...", file=sys.stderr)
    if args.provider == "ollama":
        response = _call_ollama(prompt, args.ollama_model, args.ollama_url)
    else:
        response = _call_claude(prompt, args.claude_model)

    if not response:
        print("ERROR: No response from LLM provider.", file=sys.stderr)
        return 1

    print()
    print("=" * 60)
    print("PLAYBOOK MARKER SUGGESTIONS")
    print("=" * 60)
    print()
    print(response)
    print()
    print("=" * 60)
    print("NOTE: These are suggestions only. Review each one manually.")
    print("Add markers to the source code at the indicated locations.")
    print("Use 'status: draft' — the author will promote or remove.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
