#!/usr/bin/env python3
"""
Extract PLAYBOOK markers from Atman source files and generate a consolidated
output file for agent-playbook/raw/.

Usage:
    python scripts/extract_playbook.py [options]

Options:
    --source-repo PATH   Root of the source repository (default: current dir)
    --target PATH        Output file path (default: ../agent-playbook/raw/extracted-from-atman.md)
    --check              Validate markers only, do not write output (exit 1 on errors)
"""

from __future__ import annotations

import argparse
import contextlib
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

VALID_CATEGORIES = {
    "design-patterns",
    "process-patterns",
    "architecture-decisions",
    "failure-modes",
    "templates",
}

VALID_STATUSES = {"draft", "refined", "deprecated"}

REQUIRED_FIELDS = {"id", "category", "title", "status"}
OPTIONAL_FIELDS = {"extends", "since"}
ALL_FIELDS = REQUIRED_FIELDS | OPTIONAL_FIELDS

IGNORED_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache", ".ruff_cache"}


@dataclass
class PlaybookMarker:
    source_file: str
    source_line: int
    id: str
    category: str
    title: str
    status: str
    extends: str = ""
    since: str = ""
    body: str = ""


@dataclass
class ExtractionResult:
    markers: list[PlaybookMarker] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _is_ignored(path: Path, repo_root: Path) -> bool:
    """Return True if any component of the path (relative to repo root) is in IGNORED_DIRS."""
    try:
        rel = path.relative_to(repo_root)
    except ValueError:
        return False
    return any(part in IGNORED_DIRS for part in rel.parts)


def _read_gitignore_patterns(repo_root: Path) -> list[re.Pattern[str]]:
    """Read .gitignore and compile patterns (simplified: only path prefix matching)."""
    gitignore = repo_root / ".gitignore"
    patterns: list[re.Pattern[str]] = []
    if not gitignore.exists():
        return patterns
    for raw_line in gitignore.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # Convert simple glob patterns to regex (best-effort, not full gitignore spec)
        escaped = re.escape(line.rstrip("/"))
        escaped = escaped.replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
        with contextlib.suppress(re.error):
                patterns.append(re.compile(escaped))
    return patterns


def _is_gitignored(path: Path, repo_root: Path, patterns: list[re.Pattern[str]]) -> bool:
    try:
        rel = str(path.relative_to(repo_root))
    except ValueError:
        return False
    return any(p.search(rel) for p in patterns)


def _strip_fenced_code_blocks(content: str) -> str:
    """Replace content inside fenced code blocks with whitespace-preserving placeholders.

    This prevents markers in example code blocks from being extracted as real markers.
    Line count is preserved so source line numbers remain accurate.
    """
    result = []
    in_fence = False
    fence_char = ""
    for line in content.splitlines(keepends=True):
        stripped = line.strip()
        if not in_fence:
            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_fence = True
                fence_char = stripped[:3]
                result.append(line)  # keep the opening fence line
            else:
                result.append(line)
        else:
            if stripped.startswith(fence_char):
                in_fence = False
                result.append(line)  # keep the closing fence line
            else:
                # Replace line content with same-length whitespace to preserve line numbers
                result.append("\n")
    return "".join(result)


def _extract_from_markdown(content: str, source_file: str) -> tuple[list[PlaybookMarker], list[str]]:
    """Extract PLAYBOOK markers from HTML comments in Markdown files."""
    markers: list[PlaybookMarker] = []
    errors: list[str] = []

    # Remove content inside code blocks so example markers are not extracted
    processed = _strip_fenced_code_blocks(content)

    pattern = re.compile(
        r"<!--\s*PLAYBOOK\s*\n(.*?)-->",
        re.DOTALL,
    )

    for match in pattern.finditer(processed):
        # Determine approximate line number
        start_pos = match.start()
        line_num = processed[:start_pos].count("\n") + 1

        raw_block = match.group(1)
        marker, errs = _parse_marker_block(raw_block, source_file, line_num)
        errors.extend(errs)
        if marker is not None:
            markers.append(marker)

    return markers, errors


