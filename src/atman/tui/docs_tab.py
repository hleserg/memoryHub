"""Browse docs/architecture, development, ideas, research — single list navigator."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from textual import on, work
from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.widgets import Label, ListItem, ListView, Markdown, Static

RowKind = Literal["back", "dir", "file"]

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
    DocsTab #docs-path-label {
        height: auto;
        padding: 0 1;
        background: $boost;
        color: $text-muted;
    }
    DocsTab #docs-list {
        height: 1fr;
    }
    DocsTab #docs-view {
        width: 1fr;
        height: 1fr;
        border: solid $boost;
    }
    """

    def __init__(self, repo_root: Path, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._repo = repo_root
        self._view_roots = True
        self._cwd = repo_root / DOC_ROOTS[0][1]
        self._rows: list[tuple[RowKind, Path | None]] = []
        self._section_root_paths: frozenset[Path] = frozenset(
            (repo_root / rel).resolve() for _, rel in DOC_ROOTS
        )

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="docs-browser"):
                yield Static("", id="docs-path-label")
                yield ListView(id="docs-list")
            with Vertical(id="docs-view"), ScrollableContainer():
                yield Markdown("Выберите файл Markdown в списке слева.", id="docs-md")

    def on_mount(self) -> None:
        self._view_roots = True
        self.rebuild_browser()

    def rebuild_browser(self) -> None:
        self._rebuild_browser()

    @work(group="docs", exclusive=False, exit_on_error=False)
    async def _rebuild_browser(self) -> None:
        path_lbl = self.query_one("#docs-path-label", Static)
        if self._view_roots:
            path_lbl.update("Документация — выберите раздел")
            rows: list[tuple[RowKind, Path | None]] = []
            for _name, rel in DOC_ROOTS:
                rows.append(("dir", self._repo / rel))
        else:
            path_lbl.update(str(self._cwd.relative_to(self._repo)))
            rows = [("back", None)]
            dirs: list[Path] = []
            files: list[Path] = []
            for p in sorted(self._cwd.iterdir(), key=lambda x: x.name.lower()):
                if p.name.startswith("."):
                    continue
                if p.is_dir():
                    dirs.append(p)
                else:
                    files.append(p)
            for d in dirs:
                rows.append(("dir", d))
            for f in files:
                rows.append(("file", f))

        self._rows = rows
        lv = self.query_one("#docs-list", ListView)
        await lv.clear()
        if not rows:
            return
        items: list[ListItem] = []
        for i, (kind, path) in enumerate(rows):
            label_text = self._row_label(kind, path)
            cls = f"docs-row-{kind}"
            items.append(ListItem(Label(label_text), id=f"docs-row-{i}", classes=cls))
        await lv.extend(items)
        lv.index = 0

    def _row_label(self, kind: RowKind, path: Path | None) -> str:
        if kind == "back":
            return "📂 ⬅ Назад"
        if kind == "dir" and path is not None:
            if self._view_roots:
                pr = path.resolve()
                section = next(
                    (name for name, rel in DOC_ROOTS if (self._repo / rel).resolve() == pr),
                    path.name,
                )
                return f"📁 {section.replace('_', ' ').title()}"
            return f"📁 {path.name}/"
        if kind == "file" and path is not None:
            return f"📄 {path.name}"
        return "?"

    def _go_back(self) -> None:
        if self._view_roots:
            return
        if self._cwd.resolve() in self._section_root_paths:
            self._view_roots = True
        else:
            self._cwd = self._cwd.parent
        self.rebuild_browser()

    @on(ListView.Selected, "#docs-list")
    def open_selected(self, event: ListView.Selected) -> None:
        idx = event.index
        if idx < 0 or idx >= len(self._rows):
            return
        kind, path = self._rows[idx]
        if kind == "back":
            self._go_back()
            return
        if kind == "dir" and path is not None:
            self._view_roots = False
            self._cwd = path
            self.rebuild_browser()
            return
        if kind == "file" and path is not None:
            self._open_file(path)

    def _open_file(self, path: Path) -> None:
        if path.suffix.lower() == ".md":
            text = path.read_text(encoding="utf-8", errors="replace")
            self.query_one("#docs-md", Markdown).update(text)
            return
        raw = path.read_text(encoding="utf-8", errors="replace")
        preview = raw[:12000]
        self.query_one("#docs-md", Markdown).update(
            f"```\n{preview}\n```\n\n*(Не Markdown: превью обрезано.)*",
        )
