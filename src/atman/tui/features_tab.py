"""Features tab: button picker, then sidebar + README or command output."""

from __future__ import annotations

from pathlib import Path
from shutil import which
from typing import Any

from rich.text import Text
from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.widgets import Button, Markdown, RichLog, Static

from atman.tui.cmd import python_script_cmd
from atman.tui.features_registry import FEATURES, FeatureInfo
from atman.tui.runner import stream_command


class FeaturesTab(Vertical):
    DEFAULT_CSS = """
    FeaturesTab {
        height: 1fr;
    }
    FeaturesTab #feat-pick-screen {
        height: 1fr;
        align: center middle;
        border: solid $boost;
    }
    FeaturesTab #feat-pick-inner {
        width: 60;
        height: auto;
        max-height: 100%;
    }
    FeaturesTab #feat-detail-screen {
        height: 1fr;
    }
    FeaturesTab #feat-sidebar {
        width: 36%;
        min-width: 28;
        height: 1fr;
        border: solid $boost;
        padding: 0 1;
    }
    FeaturesTab #feat-desc {
        height: auto;
        max-height: 14;
        border: solid $boost;
        padding: 0 1;
        margin-bottom: 1;
    }
    FeaturesTab #feat-actions {
        height: auto;
        layout: vertical;
        margin-top: 1;
    }
    FeaturesTab #feat-actions Button {
        margin-bottom: 1;
    }
    FeaturesTab #feat-workarea {
        width: 1fr;
        height: 1fr;
        border: solid $boost;
    }
    FeaturesTab #feat-right-readme {
        height: 1fr;
        border: solid $boost;
    }
    FeaturesTab #feat-right-output {
        border: solid $boost;
        background: $surface;
    }
    FeaturesTab #feat-right-output.-run-error {
        border: tall $error;
        background: $error-muted;
    }
    FeaturesTab #feat-right-output.-run-ok {
        border: tall $success;
        background: $success-muted;
    }
    FeaturesTab #feat-run-status {
        height: auto;
        padding: 0 1;
        background: $boost;
    }
    FeaturesTab #feat-run-status.-st-err {
        color: $text-error;
        text-style: bold;
        background: $error-muted;
    }
    FeaturesTab #feat-run-status.-st-ok {
        color: $text-success;
        background: $success-muted;
    }
    FeaturesTab #feat-log {
        height: 1fr;
        min-height: 8;
        border: solid $boost;
    }
    """

    def __init__(self, repo_root: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._repo = repo_root
        self._current: FeatureInfo | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="feat-pick-screen"), Vertical(id="feat-pick-inner"):
            yield Static("[b]Выберите фичу[/b]", id="feat-pick-title")
            for f in FEATURES:
                yield Button(f.title, id=f"feat-pick-{f.slug}", variant="primary")
        with Horizontal(id="feat-detail-screen"):
            with Vertical(id="feat-sidebar"):
                yield Static("", id="feat-desc")
                with Vertical(id="feat-actions"):
                    yield Button("README (EN)", id="feat-readme-en")
                    yield Button("README (ru)", id="feat-readme-ru")
                    yield Button("Demo: paced", id="feat-demo-slow")
                    yield Button("Demo: fast", id="feat-demo-fast")
                    yield Button("Install dev deps", id="feat-install", variant="warning")
                    yield Button("← К списку фич", id="feat-back", variant="default")
            with Vertical(id="feat-workarea"):
                with ScrollableContainer(id="feat-right-readme"):
                    yield Markdown("", id="feat-md-body")
                with Vertical(id="feat-right-output"):
                    yield Static("", id="feat-run-status")
                    yield RichLog(
                        id="feat-log",
                        highlight=True,
                        markup=True,
                        max_lines=4000,
                        auto_scroll=True,
                    )

    def on_mount(self) -> None:
        self.query_one("#feat-detail-screen", Horizontal).display = False
        self.query_one("#feat-right-output", Vertical).display = False
        self._show_picker()

    def _show_picker(self) -> None:
        self._current = None
        pick = self.query_one("#feat-pick-screen")
        detail = self.query_one("#feat-detail-screen")
        pick.display = True
        detail.display = False

    def _show_detail(self, info: FeatureInfo) -> None:
        self._current = info
        pick = self.query_one("#feat-pick-screen")
        detail = self.query_one("#feat-detail-screen")
        pick.display = False
        detail.display = True

        desc = self.query_one("#feat-desc", Static)
        paths = "\n".join(f"• {p}" for p in info.related_paths)
        desc.update(
            f"[b]{info.title}[/b] ({info.slug})\n\n{info.summary}\n\n[b]Paths[/b]\n{paths}",
        )
        self._reset_output_chrome()
        self._show_readme_pane()
        self._show_markdown_file(self._repo / info.doc_dir / "README.md")

    def _show_readme_pane(self) -> None:
        self.query_one("#feat-right-readme", ScrollableContainer).display = True
        self.query_one("#feat-right-output", Vertical).display = False

    def _show_output_pane(self) -> None:
        self.query_one("#feat-right-readme", ScrollableContainer).display = False
        self.query_one("#feat-right-output", Vertical).display = True

    def _reset_output_chrome(self) -> None:
        out = self.query_one("#feat-right-output", Vertical)
        status = self.query_one("#feat-run-status", Static)
        out.remove_class("-run-error", "-run-ok")
        status.remove_class("-st-err", "-st-ok")
        status.update("")

    def _set_run_outcome(self, *, ok: bool, exit_code: int, kind: str) -> None:
        out = self.query_one("#feat-right-output", Vertical)
        status = self.query_one("#feat-run-status", Static)
        out.remove_class("-run-error", "-run-ok")
        status.remove_class("-st-err", "-st-ok")
        if ok:
            out.add_class("-run-ok")
            status.add_class("-st-ok")
            status.update(f"[b]OK[/b] — {kind} завершилось (exit {exit_code}).")
        else:
            out.add_class("-run-error")
            status.add_class("-st-err")
            status.update(
                f"[b]ОШИБКА[/b] — {kind} завершилось с кодом {exit_code}. См. вывод ниже.",
            )

    @on(Button.Pressed, "#feat-back")
    def on_back(self) -> None:
        self._show_picker()

    @on(Button.Pressed)
    def on_pick_feature(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        prefix = "feat-pick-"
        if not bid.startswith(prefix):
            return
        slug = bid[len(prefix) :]
        info = next((f for f in FEATURES if f.slug == slug), None)
        if info:
            self._show_detail(info)

    def _show_markdown_file(self, path: Path) -> None:
        md = self.query_one("#feat-md-body", Markdown)
        if not path.is_file():
            md.update(f"*(missing)* `{path}`")
            return
        text = path.read_text(encoding="utf-8", errors="replace")
        md.update(text)

    @on(Button.Pressed, "#feat-readme-en")
    def open_readme_en(self) -> None:
        if self._current:
            self._show_readme_pane()
            self._reset_output_chrome()
            self._show_markdown_file(self._repo / self._current.doc_dir / "README.md")

    @on(Button.Pressed, "#feat-readme-ru")
    def open_readme_ru(self) -> None:
        if self._current:
            self._show_readme_pane()
            self._reset_output_chrome()
            self._show_markdown_file(self._repo / self._current.doc_dir / "README-ru.md")

    @on(Button.Pressed, "#feat-demo-slow")
    def demo_slow(self) -> None:
        if not self._current or not self._current.demos:
            return
        self.run_feature_demo(self._current.demos[0].argv, self._current.demos[0].env, "Демо (paced)")

    @on(Button.Pressed, "#feat-demo-fast")
    def demo_fast(self) -> None:
        if not self._current or len(self._current.demos) < 2:
            return
        self.run_feature_demo(self._current.demos[1].argv, self._current.demos[1].env, "Демо (fast)")

    @work(group="features", exclusive=True, exit_on_error=False)
    async def run_feature_demo(
        self,
        argv: tuple[str, ...],
        env: dict[str, str],
        kind_label: str,
    ) -> None:
        self._show_output_pane()
        self._reset_output_chrome()
        log = self.query_one("#feat-log", RichLog)
        log.clear()
        merged = dict(env)
        argv_list = python_script_cmd(*argv)
        log.write(Text.from_markup(f"[dim]$ {' '.join(argv_list)} env={merged!r}[/]"))

        def on_line(line: str) -> None:
            log.write(line.rstrip("\n"))

        code = await stream_command(argv_list, self._repo, env=merged, on_line=on_line)
        ok = code == 0
        if ok:
            log.write(Text.from_markup(f"[green]— {kind_label}: exit {code}[/]"))
        else:
            log.write(
                Text.from_markup(
                    f"[bold white on red]— {kind_label}: НЕУДАЧА (exit {code}) —[/]",
                ),
            )
        self._set_run_outcome(ok=ok, exit_code=code, kind=kind_label)
        self.app.notify(
            f"{kind_label}: exit {code}",
            severity="information" if ok else "error",
            timeout=8 if not ok else 3,
        )

    @on(Button.Pressed, "#feat-install")
    def install_dev(self) -> None:
        self.run_pip_install_dev()

    @work(group="features", exclusive=True, exit_on_error=False)
    async def run_pip_install_dev(self) -> None:
        import sys

        self._show_output_pane()
        self._reset_output_chrome()
        log = self.query_one("#feat-log", RichLog)
        log.clear()
        label = "Установка dev-зависимостей"
        if which("uv"):
            argv = ["uv", "pip", "install", "-e", ".[dev]"]
            log.write(Text.from_markup("[dim]$ uv pip install -e .[dev][/]"))
        else:
            argv = [sys.executable, "-m", "pip", "install", "-e", ".[dev]"]
            log.write(Text.from_markup("[dim]$ python -m pip install -e .[dev][/]"))

        def on_line(line: str) -> None:
            log.write(line.rstrip("\n"))

        code = await stream_command(argv, self._repo, on_line=on_line)
        ok = code == 0
        if ok:
            log.write(Text.from_markup(f"[green]— {label}: exit {code}[/]"))
        else:
            log.write(
                Text.from_markup(
                    f"[bold white on red]— {label}: НЕУДАЧА (exit {code}) —[/]",
                ),
            )
        self._set_run_outcome(ok=ok, exit_code=code, kind=label)
        self.app.notify(
            f"{label}: exit {code}",
            severity="information" if ok else "error",
            timeout=8 if not ok else 3,
        )
