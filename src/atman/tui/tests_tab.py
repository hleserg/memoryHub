"""Tests tab: collect-only list, pytest runs, progress, statistics, failure filter."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Label, ListItem, ListView, ProgressBar, RichLog, Static

from atman.tui.cmd import pytest_cmd
from atman.tui.pytest_utils import (
    classify_nodeids,
    extract_failure_only_log,
    junit_failure_error_count,
    parse_collect_only,
    parse_coverage_total_percent,
    parse_junit_counts,
    parse_summary_line,
    parse_verbose_result_line,
)
from atman.tui.runner import stream_command


class TestsTab(Vertical):
    """Left: actions + list; right: log + filter buttons."""

    DEFAULT_CSS = """
    TestsTab {
        height: 1fr;
    }
    TestsTab #tests-left {
        width: 38%;
        min-width: 28;
        height: 1fr;
    }
    TestsTab #tests-right {
        width: 1fr;
        height: 1fr;
    }
    TestsTab #tests-list {
        height: 1fr;
        border: solid $boost;
    }
    TestsTab #tests-log {
        height: 1fr;
        border: solid $boost;
        background: $surface;
    }
    TestsTab #tests-stats {
        height: auto;
        max-height: 10;
        border: solid $boost;
        padding: 0 1;
    }
    TestsTab #tests-meter {
        height: auto;
        padding: 0 1;
    }
    """

    def __init__(self, repo_root: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._repo = repo_root
        self._nodeids: list[str] = []
        self._last_full_log: str = ""
        self._running = False
        self._junit_path = repo_root / ".atman" / "tui-cache" / "junit.xml"

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="tests-left"):
                yield Button("Refresh list", id="btn-tests-refresh", variant="primary")
                yield Button("Run all tests", id="btn-tests-all")
                yield Button("Run selected", id="btn-tests-one")
                yield ProgressBar(total=100, show_eta=False, id="tests-progress")
                yield Static(
                    "Progress: —   Success (finished): —%",
                    id="tests-meter",
                )
                yield Static(
                    "Statistics will appear after a run.\nUse “Refresh list” to load tests.",
                    id="tests-stats",
                )
                yield ListView(id="tests-list")
            with Vertical(id="tests-right"):
                with Horizontal():
                    yield Button(
                        "Show errors only",
                        id="btn-tests-errors",
                        disabled=True,
                    )
                    yield Button(
                        "Show full output",
                        id="btn-tests-full",
                        disabled=True,
                    )
                    yield Button("Clear log", id="btn-tests-clear")
                yield RichLog(
                    id="tests-log",
                    highlight=False,
                    max_lines=8000,
                    auto_scroll=True,
                )

    def on_mount(self) -> None:
        self._junit_path.parent.mkdir(parents=True, exist_ok=True)

    @on(Button.Pressed, "#btn-tests-refresh")
    def refresh_tests(self) -> None:
        self.refresh_test_list()

    @work(group="tests", exclusive=True, exit_on_error=False)
    async def refresh_test_list(self) -> None:
        log = self.query_one("#tests-log", RichLog)
        log.write("[dim]Collecting tests…[/]")
        argv = pytest_cmd("tests/", "--collect-only", "-q")
        buf: list[str] = []

        code = await stream_command(argv, self._repo, on_line=buf.append)
        text = "".join(buf)
        self._nodeids = parse_collect_only(text)
        lv = self.query_one("#tests-list", ListView)
        await lv.clear()
        if self._nodeids:
            await lv.extend(ListItem(Label(n)) for n in self._nodeids)
        log.write(f"[dim]Collected {len(self._nodeids)} tests (exit {code}).[/]")
        kinds = classify_nodeids(self._nodeids)
        stats = self.query_one("#tests-stats", Static)
        stats.update(
            f"Collected: {kinds.total}\n"
            f"• Plain functions: {kinds.plain_functions}\n"
            f"• Class methods: {kinds.class_methods}",
        )
        pb = self.query_one("#tests-progress", ProgressBar)
        pb.update(total=max(1, len(self._nodeids)), progress=0)

    @on(Button.Pressed, "#btn-tests-all")
    def run_all_pressed(self) -> None:
        self.run_pytest_suite(full=True)

    @on(Button.Pressed, "#btn-tests-one")
    def run_one_pressed(self) -> None:
        lv = self.query_one("#tests-list", ListView)
        if lv.index is None or not self._nodeids:
            self.app.notify("Select a test in the list (refresh first).", severity="warning")
            return
        target = self._nodeids[lv.index]
        self.run_pytest_suite(full=False, target=target)

    @work(group="tests", exclusive=True, exit_on_error=False)
    async def run_pytest_suite(self, *, full: bool, target: str | None = None) -> None:
        if self._running:
            self.app.notify("A test run is already in progress.", severity="warning")
            return
        self._running = True
        self._last_full_log = ""
        log_w = self.query_one("#tests-log", RichLog)
        log_w.clear()
        errs = self.query_one("#btn-tests-errors", Button)
        full_btn = self.query_one("#btn-tests-full", Button)
        errs.disabled = True
        full_btn.disabled = True
        for b in self.query(Button):
            if b.id in ("btn-tests-all", "btn-tests-one", "btn-tests-refresh"):
                b.disabled = True

        if not self._nodeids:
            buf: list[str] = []
            await stream_command(
                pytest_cmd("tests/", "--collect-only", "-q"),
                self._repo,
                on_line=buf.append,
            )
            self._nodeids = parse_collect_only("".join(buf))

        pb = self.query_one("#tests-progress", ProgressBar)
        meter = self.query_one("#tests-meter", Static)
        total = max(1, len(self._nodeids))
        pb.update(total=float(total), progress=0)
        meter.update("Starting…")

        junit_arg = f"--junitxml={self._junit_path}"
        if full:
            argv = pytest_cmd(
                "tests/",
                "-v",
                "--cov=atman",
                "--cov-fail-under=90",
                "--cov-report=term-missing",
                junit_arg,
            )
        else:
            assert target is not None
            argv = pytest_cmd(target, "-v", junit_arg)

        completed = 0
        passed = 0
        failed = 0
        errors = 0
        skipped = 0

        def on_line(line: str) -> None:
            nonlocal completed, passed, failed, errors, skipped
            self._last_full_log += line
            log_w.write(line.rstrip("\n"))
            pr = parse_verbose_result_line(line)
            if pr:
                _nid, st = pr
                completed += 1
                if st == "PASSED":
                    passed += 1
                elif st == "FAILED":
                    failed += 1
                elif st == "ERROR":
                    errors += 1
                elif st == "SKIPPED":
                    skipped += 1
                elif st == "XPASS":
                    passed += 1
                pb.update(progress=min(float(completed), float(total)))
                denom = max(1, passed + failed + errors)
                rate = 100.0 * passed / denom
                meter.update(
                    f"Progress: {completed}/{total}   "
                    f"Success (finished): {rate:.0f}% "
                    f"(pass {passed} / fail+err {failed + errors})",
                )

        try:
            code = await stream_command(argv, self._repo, on_line=on_line)
        finally:
            self._running = False
            for b in self.query(Button):
                if b.id in ("btn-tests-all", "btn-tests-one", "btn-tests-refresh"):
                    b.disabled = False

        summary = parse_summary_line(self._last_full_log)
        cov_pct = parse_coverage_total_percent(self._last_full_log)
        jcounts = parse_junit_counts(self._junit_path)
        fail_n = junit_failure_error_count(self._junit_path)

        stats = self.query_one("#tests-stats", Static)
        lines = [
            f"Exit code: {code}",
            f"JUnit: tests={jcounts['tests']} fail={jcounts['failures']} err={jcounts['errors']}",
        ]
        if summary:
            lines.append(
                f"Summary: {summary.passed} passed, {summary.failed} failed, "
                f"{summary.errors} errors, {summary.skipped} skipped",
            )
            if summary.duration_seconds is not None:
                lines.append(f"Duration (pytest): {summary.duration_seconds:.2f}s")
        if cov_pct is not None:
            lines.append(f"Coverage (TOTAL): {cov_pct:.1f}%")
        stats.update("\n".join(lines))

        if fail_n > 0:
            errs.disabled = False
            full_btn.disabled = False
        elif self._last_full_log.strip():
            errs.disabled = True
            full_btn.disabled = False

        if summary:
            denom = max(1, summary.passed + summary.failed + summary.errors)
            rate = 100.0 * summary.passed / denom
            meter.update(
                f"Done: {summary.passed} passed / {summary.failed} failed / {summary.errors} errors — "
                f"success rate {rate:.0f}%",
            )
            pb.update(progress=float(total))

        self.app.notify(
            f"Tests finished (exit {code}).", severity="information" if code == 0 else "error"
        )

    @on(Button.Pressed, "#btn-tests-errors")
    def show_errors(self) -> None:
        if not self._last_full_log.strip():
            return
        slim = extract_failure_only_log(self._last_full_log)
        log_w = self.query_one("#tests-log", RichLog)
        log_w.clear()
        if slim:
            for line in slim.splitlines():
                log_w.write(line)
        else:
            log_w.write("[green]No failure sections in the log (all green).[/]")
        self.app.notify("Showing errors-only excerpt.", severity="information")

    @on(Button.Pressed, "#btn-tests-full")
    def show_full(self) -> None:
        if not self._last_full_log.strip():
            return
        log_w = self.query_one("#tests-log", RichLog)
        log_w.clear()
        for line in self._last_full_log.splitlines():
            log_w.write(line)

    @on(Button.Pressed, "#btn-tests-clear")
    def clear_log(self) -> None:
        self.query_one("#tests-log", RichLog).clear()