def _extract_from_python(content: str, source_file: str) -> tuple[list[PlaybookMarker], list[str]]:
    """Extract PLAYBOOK markers from # PLAYBOOK-START / # PLAYBOOK-END blocks in Python files."""
    markers: list[PlaybookMarker] = []
    errors: list[str] = []

    pattern = re.compile(
        r"^[ \t]*#\s*PLAYBOOK-START\s*\n((?:[ \t]*#[^\n]*\n)*?)[ \t]*#\s*PLAYBOOK-END",
        re.MULTILINE,
    )

    for match in pattern.finditer(content):
        start_pos = match.start()
        line_num = content[:start_pos].count("\n") + 1

        raw_block = match.group(1)
        # Strip leading whitespace and "# " from each line
        stripped_lines = []
        for line in raw_block.splitlines():
            stripped = re.sub(r"^[ \t]*#\s?", "", line)
            stripped_lines.append(stripped)
        clean_block = "\n".join(stripped_lines)

        marker, errs = _parse_marker_block(clean_block, source_file, line_num)
        errors.extend(errs)
        if marker is not None:
            markers.append(marker)

    return markers, errors


def _parse_marker_block(
    block: str, source_file: str, line_num: int
) -> tuple[PlaybookMarker | None, list[str]]:
    """Parse a raw marker block into a PlaybookMarker. Returns (marker, errors)."""
    errors: list[str] = []
    fields: dict[str, str] = {}
    body_lines: list[str] = []

    # Parse key: value lines at the start, then treat rest as body text
    in_fields = True
    for line in block.splitlines():
        if in_fields:
            kv_match = re.match(r"^([\w-]+)\s*:\s*(.*)$", line.strip())
            if kv_match:
                key = kv_match.group(1).lower()
                value = kv_match.group(2).strip()
                if key in ALL_FIELDS:
                    fields[key] = value
                # else: silently ignore unknown structured fields
                continue
            else:
                # First non-field line starts the body
                in_fields = False
        if not in_fields:
            body_lines.append(line)

    # Validate required fields
    for req in REQUIRED_FIELDS:
        if req not in fields or not fields[req]:
            errors.append(
                f"{source_file}:{line_num}: missing required field '{req}' in PLAYBOOK marker"
            )

    if "category" in fields and fields["category"] not in VALID_CATEGORIES:
        errors.append(
            f"{source_file}:{line_num}: invalid category '{fields['category']}'; "
            f"must be one of {sorted(VALID_CATEGORIES)}"
        )

    if "status" in fields and fields["status"] not in VALID_STATUSES:
        errors.append(
            f"{source_file}:{line_num}: invalid status '{fields['status']}'; "
            f"must be one of {sorted(VALID_STATUSES)}"
        )

    if errors:
        return None, errors

    marker = PlaybookMarker(
        source_file=source_file,
        source_line=line_num,
        id=fields["id"],
        category=fields["category"],
        title=fields["title"],
        status=fields["status"],
        extends=fields.get("extends", ""),
        since=fields.get("since", ""),
        body="\n".join(body_lines).strip(),
    )
    return marker, []


