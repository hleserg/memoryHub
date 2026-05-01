"""Parse pytest collect-only output, verbose progress lines, summaries, and failure excerpts."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET  # nosec B405
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PytestSummary:
    """Counts parsed from pytest's final session summary line."""

    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    deselected: int = 0
    xfailed: int = 0
    xpassed: int = 0
    duration_seconds: float | None = None


@dataclass
class TestKindStats:
    """Rough classification from nodeids (no AST)."""

    total: int = 0
    class_methods: int = 0
    plain_functions: int = 0


_RESULT_LINE_RE = re.compile(
    r"^(?P<nodeid>.+?)\s+(?P<status>PASSED|FAILED|SKIPPED|ERROR|XFAIL|XPASS)\s",
)
_SUMMARY_LINE_RE = re.compile(
    r"=+\s*(?P<body>.*?)\s*=+",
)
_COUNT_FRAG_RE = re.compile(
    r"(?P<n>\d+)\s+(?P<kind>passed|failed|error|errors|skipped|deselected|xfailed|xpassed)",
    re.IGNORECASE,
)
_DURATION_RE = re.compile(r"in\s+([\d.]+)\s*s\b", re.IGNORECASE)
_COV_TOTAL_RE = re.compile(
    r"^TOTAL\s+\d+\s+\d+\s+\d+\s+\d+\s+(\d+)%",
    re.MULTILINE,
)


def parse_collect_only(stdout: str) -> list[str]:
    """Return test nodeids from ``pytest --collect-only -q`` stdout."""
    nodeids: list[str] = []
    for line in stdout.splitlines():
        s = line.strip()
        if not s or s.startswith("="):
            continue
        if "error" in s.lower() and "during collection" in s.lower():
            continue
        if re.search(r"\d+\s+tests?\s+collected", s):
            continue
        if "::" not in s:
            continue
        if s.startswith("tests/") or s.startswith("test"):
            nodeids.append(s)
    return nodeids


def parse_verbose_result_line(line: str) -> tuple[str, str] | None:
    """If ``line`` is a pytest ``-v`` result line, return (nodeid, status)."""
    m = _RESULT_LINE_RE.match(line.strip())
    if not m:
        return None
    return m.group("nodeid"), m.group("status")


def classify_nodeids(nodeids: list[str]) -> TestKindStats:
    """Classify tests as plain functions vs class methods using nodeid shape."""
    stats = TestKindStats(total=len(nodeids))
    class_re = re.compile(r"::Test[A-Za-z0-9_]+::test_")
    for nid in nodeids:
        if class_re.search(nid):
            stats.class_methods += 1
        else:
            stats.plain_functions += 1
    return stats


def parse_summary_line(log: str) -> PytestSummary | None:
    """Parse the last pytest banner line like ``==== 3 passed in 0.5s ========``."""
    candidates: list[str] = []
    for line in log.splitlines():
        ls = line.strip()
        if (
            ls.startswith("=")
            and ls.endswith("=")
            and " in " in ls
            and "s" in ls
            and any(
                k in ls.lower()
                for k in ("passed", "failed", "error", "skipped", "deselected", "warnings")
            )
        ):
            candidates.append(ls)
    if not candidates:
        return None
    last = candidates[-1]
    m = _SUMMARY_LINE_RE.match(last)
    body = m.group("body") if m else last.strip("=")

    summary = PytestSummary()
    for cm in _COUNT_FRAG_RE.finditer(body):
        n = int(cm.group("n"))
        kind = cm.group("kind").lower()
        if kind == "passed":
            summary.passed = n
        elif kind == "failed":
            summary.failed = n
        elif kind in ("error", "errors"):
            summary.errors = n
        elif kind == "skipped":
            summary.skipped = n
        elif kind == "deselected":
            summary.deselected = n
        elif kind == "xfailed":
            summary.xfailed = n
        elif kind == "xpassed":
            summary.xpassed = n

    dm = _DURATION_RE.search(body)
    if dm:
        summary.duration_seconds = float(dm.group(1))
    return summary


def parse_coverage_total_percent(log: str) -> float | None:
    """Extract ``TOTAL`` coverage percent from terminal coverage report."""
    m = _COV_TOTAL_RE.search(log)
    if not m:
        return None
    return float(m.group(1))


_FAIL_HEAD = re.compile(r"^=+\s*FAILURES\s*=+$")
_ERR_HEAD = re.compile(r"^=+\s*ERRORS\s*=+$")


def extract_failure_only_log(full_log: str) -> str:
    """Return only failure/error/traceback sections and short test summary."""
    lines = full_log.splitlines()
    chunks: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        stripped = lines[i].strip()
        if _FAIL_HEAD.match(stripped):
            block = [lines[i]]
            i += 1
            while i < n:
                ns = lines[i].strip()
                if ns.startswith("=") and len(ns) > 15:
                    if "short test summary" in lines[i].lower():
                        break
                    if _ERR_HEAD.match(ns):
                        break
                block.append(lines[i])
                i += 1
            chunks.append("\n".join(block))
            continue
        if _ERR_HEAD.match(stripped):
            block = [lines[i]]
            i += 1
            while i < n:
                ns = lines[i].strip()
                if ns.startswith("=") and len(ns) > 15 and "short test summary" in lines[i].lower():
                    break
                block.append(lines[i])
                i += 1
            chunks.append("\n".join(block))
            continue
        if "short test summary info" in lines[i].lower() and stripped.startswith("="):
            block = [lines[i]]
            i += 1
            while i < n:
                ns = lines[i].strip()
                block.append(lines[i])
                i += 1
                if (
                    ns.startswith("=")
                    and len(ns) > 10
                    and ("failed in" in ns.lower() or "passed in" in ns.lower())
                ):
                    break
            chunks.append("\n".join(block))
            continue
        i += 1

    if not chunks:
        slim: list[str] = []
        for line in lines:
            if line.startswith("FAILED ") or line.startswith("ERROR "):
                slim.append(line)
        summary = parse_summary_line(full_log)
        if summary and (summary.failed or summary.errors):
            for line in reversed(lines):
                ls = line.strip()
                if ls.startswith("=") and ("failed" in ls.lower() or "error" in ls.lower()):
                    slim.append(ls)
                    break
        if slim:
            return "\n".join(slim)
        return ""

    return "\n\n".join(c for c in chunks if c).strip()


def junit_failure_error_count(path: Path) -> int:
    """Return number of failing testcases in a JUnit XML file (failures + errors)."""
    data = parse_junit_counts(path)
    return int(data["failures"]) + int(data["errors"])


def parse_junit_counts(path: Path) -> dict[str, int]:
    """Return tests, failures, errors, skipped from JUnit XML (pytest-compatible)."""
    out: dict[str, int] = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    if not path.is_file():
        return out
    try:
        tree = ET.parse(path)  # nosec B314
    except ET.ParseError:
        return out
    root = tree.getroot()
    for el in root.iter():
        tag = el.tag.split("}")[-1] if "}" in el.tag else el.tag
        if tag == "testsuite":
            out["tests"] += int(el.attrib.get("tests", "0") or "0")
            out["failures"] += int(el.attrib.get("failures", "0") or "0")
            out["errors"] += int(el.attrib.get("errors", "0") or "0")
            out["skipped"] += int(el.attrib.get("skipped", "0") or "0")
    return out
