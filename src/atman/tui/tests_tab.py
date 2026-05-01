"""Tests tab: run full suite, live log, progress bar, statistics, log filters."""

from __future__ import annotations

import asyncio
import contextlib
import traceback
from pathlib import Path
from typing import Any

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, ProgressBar, RichLog, Static

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
    """Single column: controls, log, progress, stats."""

    DEFAULT_CSS = """
    TestsTab {
        height: 1fr;
    }
    TestsTab #tests-toolbar {
        height: auto;
        width: 100%;
        layout: horizontal;
        margin-bottom: 1;
    }
    /* Вся гибкая высота вкладки — здесь: сначала лог, под ним прогресс и статистика */
    TestsTab #tests-body {
        height: 1fr;
        width: 100%;
        min-height: 0;
    }
    TestsTab #tests-log-wrap {
        height: 1fr;
        min-height: 8;
        border: solid $boost;
        background: $surface;
    }
    /* Accent border only on log area (no full-panel tint) */
    TestsTab #tests-log-wrap.-out-ok {
        border: tall $success;
    }
    TestsTab #tests-log-wrap.-out-err {
        border: tall $error;
    }
    TestsTab #tests-log {
        height: 1fr;
    }
    TestsTab #tests-progress-block {
        width: 100%;
        height: auto;
        margin: 0;
    }
    TestsTab #tests-progress-label {
        width: 100%;
        height: auto;
        margin: 0;
        padding: 0;
    }
    TestsTab #tests-progress-row {
        width: 100%;
        height: 3;
        min-height: 3;
        margin: 0;
        layout: horizontal;
    }
    TestsTab #tests-progress {
        width: 1fr;
        height: 100%;
        min-height: 3;
    }
    TestsTab #tests-stats {
        height: auto;
        max-height: 12;
        border: solid $boost;
        padding: 0 1;
        background: $boost;
    }
    TestsTab #tests-stats.-stats-ok {
        background: $success-muted;
        color: $text-success;
    }
    TestsTab #tests-stats.-stats-err {
        background: $error-muted;
        color: $text-error;
    }
    """

    def __init__(self, repo_root: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._repo = repo_root
        self._nodeids: list[str] = []
        self._last_full_log: str = ""
        # Must not use ``_running`` — Textual's MessagePump reserves it for the message loop.
        self._pytest_busy = False
        self._junit_path = repo_root / ".atman" / "tui-cache" / "junit.xml"

    def compose(self) -> ComposeResult:
        with Horizontal(id="tests-toolbar"):
            yield Button(
                "Запустить тесты",
                id="btn-tests-run",
                variant="primary",
                compact=True,
            )
            yield Button(
                "Только ошибки",
                id="btn-tests-errors",
                disabled=True,
                compact=True,
            )
            yield Button(
                "Полный вывод",
                id="btn-tests-full",
                disabled=True,
                compact=True,
            )
            yield Button("Очистить лог", id="btn-tests-clear", compact=True)
        with Vertical(id="tests-body"):
            with Vertical(id="tests-log-wrap"):
                yield RichLog(
                    id="tests-log",
                    highlight=False,
                    max_lines=12000,
                    auto_scroll=True,
                )
            with Vertical(id="tests-progress-block"):
                yield Static("", id="tests-progress-label")
                with Horizontal(id="tests-progress-row"):
                    yield ProgressBar(
                        total=100,
                        show_eta=False,
                        show_percentage=True,
                        show_bar=True,
                        id="tests-progress",
                    )
            yield Static(
                "Нажмите «Запустить тесты». После прогона здесь появится статистика.",
                id="tests-stats",
            )

    def on_mount(self) -> None:
        self._junit_path.parent.mkdir(parents=True, exist_ok=True)
        pb = self.query_one("#tests-progress", ProgressBar)
        pb.update(total=100.0, progress=0.0)

    def _reset_log_chrome(self) -> None:
        wrap = self.query_one("#tests-log-wrap", Vertical)
        stats = self.query_one("#tests-stats", Static)
        wrap.remove_class("-out-ok", "-out-err")
        stats.remove_class("-stats-ok", "-stats-err")

    def _set_run_chrome(self, *, ok: bool) -> None:
        wrap = self.query_one("#tests-log-wrap", Vertical)
        stats = self.query_one("#tests-stats", Static)
        wrap.remove_class("-out-ok", "-out-err")
        stats.remove_class("-stats-ok", "-stats-err")
        if ok:
            wrap.add_class("-out-ok")
            stats.add_class("-stats-ok")
        else:
            wrap.add_class("-out-err")
            stats.add_class("-stats-err")

    @on(Button.Pressed, "#btn-tests-run")
    def run_pressed(self) -> None:
        self.run_pytest_suite()

    @work(group="tests", exclusive=False, exit_on_error=False)
    async def run_pytest_suite(self) -> None:
        if self._pytest_busy:
            self.app.notify("Тесты уже выполняются.", severity="warning")
            return
        self._pytest_busy = True
        self._last_full_log = ""
        self._reset_log_chrome()

        log_w = self.query_one("#tests-log", RichLog)
        errs = self.query_one("#btn-tests-errors", Button)
        full_btn = self.query_one("#btn-tests-full", Button)
        run_btn = self.query_one("#btn-tests-run", Button)
        stats_panel = self.query_one("#tests-stats", Static)
        try:
            log_w.clear()
            errs.disabled = True
            full_btn.disabled = True
            run_btn.disabled = True

            stats_panel.remove_class("-stats-ok", "-stats-err")
            stats_panel.update("Сбор списка тестов…")
            log_w.write("$ " + " ".join(pytest_cmd("tests/", "--collect-only", "-q")))

            buf: list[str] = []

            def on_collect_line(line: str) -> None:
                buf.append(line)
                log_w.write(line.rstrip("\n"))

            collect_code = await stream_command(
                pytest_cmd("tests/", "--collect-only", "-q"),
                self._repo,
                on_line=on_collect_line,
            )
            if collect_code != 0:
                log_w.write(
                    f"\n⚠ collect-only завершился с кодом {collect_code} "
                    "(список тестов может быть неполным).\n",
                )
            self._nodeids = parse_collect_only("".join(buf))
            total = max(1, len(self._nodeids))
            kinds = classify_nodeids(self._nodeids)

            pb = self.query_one("#tests-progress", ProgressBar)
            lbl = self.query_one("#tests-progress-label", Static)
            pb.update(total=float(total), progress=0.0)
            lbl.update(f"0% — 0 / {total} тестов")

            log_w.write(
                f"Собрано тестов: {total} (функций: {kinds.plain_functions}, "
                f"методов классов: {kinds.class_methods}). Запуск pytest…",
            )

            with contextlib.suppress(OSError):
                self._junit_path.unlink(missing_ok=True)

            junit_arg = f"--junitxml={self._junit_path}"
            argv = pytest_cmd(
                "tests/",
                "-v",
                "--cov=atman",
                "--cov-fail-under=90",
                "--cov-report=term-missing",
                junit_arg,
            )
            log_w.write("$ " + " ".join(argv))

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
                    pct = 100.0 * min(completed, total) / total
                    pb.update(progress=min(float(completed), float(total)))
                    lbl.update(
                        f"{pct:.0f}% — {completed} / {total} тестов завершено "
                        f"(ok {passed}, fail {failed}, err {errors}, skip {skipped})",
                    )

            code = await stream_command(argv, self._repo, on_line=on_line)

            summary = parse_summary_line(self._last_full_log)
            cov_pct = parse_coverage_total_percent(self._last_full_log)
            jcounts = parse_junit_counts(self._junit_path)
            fail_n = junit_failure_error_count(self._junit_path)

            # Trust process exit code; stale JUnit is removed before the run.
            ok_exit = code == 0
            self._set_run_chrome(ok=ok_exit)

            pb.update(progress=float(total))
            if summary:
                done = summary.passed + summary.failed + summary.errors + summary.skipped
                lbl.update(
                    f"Готово: 100% — выполнено {done} из ~{total} "
                    f"(pytest: {summary.passed} passed, {summary.failed} failed)",
                )
            else:
                lbl.update(f"Готово: 100% — exit code {code}")

            lines: list[str] = []
            if summary:
                lines.append(
                    f"Итог: пройдено {summary.passed}, провалено {summary.failed}, "
                    f"ошибок {summary.errors}, пропущено {summary.skipped}",
                )
                if summary.duration_seconds is not None:
                    lines.append(f"Время pytest: {summary.duration_seconds:.2f} с")
                denom = max(1, summary.passed + summary.failed + summary.errors)
                rate = 100.0 * summary.passed / denom
                lines.append(f"Доля успешных (без skip): {rate:.1f}%")
            lines.append(f"Код выхода процесса: {code}")
            lines.append(
                f"JUnit: всего {jcounts['tests']}, failures {jcounts['failures']}, "
                f"errors {jcounts['errors']}, skipped {jcounts['skipped']}",
            )
            if cov_pct is not None:
                lines.append(f"Покрытие (TOTAL): {cov_pct:.1f}%")
            lines.append(f"Собрано при collect-only: {total} тестов")

            stats_panel.update("\n".join(lines))

            if fail_n > 0 or not ok_exit:
                errs.disabled = False
                full_btn.disabled = False
            elif self._last_full_log.strip():
                errs.disabled = True
                full_btn.disabled = False

            if ok_exit:
                self.app.notify(
                    f"Тесты завершены (exit {code}).",
                    severity="information",
                )
            else:
                self.app.notify(
                    f"Тесты завершились с ошибкой (exit {code}). См. лог и статистику.",
                    severity="error",
                    timeout=12,
                )
        except asyncio.CancelledError:
            log_w.write("\nЗапуск тестов прерван.\n")
            raise
        except Exception as e:
            log_w.write(traceback.format_exc())
            stats_panel.update(f"Ошибка: {e}\n\nСм. трассировку в логе выше.")
            self.app.notify(
                f"Ошибка при прогоне тестов: {e}",
                severity="error",
                timeout=15,
            )
        finally:
            self._pytest_busy = False
            run_btn.disabled = False

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
            log_w.write("Нет секций с ошибками в логе (всё зелёное).")
        self.app.notify("Показан фрагмент только с ошибками.", severity="information")

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
        self._reset_log_chrome()
        self.query_one("#tests-stats", Static).update(
            "Лог очищен. Запустите тесты снова для новой статистики.",
        )
        self.query_one("#tests-progress-label", Static).update("")
        pb = self.query_one("#tests-progress", ProgressBar)
        pb.update(total=100.0, progress=0.0)