def extract_markers(repo_root: Path) -> ExtractionResult:
    """Walk repo_root and extract all PLAYBOOK markers from .md and .py files."""
    result = ExtractionResult()
    gitignore_patterns = _read_gitignore_patterns(repo_root)
    seen_ids: dict[str, str] = {}  # id -> source location

    for path in sorted(repo_root.rglob("*")):
        if not path.is_file():
            continue
        if _is_ignored(path, repo_root):
            continue
        if _is_gitignored(path, repo_root, gitignore_patterns):
            continue
        if path.suffix not in (".md", ".py"):
            continue

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        rel_path = str(path.relative_to(repo_root))

        if path.suffix == ".md":
            markers, errors = _extract_from_markdown(content, rel_path)
        else:
            markers, errors = _extract_from_python(content, rel_path)

        result.errors.extend(errors)

        for marker in markers:
            if marker.id in seen_ids:
                result.errors.append(
                    f"{rel_path}:{marker.source_line}: duplicate PLAYBOOK id '{marker.id}' "
                    f"(first seen at {seen_ids[marker.id]})"
                )
            else:
                seen_ids[marker.id] = f"{rel_path}:{marker.source_line}"
                result.markers.append(marker)

    return result


def _get_current_commit(repo_root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=repo_root,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except OSError:
        return "unknown"


def generate_output(markers: list[PlaybookMarker], repo_root: Path) -> str:
    """Generate the Markdown output for agent-playbook/raw/extracted-from-atman.md."""
    now = datetime.now(UTC).strftime("%Y-%m-%d")
    commit = _get_current_commit(repo_root)

    lines: list[str] = [
        "# Extracted from atman",
        "",
        f"Last updated: {now}  ",
        "Source repo: github.com/hleserg/atman  ",
        f"Source commit: {commit}",
        "",
        "This file is auto-generated. Do not edit directly.",
        "Edit PLAYBOOK markers in atman source files instead.",
        "",
    ]

    if not markers:
        lines.append("*(No PLAYBOOK markers found)*")
        return "\n".join(lines)

    # Group by category
    by_category: dict[str, list[PlaybookMarker]] = {}
    for m in markers:
        by_category.setdefault(m.category, []).append(m)

    for category in sorted(by_category):
        lines.append(f"## {category}")
        lines.append("")
        for marker in sorted(by_category[category], key=lambda m: m.id):
            lines.append(f"### {marker.id}")
            lines.append(f"**Status**: {marker.status}  ")
            lines.append(f"**Title**: {marker.title}  ")
            lines.append(f"**Source**: {marker.source_file}:{marker.source_line}  ")
            if marker.extends:
                lines.append(f"**Extends**: {marker.extends}  ")
            if marker.since:
                lines.append(f"**Since**: {marker.since}  ")
            if marker.body:
                lines.append("")
                lines.append(marker.body)
            lines.append("")
            lines.append("---")
            lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract PLAYBOOK markers from Atman source files.")
    parser.add_argument(
        "--source-repo",
        type=Path,
        default=Path("."),
        help="Root of the source repository (default: current directory)",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=Path("../agent-playbook/raw/extracted-from-atman.md"),
        help="Output file path",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate markers only, do not write output. Exit 1 on validation errors.",
    )
    args = parser.parse_args()

    repo_root = args.source_repo.resolve()
    if not repo_root.is_dir():
        print(f"ERROR: --source-repo path does not exist: {repo_root}", file=sys.stderr)
        return 1

    result = extract_markers(repo_root)

    if result.errors:
        for err in result.errors:
            print(f"ERROR: {err}", file=sys.stderr)
        print(
            f"\n{len(result.errors)} validation error(s). No output written.",
            file=sys.stderr,
        )
        return 1

    marker_count = len(result.markers)
    category_counts = {}
    for m in result.markers:
        category_counts[m.category] = category_counts.get(m.category, 0) + 1

    if args.check:
        print(
            f"OK: {marker_count} PLAYBOOK marker(s) found, all valid.",
            file=sys.stderr,
        )
        for cat, count in sorted(category_counts.items()):
            print(f"  {cat}: {count}", file=sys.stderr)
        return 0

    # Write output
    output = generate_output(result.markers, repo_root)
    target = args.target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(output, encoding="utf-8")

    print(f"OK: extracted {marker_count} marker(s) to {target}", file=sys.stderr)
    for cat, count in sorted(category_counts.items()):
        print(f"  {cat}: {count}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
