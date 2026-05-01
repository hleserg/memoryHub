"""Browse docs/architecture, development, ideas, research with Markdown preview."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.widgets import Button, Label, ListItem, ListView, Markdown, Static

DOC_ROOTS: tuple[tuple[str, str], ...] = (
    ("architecture", "docs/architecture"),
    ("development", "docs/development"),
    ("ideas", "docs/ideas"),
    ("research", "docs/research"),
)


class DocsTab(Vertical):
    DEFAULT_CSS = """
    DocsTab {
        height: 1fr;
    }
    DocsTab #docs-browser {
        width: 36%;
        min-width: 26;
        height: 1fr;
        border: solid $boost;
    }
    DocsTab #docs-view {
        width: 1fr;
        height: 1fr;
        border: solid $boost;
    }
    DocsTab #docs-subdirs {
        height: auto;
        min-height: 1;
    }
    DocsTab #docs-list {
        height: 1fr;
    }
    """

    def __init__(self, repo_root: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._repo = repo_root
        self._cwd: Path = repo_root / "docs" / "architecture"
        self._entries: list[Path] = []

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="docs-browser"):
                yield Static("Section")
                with Horizontal(id="docs-roots"):
                    for name, _rel in DOC_ROOTS:
                        yield Button(
                            name.capitalize(),
                            id=f"docs-root-{name}",
                            variant="primary",
                        )
                yield Static("", id="docs-path-label")
                yield Horizontal(id="docs-subdirs")
                yield ListView(id="docs-list")
            with Vertical(id="docs-view"), ScrollableContainer():
                yield Markdown("Pick a Markdown file.", id="docs-md")

    def on_mount(self) -> None:
        self._cwd = self._repo / "docs" / "architecture"
        self.rebuild_browser()

    def rebuild_browser(self) -> None:
        self._rebuild_browser()

    @work(group="docs", exclusive=True, exit_on_error=False)
    async def _rebuild_browser(self) -> None:
        rel = self._cwd.relative_to(self._repo)
        self.query_one("#docs-path-label", Static).update(str(rel))
        sub_bar = self.query_one("#docs-subdirs", Horizontal)
        await sub_bar.remove_children()
        await sub_bar.mount(Button("↑ Up", id="docs-up"))
        for p in sorted(self._cwd.iterdir()):
            if p.is_dir() and not p.name.startswith("."):
                await sub_bar.mount(
                    Button(p.name, classes="subdir-btn"),
                )

        entries: list[Path] = []
        for p in sorted(self._cwd.iterdir()):
            if p.name.startswith("."):
                continue
            entries.append(p)
        self._entries = entries

        lv = self.query_one("#docs-list", ListView)
        await lv.clear()
        if entries:
            items = [
                ListItem(Label(self._entry_label(p)), id=f"docs-entry-{i}")
                for i, p in enumerate(entries)
            ]
            await lv.extend(items)
            lv.index = 0

    def _entry_label(self, p: Path) -> str:
        return f"📁 {p.name}/" if p.is_dir() else p.name

    @on(Button.Pressed, "#docs-up")
    def go_up(self) -> None:
        docs = self._repo / "docs"
        try:
            self._cwd.relative_to(docs)
        except ValueError:
            return
        if self._cwd.resolve() == docs.resolve():
            return
        self._cwd = self._cwd.parent
        self.rebuild_browser()

    @on(Button.Pressed, ".subdir-btn")
    def subdir_pressed(self, event: Button.Pressed) -> None:
        label = event.button.label
        plain = str(label) if label is not None else ""
        target = self._cwd / plain
        if target.is_dir():
            self._cwd = target
            self.rebuild_browser()

    @on(Button.Pressed)
    def docs_root_buttons(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""
        prefix = "docs-root-"
        if not bid.startswith(prefix):
            return
        name = bid[len(prefix) :]
        for n, rel in DOC_ROOTS:
            if n == name:
                self._cwd = self._repo / rel
                self.rebuild_browser()
                return

    @on(ListView.Selected, "#docs-list")
    def open_selected(self, event: ListView.Selected) -> None:
        idx = event.index
        if idx < 0 or idx >= len(self._entries):
            return
        path = self._entries[idx]
        if path.is_dir():
            self._cwd = path
            self.rebuild_browser()
            return
        if path.suffix.lower() == ".md":
            text = path.read_text(encoding="utf-8", errors="replace")
            self.query_one("#docs-md", Markdown).update(text)
        else:
            raw = path.read_text(encoding="utf-8", errors="replace")
            preview = raw[:12000]
            self.query_one("#docs-md", Markdown).update(
                f"```\n{preview}\n```\n\n*(Non-Markdown file: truncated preview.)*",
            )
