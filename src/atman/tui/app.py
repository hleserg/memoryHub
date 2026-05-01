"""Textual developer UI entrypoint."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, TabbedContent, TabPane

from atman.tui.docs_tab import DocsTab
from atman.tui.features_tab import FeaturesTab
from atman.tui.repo_root import find_repo_root
from atman.tui.tests_tab import TestsTab


class AtmanDevApp(App[None]):
    """Developer shell: tests, features, documentation."""

    TITLE = "Atman Dev UI"
    BINDINGS = [Binding("q", "quit", "Quit")]  # noqa: RUF012

    def __init__(self) -> None:
        super().__init__()
        self._root = find_repo_root()

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent():
            with TabPane("Tests", id="tab-tests"):
                yield TestsTab(self._root)
            with TabPane("Features", id="tab-features"):
                yield FeaturesTab(self._root)
            with TabPane("Docs", id="tab-docs"):
                yield DocsTab(self._root)
        yield Footer()


def main() -> None:
    """Console entrypoint for ``atman-dev``."""
    try:
        AtmanDevApp().run()
    except FileNotFoundError as e:
        raise SystemExit(f"{e}") from e
