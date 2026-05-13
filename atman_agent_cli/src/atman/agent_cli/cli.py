"""
atman/agent_cli/cli.py
Atman Agent — Textual TUI interface.

Layout:
  ┌──────────────────────────────────────────────────────────┐
  │ atman-agent           feat/bge-m3   ● agent   cohere/🏠 │
  ├─[Chat]─[Plans]─[Config]─[Changes]──────────────────────┤
  │                                      │ Current Plan     │
  │  ◆ Searching codebase...             │ ───────────────  │
  │    · embedding.py (line 1)           │ Add BGE-M3 (3/4) │
  │    · experience_service.py           │                  │
  │                                      │ Branch:          │
  │  ◆ Implementing...                   │ feat/bge-m3      │
  │    ## src/atman/adapters/...         │                  │
  │    ```python                         │ PR #531          │
  │    class BGEAdapter:                 │ CI: ⏳ pending   │
  │                                      │                  │
  ├──────────────────────────────────────┴──────────────────┤
  │ > add bge-m3 support to experience store_               │
  ├──────────────────────────────────────────────────────────┤
  │ ^P Plan  ^A Agent  ^B Babysit  ^R Review  ^K Config  ^Q │
  └──────────────────────────────────────────────────────────┘

Install: pip install textual
"""
from __future__ import annotations

import os
import time
import threading
import asyncio
from pathlib import Path
from typing import ClassVar

from textual import work, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import (
    DataTable, Footer, Header, Input, Label, Log,
    RichLog, Static, TabbedContent, TabPane,
)
from rich.text import Text
from rich.markdown import Markdown
from rich.panel import Panel

from .config import AgentConfig
from .memory import AgentMemory, Plan
from .git import (
    BranchGuard, PRManager, commit_all, current_branch,
    get_diff, is_branch_merged, pull_main, push_branch, run_git,
)
from .rag import RAGIndex
from .main_watcher import MainWatcher
from .webhook import WebhookServer
from .secrets import get_secrets
from .providers import (
    ProviderConfig, ProviderRouter,
    CODER_PROVIDERS, PLANNER_PROVIDERS, EMBEDDER_PROVIDERS, RERANKER_PROVIDERS,
)
from .executor import PlanExecutor, auto_plan
from .web import extract_urls, fetch_all_urls, format_pages_for_context, is_github_url, fetch_github_raw
from .search import search, has_search_intent, extract_search_query, add_search_domain, get_known_sites
from .context_manager import ContextManager, ContextLimits, count_tokens


# ── CSS ───────────────────────────────────────────────────────────────────────

APP_CSS = """
Screen {
    layers: base overlay;
}

#main-horizontal {
    height: 1fr;
}

#chat-pane {
    width: 1fr;
    height: 1fr;
    border-right: solid $panel;
}

#chat-log {
    height: 1fr;
    padding: 0 1;
}

#input-bar {
    height: auto;
    padding: 0 1;
    border-top: solid $panel;
}

#input-bar Input {
    width: 1fr;
    border: none;
    background: $surface;
}

#status-sidebar {
    width: 28;
    padding: 1;
    background: $panel;
}

.status-section {
    margin-bottom: 1;
}

.status-label {
    color: $text-muted;
    text-style: bold;
}

.status-value {
    color: $accent;
}

.plan-step-done {
    color: $success;
}

.plan-step-todo {
    color: $text-muted;
}

#plans-tab {
    padding: 1;
}

#settings-tab {
    padding: 1;
}

#changes-tab {
    padding: 1;
}

.mode-plan    { color: yellow; text-style: bold; }
.mode-agent   { color: green; text-style: bold; }
.mode-babysit { color: cyan; text-style: bold; }
.mode-review  { color: magenta; text-style: bold; }

.provider-local { color: $accent; }
.provider-cloud { color: yellow; }

.dim { color: $text-muted; }
.success { color: $success; }
.error { color: $error; }
.warning { color: yellow; }
"""


# ── Status sidebar ────────────────────────────────────────────────────────────

class StatusSidebar(Static):
    """Right panel: current plan, branch, PR status."""

    def __init__(self, agent: "AtmanApp") -> None:
        super().__init__()
        self._agent = agent

    def compose(self) -> ComposeResult:
        yield Static("", id="status-content")

    def refresh_status(self) -> None:
        agent = self._agent
        lines: list[str] = []

        # Mode
        mode = agent.mode
        mode_icons = {"plan": "📋", "agent": "⚡", "babysit": "👁", "review": "🔍"}
        lines.append(f"{mode_icons.get(mode, '?')} [bold]{mode.upper()}[/bold]")
        lines.append("")

        # Branch
        try:
            branch = current_branch(agent.cfg.repo_path)
            lines.append("[dim]Branch[/dim]")
            lines.append(f"[cyan]{branch}[/cyan]")
            lines.append("")
        except Exception:
            pass

        # Current plan
        plan = agent.current_plan
        if plan:
            done, total = plan.progress
            lines.append("[dim]Plan[/dim]")
            lines.append(f"{plan.task[:22]}")
            lines.append(f"[green]{done}/{total} done[/green]")
            next_step = plan.next_step()
            if next_step:
                lines.append(f"[dim]Next:[/dim] {next_step[:20]}")
            lines.append("")

        # Providers
        lines.append("[dim]Providers[/dim]")
        pcfg = agent.provider_cfg
        coder_icon = "🏠" if pcfg.coder == "llamacpp" else "☁"
        planner_icon = "🏠" if pcfg.planner == "llamacpp" else "☁"
        lines.append(f"coder  {coder_icon} {pcfg.coder}")
        lines.append(f"plan   {planner_icon} {pcfg.planner}")
        lines.append(f"embed  {'🏠' if pcfg.embedder == 'local' else '☁'} {pcfg.embedder}")
        lines.append("")

        # RAG stats
        stats = agent.rag.stats
        if stats["chunks"]:
            lines.append("[dim]Index[/dim]")
            lines.append(f"{stats['files']} files")
            lines.append(f"{stats['chunks']} chunks")

        # Token usage
        agent_app = agent
        if hasattr(agent_app, 'ctx') and hasattr(agent_app, '_messages'):
            status = agent_app.ctx.check(agent_app._messages, agent_app.current_plan)
            bar = agent_app.ctx.usage_bar(status.tokens_used)
            color = status.color
            compressions = agent_app.ctx.compression_count
            lines.append("[dim]Context[/dim]")
            lines.append(f"[{color}]{bar}[/{color}]")
            if compressions:
                lines.append(f"[dim]compressed ×{compressions}[/dim]")
            lines.append("")

        content = "\n".join(lines)
        try:
            self.query_one("#status-content", Static).update(content)
        except NoMatches:
            pass


# ── Chat pane ─────────────────────────────────────────────────────────────────

class ChatPane(Widget):
    def compose(self) -> ComposeResult:
        yield RichLog(id="chat-log", highlight=True, markup=True, wrap=True)
        with Container(id="input-bar"):
            yield Input(placeholder="Type a message or /command...", id="main-input")

    def write(self, text: str, markup: bool = True) -> None:
        log = self.query_one("#chat-log", RichLog)
        if markup:
            log.write(text)
        else:
            log.write(Text(text))

    def write_chunk(self, chunk: str) -> None:
        """Write a streaming chunk without newline."""
        log = self.query_one("#chat-log", RichLog)
        log.write(Text(chunk), shrink=False)

    def separator(self) -> None:
        self.write("[dim]" + "─" * 60 + "[/dim]")


# ── Plans tab ─────────────────────────────────────────────────────────────────

class PlansTab(Widget):
    def compose(self) -> ComposeResult:
        yield Static("[bold]Saved Plans[/bold]", classes="status-label")
        yield DataTable(id="plans-table")

    def on_mount(self) -> None:
        t = self.query_one(DataTable)
        t.add_columns("ID", "Task", "Status", "Progress", "Branch")
        t.cursor_type = "row"

    def refresh_plans(self, plans: list[Plan]) -> None:
        t = self.query_one(DataTable)
        t.clear()
        for p in plans:
            done, total = p.progress
            status_style = {
                "active": "green", "done": "dim", "abandoned": "red"
            }.get(p.status, "white")
            t.add_row(
                p.id,
                p.task[:40],
                f"[{status_style}]{p.status}[/{status_style}]",
                f"{done}/{total}",
                p.branch or "—",
            )


# ── Settings tab ──────────────────────────────────────────────────────────────

SETTINGS_CSS = """
SettingsTab {
    padding: 1 2;
    overflow-y: scroll;
}

.settings-section {
    margin-bottom: 2;
    border: solid $panel;
    padding: 1;
}

.settings-section-title {
    text-style: bold;
    color: $accent;
    margin-bottom: 1;
}

.settings-row {
    height: 3;
    margin-bottom: 1;
}

.settings-label {
    width: 28;
    height: 3;
    content-align: left middle;
    color: $text;
}

.settings-label-dim {
    width: 28;
    height: 3;
    content-align: left middle;
    color: $text-muted;
}

.settings-hint {
    color: $text-muted;
    margin-left: 28;
    margin-bottom: 1;
}

.settings-input {
    width: 1fr;
}

.settings-select {
    width: 1fr;
}

.settings-save-btn {
    margin-top: 1;
    width: 20;
}
"""


class SettingsTab(Widget):
    """
    Full settings page with interactive Textual widgets.
    All changes are applied live and persisted to ~/.atman/agent_memory/settings.json
    """

    DEFAULT_CSS = SETTINGS_CSS

    def __init__(self, app: "AtmanApp") -> None:
        super().__init__()
        self._app = app

    def compose(self) -> ComposeResult:
        from textual.widgets import Select, Switch, Button
        from textual.widgets import Input as TInput

        cfg = self._app.cfg
        pcfg = self._app.provider_cfg

        # ── LLM / Coder ────────────────────────────────────────────
        with Container(classes="settings-section"):
            yield Static("⚡ Coder (code generation)", classes="settings-section-title")

            with Horizontal(classes="settings-row"):
                yield Static("Provider", classes="settings-label")
                yield Select(
                    [(p, p) for p in CODER_PROVIDERS],
                    value=pcfg.coder,
                    id="sel-coder",
                    classes="settings-select",
                )

            with Horizontal(classes="settings-row"):
                yield Static("llama.cpp URL", classes="settings-label")
                yield Input(value=cfg.llm_url, id="inp-llm-url", classes="settings-input")
            yield Static("Server URL when coder=llamacpp", classes="settings-hint")

            with Horizontal(classes="settings-row"):
                yield Static("Model name", classes="settings-label")
                yield Input(value=cfg.llm_model, id="inp-llm-model", classes="settings-input")
            yield Static("Model name sent to llama.cpp /v1/chat/completions", classes="settings-hint")

            with Horizontal(classes="settings-row"):
                yield Static("Temperature", classes="settings-label")
                yield Input(value=str(cfg.llm_temperature), id="inp-llm-temp", classes="settings-input")

            with Horizontal(classes="settings-row"):
                yield Static("Max tokens (output)", classes="settings-label")
                yield Input(value=str(cfg.llm_max_tokens), id="inp-llm-maxtok", classes="settings-input")

            with Horizontal(classes="settings-row"):
                yield Static("Timeout (s)", classes="settings-label")
                yield Input(value=str(cfg.llm_timeout), id="inp-llm-timeout", classes="settings-input")

        # ── Planner ────────────────────────────────────────────────
        with Container(classes="settings-section"):
            yield Static("🧠 Planner (planning & analysis)", classes="settings-section-title")

            with Horizontal(classes="settings-row"):
                yield Static("Provider", classes="settings-label")
                yield Select(
                    [(p, p) for p in PLANNER_PROVIDERS],
                    value=pcfg.planner,
                    id="sel-planner",
                    classes="settings-select",
                )

            with Horizontal(classes="settings-row"):
                yield Static("Cohere model", classes="settings-label")
                yield Select(
                    [
                        ("command-r-plus", "command-r-plus"),
                        ("command-r",      "command-r"),
                        ("command",        "command"),
                    ],
                    value=cfg.cohere_model,
                    id="sel-cohere-model",
                    classes="settings-select",
                )

            with Horizontal(classes="settings-row"):
                yield Static("Cohere temperature", classes="settings-label")
                yield Input(value=str(cfg.cohere_temperature), id="inp-cohere-temp", classes="settings-input")

        # ── Embedder & Reranker ────────────────────────────────────
        with Container(classes="settings-section"):
            yield Static("🔍 Embedder & Reranker (RAG)", classes="settings-section-title")

            with Horizontal(classes="settings-row"):
                yield Static("Embedder", classes="settings-label")
                yield Select(
                    [(p, p) for p in EMBEDDER_PROVIDERS],
                    value=pcfg.embedder,
                    id="sel-embedder",
                    classes="settings-select",
                )

            with Horizontal(classes="settings-row"):
                yield Static("Reranker", classes="settings-label")
                yield Select(
                    [(p, p) for p in RERANKER_PROVIDERS],
                    value=pcfg.reranker,
                    id="sel-reranker",
                    classes="settings-select",
                )

            with Horizontal(classes="settings-row"):
                yield Static("RAG candidates (top-K)", classes="settings-label")
                yield Input(value=str(cfg.rag_top_k), id="inp-rag-topk", classes="settings-input")
            yield Static("BGE-M3 retrieves this many candidates before reranking", classes="settings-hint")

            with Horizontal(classes="settings-row"):
                yield Static("Final results (top-N)", classes="settings-label")
                yield Input(value=str(cfg.rag_top_n), id="inp-rag-topn", classes="settings-input")
            yield Static("Reranker keeps this many for LLM context", classes="settings-hint")

        # ── Babysit ────────────────────────────────────────────────
        with Container(classes="settings-section"):
            yield Static("👁 Babysit (PR lifecycle)", classes="settings-section-title")

            with Horizontal(classes="settings-row"):
                yield Static("Require PR approval", classes="settings-label")
                yield Switch(value=cfg.babysit_require_approval, id="sw-require-approval")
            yield Static(
                "OFF = merge as soon as CI is green (solo PRs). "
                "ON = wait for reviewer approval too.",
                classes="settings-hint",
            )

            with Horizontal(classes="settings-row"):
                yield Static("Poll interval (s)", classes="settings-label")
                yield Input(value=str(cfg.babysit_poll_interval), id="inp-babysit-poll", classes="settings-input")

            with Horizontal(classes="settings-row"):
                yield Static("Max fix attempts", classes="settings-label")
                yield Input(value=str(cfg.babysit_max_fix_attempts), id="inp-babysit-max", classes="settings-input")
            yield Static("How many times babysit tries to fix CI/conflicts before giving up", classes="settings-hint")

        # ── Context window ────────────────────────────────────────
        with Container(classes="settings-section"):
            yield Static("📐 Context window", classes="settings-section-title")

            with Horizontal(classes="settings-row"):
                yield Static("Token limit", classes="settings-label")
                yield Input(value=str(cfg.context_limit), id="inp-ctx-limit", classes="settings-input")
            yield Static(
                "Total context window of your model. "
                "DeepSeek-R1-14B Q4_K_M: try 8192–16384 depending on VRAM.",
                classes="settings-hint",
            )

            with Horizontal(classes="settings-row"):
                yield Static("Warn threshold", classes="settings-label")
                yield Select(
                    [("70%", "0.70"), ("75%", "0.75"), ("80%", "0.80"), ("85%", "0.85")],
                    value=str(cfg.context_warn_ratio),
                    id="sel-ctx-warn",
                    classes="settings-select",
                )

            with Horizontal(classes="settings-row"):
                yield Static("Compress threshold", classes="settings-label")
                yield Select(
                    [("85%", "0.85"), ("90%", "0.90"), ("92%", "0.92"), ("95%", "0.95")],
                    value=str(cfg.context_critical_ratio),
                    id="sel-ctx-compress",
                    classes="settings-select",
                )

        # ── GitHub ────────────────────────────────────────────────
        with Container(classes="settings-section"):
            yield Static("🐙 GitHub", classes="settings-section-title")

            with Horizontal(classes="settings-row"):
                yield Static("Repository", classes="settings-label")
                yield Input(value=cfg.github_repo, id="inp-github-repo", classes="settings-input")

            with Horizontal(classes="settings-row"):
                yield Static("Main branch", classes="settings-label")
                yield Input(value=cfg.main_branch, id="inp-main-branch", classes="settings-input")

        # ── Secrets ────────────────────────────────────────────────
        with Container(classes="settings-section"):
            yield Static("🔑 API Keys  (masked, saved to ~/.atman/.secrets)", classes="settings-section-title")
            yield Static("", id="secrets-status")
            yield Static(
                "[dim]Enter key and press Enter to save. Values are write-only here.[/dim]",
                classes="settings-hint",
            )
            with Horizontal(classes="settings-row"):
                yield Static("Anthropic API key", classes="settings-label-dim")
                yield Input(placeholder="sk-ant-... (leave blank to keep existing)", password=True,
                           id="inp-anthropic-key", classes="settings-input")
            with Horizontal(classes="settings-row"):
                yield Static("Cohere API key", classes="settings-label-dim")
                yield Input(placeholder="leave blank to keep existing", password=True,
                           id="inp-cohere-key", classes="settings-input")
            with Horizontal(classes="settings-row"):
                yield Static("GitHub token", classes="settings-label-dim")
                yield Input(placeholder="ghp_... (leave blank to keep existing)", password=True,
                           id="inp-github-token", classes="settings-input")

        from textual.widgets import Button
        yield Button("💾  Save all settings", id="btn-save-settings", variant="primary")
        yield Static("", id="settings-save-status")

    def on_mount(self) -> None:
        self._refresh_secrets_status()

    def _refresh_secrets_status(self) -> None:
        secrets = self._app.secrets
        lines = []
        for key, status in secrets.status().items():
            color = "green" if "[not set]" not in status else "dim"
            lines.append(f"  [{color}]{key:<24}[/{color}] {status}")
        try:
            self.query_one("#secrets-status", Static).update("\n".join(lines))
        except NoMatches:
            pass

    def on_button_pressed(self, event) -> None:
        if event.button.id == "btn-save-settings":
            self._save_all()

    def on_select_changed(self, event) -> None:
        """Live-apply provider switches immediately."""
        from textual.widgets import Select
        sel_id = event.select.id
        val = event.value

        provider_map = {
            "sel-coder":    "coder",
            "sel-planner":  "planner",
            "sel-embedder": "embedder",
            "sel-reranker": "reranker",
        }
        if sel_id in provider_map:
            role = provider_map[sel_id]
            ok, msg = self._app.router.switch(role, val)
            if ok:
                self._app.provider_cfg.save(self._app._provider_cfg_file)
                self._app._update_header()
                self._app._refresh_sidebar()
                self._set_status(f"✓ {msg}", "green")
            else:
                self._set_status(f"✗ {msg}", "red")

    def on_switch_changed(self, event) -> None:
        if event.switch.id == "sw-require-approval":
            self._app.cfg.babysit_require_approval = event.value
            state = "ON (wait for approval)" if event.value else "OFF (merge on CI green)"
            self._set_status(f"Babysit approval: {state}", "cyan")

    def _save_all(self) -> None:
        """Collect all input values and save to config + disk."""
        cfg = self._app.cfg
        errors: list[str] = []

        def get_input(widget_id: str) -> str:
            try:
                return self.query_one(f"#{widget_id}", Input).value.strip()
            except NoMatches:
                return ""

        def get_select(widget_id: str) -> str:
            try:
                from textual.widgets import Select
                return str(self.query_one(f"#{widget_id}", Select).value)
            except NoMatches:
                return ""

        def set_float(attr: str, val: str) -> None:
            try:
                setattr(cfg, attr, float(val))
            except ValueError:
                errors.append(f"{attr}: invalid float '{val}'")

        def set_int(attr: str, val: str) -> None:
            try:
                setattr(cfg, attr, int(val))
            except ValueError:
                errors.append(f"{attr}: invalid int '{val}'")

        # LLM
        cfg.llm_url   = get_input("inp-llm-url")   or cfg.llm_url
        cfg.llm_model = get_input("inp-llm-model")  or cfg.llm_model
        set_float("llm_temperature", get_input("inp-llm-temp") or str(cfg.llm_temperature))
        set_int("llm_max_tokens",    get_input("inp-llm-maxtok") or str(cfg.llm_max_tokens))
        set_int("llm_timeout",       get_input("inp-llm-timeout") or str(cfg.llm_timeout))

        # Update router llm_url live
        self._app.router.llm_url = cfg.llm_url

        # Cohere
        cfg.cohere_model = get_select("sel-cohere-model") or cfg.cohere_model
        set_float("cohere_temperature", get_input("inp-cohere-temp") or str(cfg.cohere_temperature))

        # RAG
        set_int("rag_top_k", get_input("inp-rag-topk") or str(cfg.rag_top_k))
        set_int("rag_top_n", get_input("inp-rag-topn") or str(cfg.rag_top_n))

        # Babysit
        set_int("babysit_poll_interval",    get_input("inp-babysit-poll") or str(cfg.babysit_poll_interval))
        set_int("babysit_max_fix_attempts", get_input("inp-babysit-max")  or str(cfg.babysit_max_fix_attempts))
        # babysit_require_approval already set live via Switch

        # Context window
        ctx_limit_str = get_input("inp-ctx-limit")
        set_int("context_limit", ctx_limit_str or str(cfg.context_limit))
        if ctx_limit_str:
            self._app.ctx.limits.total = cfg.context_limit

        warn_str = get_select("sel-ctx-warn")
        compress_str = get_select("sel-ctx-compress")
        if warn_str:
            set_float("context_warn_ratio", warn_str)
            self._app.ctx.limits.warning_ratio = cfg.context_warn_ratio
        if compress_str:
            set_float("context_critical_ratio", compress_str)
            self._app.ctx.limits.critical_ratio = cfg.context_critical_ratio

        # GitHub
        cfg.github_repo  = get_input("inp-github-repo")   or cfg.github_repo
        cfg.main_branch  = get_input("inp-main-branch")   or cfg.main_branch

        # API Keys — only save if non-empty
        anthropic_key = get_input("inp-anthropic-key")
        cohere_key    = get_input("inp-cohere-key")
        github_token  = get_input("inp-github-token")
        if anthropic_key:
            self._app.secrets.set_persistent("ANTHROPIC_API_KEY", anthropic_key)
        if cohere_key:
            self._app.secrets.set_persistent("COHERE_API_KEY", cohere_key)
        if github_token:
            self._app.secrets.set_persistent("GITHUB_TOKEN", github_token)

        # Clear password fields after save
        for fid in ("inp-anthropic-key", "inp-cohere-key", "inp-github-token"):
            try:
                self.query_one(f"#{fid}", Input).value = ""
            except NoMatches:
                pass

        if errors:
            self._set_status("⚠ " + " | ".join(errors), "yellow")
            return

        # Persist everything
        cfg.save_settings()
        self._app.provider_cfg.save(self._app._provider_cfg_file)
        self._refresh_secrets_status()
        self._app._update_header()
        self._app._refresh_sidebar()
        self._set_status("✓ All settings saved", "green")

    def _set_status(self, msg: str, color: str = "white") -> None:
        try:
            self.query_one("#settings-save-status", Static).update(
                f"[{color}]{msg}[/{color}]"
            )
        except NoMatches:
            pass


# ── Setup / CI wizard tab ─────────────────────────────────────────────────────

SETUP_CSS = """
SetupTab {
    padding: 1 2;
    overflow-y: scroll;
}

.setup-step {
    border: solid $panel;
    padding: 1;
    margin-bottom: 1;
}

.setup-step-title {
    text-style: bold;
}

.step-ok      { color: $success; }
.step-pending { color: $text-muted; }
.step-error   { color: $error; }
.step-running { color: yellow; }

.setup-log {
    height: 12;
    border: solid $panel;
    margin-top: 1;
}

.setup-btn {
    margin-top: 1;
    margin-right: 1;
}
"""


class SetupTab(Widget):
    """
    Interactive CI setup wizard.

    Steps:
      1. Prerequisites check (cloudflared, runner dir)
      2. Start Cloudflare quick tunnel → get public URL
      3. Register GitHub webhook
      4. Install + configure + start self-hosted runner
      5. Write CI workflow file
      6. Test: ping webhook, verify runner online
    """

    DEFAULT_CSS = SETUP_CSS

    STEP_ICONS = {"ok": "✅", "error": "❌", "running": "⚡", "pending": "⬜", "warn": "⚠️"}

    def __init__(self, app: "AtmanApp") -> None:
        super().__init__()
        self._app = app
        self._orchestrator = None
        self._step_status: dict[str, str] = {
            "prereqs": "pending",
            "tunnel": "pending",
            "webhook": "pending",
            "runner": "pending",
            "workflow": "pending",
            "test": "pending",
        }

    def compose(self) -> ComposeResult:
        from textual.widgets import Button, RichLog as TRichLog
        from tunnel import TunnelState
        state = TunnelState.load()

        yield Static(
            "[bold]CI Setup Wizard[/bold]\n"
            "[dim]Connects your local machine to GitHub as a self-hosted runner + webhook receiver.\n"
            "Uses Cloudflare Tunnel — no public IP needed, free.[/dim]\n",
        )

        # ── How it works ────────────────────────────────────────────────
        yield Static(
            "──────────────────────────────────────────────────────────\n"
            "[bold cyan]How it works:[/bold cyan]\n\n"
            "  Your machine  ←→  Cloudflare Tunnel  ←→  GitHub\n\n"
            "  • Cloudflare gives you a free public URL (*.trycloudflare.com)\n"
            "  • GitHub sends PR events to that URL → your webhook server\n"
            "  • GitHub Actions uses your machine as a runner to execute AI review\n"
            "  • No ports to open, no router config, works behind NAT/VPN\n"
            "──────────────────────────────────────────────────────────\n",
        )

        # ── Step indicators ──────────────────────────────────────────────
        yield Static("", id="setup-steps-overview")

        # ── Step 1: Prerequisites ────────────────────────────────────────
        with Container(classes="setup-step", id="step-prereqs"):
            yield Static("⬜ Step 1 — Prerequisites", id="step-prereqs-title", classes="setup-step-title")
            yield Static(
                "[dim]Checks: Python packages, cloudflared binary, GitHub token set.[/dim]"
            )
            yield Button("Check prerequisites", id="btn-check-prereqs", classes="setup-btn")
            yield Static("", id="prereqs-result")

        # ── Step 2: Tunnel ───────────────────────────────────────────────
        with Container(classes="setup-step", id="step-tunnel"):
            yield Static("⬜ Step 2 — Start Cloudflare Tunnel", id="step-tunnel-title", classes="setup-step-title")
            yield Static(
                "[dim]Runs: [cyan]cloudflared tunnel --url http://localhost:9876[/cyan]\n"
                "Gives you a free temporary public URL. No account needed.\n"
                "⚠ URL changes on restart → webhook is re-registered automatically.[/dim]"
            )
            yield Button("Start tunnel", id="btn-start-tunnel", classes="setup-btn", variant="primary")
            yield Static("", id="tunnel-result")

        # ── Step 3: Webhook ──────────────────────────────────────────────
        with Container(classes="setup-step", id="step-webhook"):
            yield Static("⬜ Step 3 — Register GitHub Webhook", id="step-webhook-title", classes="setup-step-title")
            yield Static(
                "[dim]Calls GitHub API to create a webhook pointing to your tunnel URL.\n"
                "Events: pull_request, check_run\n"
                "[bold]You don't need to do anything manually.[/bold][/dim]"
            )
            yield Button("Register webhook", id="btn-register-webhook", classes="setup-btn")
            yield Static("", id="webhook-result")

        # ── Step 4: Runner ───────────────────────────────────────────────
        with Container(classes="setup-step", id="step-runner"):
            yield Static("⬜ Step 4 — GitHub Self-Hosted Runner", id="step-runner-title", classes="setup-step-title")
            yield Static(
                "[dim]Downloads GitHub Actions runner binary (~100MB).\n"
                "Registers it with your repo. Starts it as a background process.\n"
                "[bold]You don't need to do anything manually.[/bold]\n\n"
                "Runner will appear in:\n"
                "  GitHub → Repo → Settings → Actions → Runners[/dim]"
            )
            yield Button("Install & start runner", id="btn-setup-runner", classes="setup-btn")
            yield Static("", id="runner-result")

        # ── Step 5: CI workflow ──────────────────────────────────────────
        with Container(classes="setup-step", id="step-workflow"):
            yield Static("⬜ Step 5 — Write CI Workflow File", id="step-workflow-title", classes="setup-step-title")
            yield Static(
                "[dim]Creates [cyan].github/workflows/ai-review.yml[/cyan]\n"
                "This tells GitHub Actions to run the AI review on every PR.\n\n"
                "[bold]⚠ You need to:[/bold]\n"
                "  1. Commit and push this file\n"
                "  2. Add secrets to GitHub if using cloud providers:\n"
                "     Repo → Settings → Secrets → Actions:\n"
                "     [cyan]COHERE_API_KEY[/cyan] and/or [cyan]ANTHROPIC_API_KEY[/cyan][/dim]"
            )
            yield Button("Write workflow file", id="btn-write-workflow", classes="setup-btn")
            yield Static("", id="workflow-result")

        # ── Step 6: Test ─────────────────────────────────────────────────
        with Container(classes="setup-step", id="step-test"):
            yield Static("⬜ Step 6 — Verify Everything", id="step-test-title", classes="setup-step-title")
            yield Static(
                "[dim]Checks: tunnel reachable, webhook active on GitHub,\n"
                "runner showing as online in GitHub API.[/dim]"
            )
            yield Button("Run verification", id="btn-verify", classes="setup-btn")
            yield Static("", id="test-result")

        # ── Setup All ────────────────────────────────────────────────────
        yield Static("\n──────────────────────────────────────────────────────────")
        with Horizontal():
            yield Button("🚀  Setup Everything", id="btn-setup-all", variant="success", classes="setup-btn")
            yield Button("⏹  Stop Tunnel & Runner", id="btn-stop-all", variant="error", classes="setup-btn")

        # ── Live log ─────────────────────────────────────────────────────
        yield Static("\n[bold]Live log:[/bold]")
        yield RichLog(id="setup-log", highlight=True, markup=True, classes="setup-log")

        # ── Current state ────────────────────────────────────────────────
        if state.tunnel_url:
            yield Static(
                f"\n[dim]Last session:[/dim]\n"
                f"  Tunnel: [cyan]{state.tunnel_url}[/cyan]\n"
                f"  Webhook: #{state.webhook_id or 'none'}\n"
                f"  Runner: {'registered' if state.runner_registered else 'not registered'}\n"
                f"  Started: {state.last_started[:16] if state.last_started else 'never'}[/dim]"
            )

    def on_mount(self) -> None:
        self._refresh_overview()

    def _log(self, msg: str, level: str = "info") -> None:
        colors = {"ok": "green", "error": "red", "warn": "yellow", "info": "dim"}
        color = colors.get(level, "white")
        try:
            self.query_one("#setup-log", RichLog).write(
                f"[{color}]{datetime.now().strftime('%H:%M:%S')} {msg}[/{color}]"
            )
        except NoMatches:
            pass

    def _set_step(self, step: str, status: str, detail: str = "") -> None:
        self._step_status[step] = status
        icon = self.STEP_ICONS.get(status, "?")
        labels = {
            "prereqs": "Step 1 — Prerequisites",
            "tunnel":  "Step 2 — Cloudflare Tunnel",
            "webhook": "Step 3 — GitHub Webhook",
            "runner":  "Step 4 — Self-hosted Runner",
            "workflow":"Step 5 — CI Workflow File",
            "test":    "Step 6 — Verification",
        }
        label = labels.get(step, step)
        color = {"ok": "green", "error": "red", "running": "yellow", "warn": "yellow"}.get(status, "dim")
        try:
            self.query_one(f"#step-{step}-title", Static).update(
                f"[{color}]{icon} {label}[/{color}]"
            )
        except NoMatches:
            pass
        if detail:
            try:
                self.query_one(f"#{step}-result", Static).update(
                    f"  [{color}]{detail}[/{color}]"
                )
            except NoMatches:
                pass
        self._refresh_overview()

    def _refresh_overview(self) -> None:
        parts = []
        labels = ["prereqs", "tunnel", "webhook", "runner", "workflow", "test"]
        short = ["Prereqs", "Tunnel", "Webhook", "Runner", "Workflow", "Verify"]
        for k, s in zip(labels, short):
            icon = self.STEP_ICONS.get(self._step_status.get(k, "pending"), "⬜")
            parts.append(f"{icon} {s}")
        try:
            self.query_one("#setup-steps-overview", Static).update(
                "  " + "   ".join(parts) + "\n"
            )
        except NoMatches:
            pass

    def _get_orchestrator(self):
        if not self._orchestrator:
            from .tunnel import SetupOrchestrator
            self._orchestrator = SetupOrchestrator(
                github_token=self._app.secrets.github_token,
                repo=self._app.cfg.github_repo,
                repo_path=self._app.cfg.repo_path,
                webhook_port=self._app.cfg.babysit_poll_interval,  # reuse port from config
                log=lambda msg, level="info": self.call_from_thread(self._log, msg, level),
            )
        return self._orchestrator

    def on_button_pressed(self, event) -> None:
        btn_id = event.button.id
        if btn_id == "btn-check-prereqs":
            self._run_check_prereqs()
        elif btn_id == "btn-start-tunnel":
            self._run_start_tunnel()
        elif btn_id == "btn-register-webhook":
            self._run_register_webhook()
        elif btn_id == "btn-setup-runner":
            self._run_setup_runner()
        elif btn_id == "btn-write-workflow":
            self._run_write_workflow()
        elif btn_id == "btn-verify":
            self._run_verify()
        elif btn_id == "btn-setup-all":
            self._run_setup_all()
        elif btn_id == "btn-stop-all":
            self._run_stop_all()

    @work(thread=True)
    def _run_check_prereqs(self) -> None:
        self.call_from_thread(self._set_step, "prereqs", "running", "Checking...")
        errors = []

        # cloudflared
        from .tunnel import is_cloudflared_installed
        if is_cloudflared_installed():
            self.call_from_thread(self._log, "cloudflared: found", "ok")
        else:
            self.call_from_thread(self._log, "cloudflared: not found (will install automatically)", "warn")

        # GitHub token
        if self._app.secrets.github_token:
            self.call_from_thread(self._log, "GitHub token: set", "ok")
        else:
            self.call_from_thread(self._log, "GitHub token: NOT SET — go to Settings tab", "error")
            errors.append("GitHub token missing")

        # Python packages
        for pkg in ("requests", "trafilatura", "duckduckgo_search"):
            try:
                __import__(pkg)
                self.call_from_thread(self._log, f"{pkg}: ok", "ok")
            except ImportError:
                self.call_from_thread(self._log, f"{pkg}: missing (pip install {pkg})", "warn")

        if errors:
            self.call_from_thread(self._set_step, "prereqs", "error", " | ".join(errors))
        else:
            self.call_from_thread(self._set_step, "prereqs", "ok", "All prerequisites met")

    @work(thread=True)
    def _run_start_tunnel(self) -> None:
        self.call_from_thread(self._set_step, "tunnel", "running", "Starting...")
        orch = self._get_orchestrator()
        ok = orch.start_tunnel()
        if ok:
            url = orch.tunnel_url
            self.call_from_thread(
                self._set_step, "tunnel", "ok", f"Running → {url}"
            )
        else:
            self.call_from_thread(self._set_step, "tunnel", "error", "Tunnel failed to start")

    @work(thread=True)
    def _run_register_webhook(self) -> None:
        self.call_from_thread(self._set_step, "webhook", "running", "Registering...")
        orch = self._get_orchestrator()
        ok = orch.register_webhook()
        if ok:
            self.call_from_thread(
                self._set_step, "webhook", "ok",
                f"Webhook #{orch.state.webhook_id} registered on GitHub"
            )
        else:
            self.call_from_thread(self._set_step, "webhook", "error", "Failed — check GitHub token")

    @work(thread=True)
    def _run_setup_runner(self) -> None:
        self.call_from_thread(self._set_step, "runner", "running", "Installing...")
        orch = self._get_orchestrator()
        ok = orch.setup_runner()
        if ok:
            self.call_from_thread(
                self._set_step, "runner", "ok", "Runner running — check GitHub → Settings → Runners"
            )
        else:
            self.call_from_thread(self._set_step, "runner", "error", "Runner setup failed")

    @work(thread=True)
    def _run_write_workflow(self) -> None:
        self.call_from_thread(self._set_step, "workflow", "running", "Writing...")
        orch = self._get_orchestrator()
        ok = orch.write_workflow()
        if ok:
            self.call_from_thread(
                self._set_step, "workflow", "ok",
                ".github/workflows/ai-review.yml written — commit and push!"
            )
            self.call_from_thread(
                self._log,
                "⚠ Don't forget:\n"
                "  1. git add .github/workflows/ai-review.yml && git commit -m 'ci: add AI review'\n"
                "  2. Add secrets on GitHub (COHERE_API_KEY / ANTHROPIC_API_KEY)",
                "warn"
            )

    @work(thread=True)
    def _run_verify(self) -> None:
        self.call_from_thread(self._set_step, "test", "running", "Verifying...")
        from .tunnel import TunnelState, list_registered_runners
        state = TunnelState.load()
        issues = []

        # Tunnel reachable?
        if state.tunnel_url:
            try:
                r = requests.get(state.tunnel_url, timeout=10)
                self.call_from_thread(self._log, f"Tunnel HTTP {r.status_code} — reachable", "ok")
            except Exception as e:
                self.call_from_thread(self._log, f"Tunnel not reachable: {e}", "error")
                issues.append("tunnel unreachable")
        else:
            issues.append("no tunnel URL")

        # Runner online?
        runners = list_registered_runners(
            self._app.secrets.github_token, self._app.cfg.github_repo
        )
        online = [r for r in runners if r.get("status") == "online"]
        if online:
            names = ", ".join(r["name"] for r in online)
            self.call_from_thread(self._log, f"Runner(s) online: {names}", "ok")
        else:
            self.call_from_thread(self._log, "No online runners found on GitHub", "warn")
            issues.append("no online runner")

        if issues:
            self.call_from_thread(self._set_step, "test", "warn", " | ".join(issues))
        else:
            self.call_from_thread(self._set_step, "test", "ok", "All checks passed 🎉")

    @work(thread=True)
    def _run_setup_all(self) -> None:
        self.call_from_thread(self._log, "=== Starting full setup ===", "info")
        self._run_check_prereqs()
        time.sleep(1)
        self._run_start_tunnel()
        time.sleep(2)
        self._run_register_webhook()
        time.sleep(1)
        self._run_setup_runner()
        time.sleep(2)
        self._run_write_workflow()
        time.sleep(1)
        self._run_verify()
        self.call_from_thread(self._log, "=== Setup complete ===", "ok")

    def _run_stop_all(self) -> None:
        if self._orchestrator:
            self._orchestrator.stop()
        self._set_step("tunnel", "pending", "Stopped")
        self._set_step("runner", "pending", "Stopped")
        self._log("Tunnel and runner stopped", "warn")


# ── Changes tab ───────────────────────────────────────────────────────────────

class ChangesTab(Widget):
    def compose(self) -> ComposeResult:
        yield Static("[bold]Recent changes in main[/bold]", classes="status-label")
        yield DataTable(id="changes-table")

    def on_mount(self) -> None:
        t = self.query_one(DataTable)
        t.add_columns("Date", "Source", "Stat", "Files")
        t.cursor_type = "row"

    def refresh_changes(self, records: list[dict]) -> None:
        t = self.query_one(DataTable)
        t.clear()
        for r in records:
            pr = f"PR #{r['pr_number']}" if r.get("pr_number") else r.get("triggered_by", "?")
            files = ", ".join(r.get("files_changed", [])[:3])
            if len(r.get("files_changed", [])) > 3:
                files += " ..."
            t.add_row(
                r.get("synced_at", "")[:16],
                pr,
                r.get("diff_stat", ""),
                files,
            )


# ── Main App ──────────────────────────────────────────────────────────────────

class AtmanApp(App):
    """Atman Agent — Textual TUI."""

    CSS = APP_CSS
    TITLE = "atman-agent"

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("ctrl+p", "set_mode('plan')",    "Plan",    show=True),
        Binding("ctrl+a", "set_mode('agent')",   "Agent",   show=True),
        Binding("ctrl+b", "set_mode('babysit')", "Babysit", show=True),
        Binding("ctrl+r", "set_mode('review')",  "Review",  show=True),
        Binding("ctrl+k", "show_config",         "Config",  show=True),
        Binding("ctrl+u", "show_setup",          "Setup",   show=True),
        Binding("ctrl+s", "manual_sync",         "Sync",    show=True),
        Binding("ctrl+i", "rebuild_index",       "Index",   show=False),
        Binding("ctrl+q", "quit",                "Quit",    show=True),
    ]

    mode: reactive[str] = reactive("agent")

    def __init__(self, cfg: AgentConfig) -> None:
        super().__init__()
        self.cfg = cfg

        # Secrets + providers
        self.secrets = get_secrets()
        provider_cfg_file = cfg.memory_path / "providers.json"
        self.provider_cfg = ProviderConfig.load(provider_cfg_file)
        self._provider_cfg_file = provider_cfg_file
        self.router = ProviderRouter(self.provider_cfg, self.secrets, cfg.llm_url)

        # Backend
        self.memory = AgentMemory(cfg)
        self.branch_guard = BranchGuard(cfg)
        self.pr_manager = PRManager(cfg)
        self.rag = RAGIndex(cfg)

        # Background watcher — daemon thread, no LLM, richer event model
        self.watcher = MainWatcher(
            cfg,
            on_change=lambda ev: self.memory.save_changeset_from_event(ev),
        )

        # State
        self.current_plan: Plan | None = None
        self._busy = False
        self._stream_buffer: list[str] = []

        # Conversation history for context tracking
        self._messages: list[dict] = []

        # Context window manager
        ctx_limits = ContextLimits(
            total=int(os.getenv("ATMAN_CONTEXT_LIMIT", "8192")),
        )
        self.ctx = ContextManager(ctx_limits, self.router, self.memory)
        self._current_executor: PlanExecutor | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(id="tabs"):
            with TabPane("Chat", id="tab-chat"):
                with Horizontal(id="main-horizontal"):
                    with Container(id="chat-pane"):
                        yield ChatPane(id="chat-widget")
                    yield StatusSidebar(self, id="status-sidebar")
            with TabPane("Plans", id="tab-plans"):
                yield PlansTab(id="plans-tab")
            with TabPane("Settings", id="tab-settings"):
                yield SettingsTab(self, id="settings-tab")
            with TabPane("Setup CI", id="tab-setup"):
                yield SetupTab(self, id="setup-tab")
            with TabPane("Changes", id="tab-changes"):
                yield ChangesTab(id="changes-tab")
        yield Footer()

    def on_mount(self) -> None:
        # Start background watcher (daemon thread, no LLM)
        self.watcher.start_background(interval=60)

        # Optional webhook server with HMAC signature verification
        webhook_port = int(os.getenv("ATMAN_WEBHOOK_PORT", "0"))
        if webhook_port:
            WebhookServer(
                watcher=self.watcher,
                port=webhook_port,
                secret=os.getenv("ATMAN_WEBHOOK_SECRET", ""),
                main_branch=self.cfg.main_branch,
            ).start()

        # Initial render
        self._refresh_all()
        self._update_header()

        # Welcome message
        self._chat_write("[bold cyan]Atman Agent[/bold cyan] — type [green]/help[/green] or start chatting")
        self._chat_write(f"[dim]Mode: {self.mode} · Index: {self.rag.stats['chunks']} chunks[/dim]")

        # Warn if no index
        if not self.rag.stats["chunks"]:
            self._chat_write("[yellow]⚠ No RAG index. Press Ctrl+I or type /index to build.[/yellow]")

        # Resume hint
        plan = self.memory.get_active_plan()
        if plan:
            done, total = plan.progress
            self._chat_write(
                f"[dim]Active plan: \"{plan.task[:50]}\" [{done}/{total}] — "
                f"type [bold]/resume[/bold][/dim]"
            )

    # ── Header ────────────────────────────────────────────────────────────────

    def _update_header(self) -> None:
        try:
            branch = current_branch(self.cfg.repo_path)
        except Exception:
            branch = "?"
        mode_icons = {"plan": "📋", "agent": "⚡", "babysit": "👁", "review": "🔍"}
        icon = mode_icons.get(self.mode, "?")
        self.title = f"atman-agent  {branch}  {icon} {self.mode}"
        self.sub_title = (
            f"coder:{self.provider_cfg.coder}  "
            f"plan:{self.provider_cfg.planner}  "
            f"embed:{self.provider_cfg.embedder}"
        )

    # ── Chat helpers ──────────────────────────────────────────────────────────

    def _chat_write(self, text: str) -> None:
        try:
            self.query_one("#chat-widget", ChatPane).write(text)
        except NoMatches:
            pass

    def _chat_separator(self) -> None:
        try:
            self.query_one("#chat-widget", ChatPane).separator()
        except NoMatches:
            pass

    def _chat_append(self, chunk: str) -> None:
        """Append streaming chunk (called from worker thread)."""
        try:
            self.query_one("#chat-widget", ChatPane).write(chunk, markup=False)
        except NoMatches:
            pass

    # ── Input handler ─────────────────────────────────────────────────────────

    @on(Input.Submitted, "#main-input")
    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return

        # Echo input
        self._chat_write(f"\n[bold cyan]>[/bold cyan] {text}")
        self._add_to_history("user", text)   # track for context window

        if text.lower() in ("/quit", "/exit", "/q"):
            self.exit()
            return

        if text.startswith("/"):
            self._handle_slash(text)
        else:
            self._handle_message(text)

    # ── Slash commands ────────────────────────────────────────────────────────

    def _handle_slash(self, text: str) -> None:
        parts = text.split(None, 1)
        cmd  = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        dispatch = {
            "/help":     self._cmd_help,
            "/mode":     self._cmd_mode,
            "/status":   self._cmd_status,
            "/plans":    self._cmd_plans,
            "/resume":   self._cmd_resume,
            "/index":    self._cmd_index,
            "/diff":     self._cmd_diff,
            "/memory":   self._cmd_memory,
            "/babysit":  self._cmd_babysit,
            "/review":   self._cmd_review,
            "/finalize": self._cmd_finalize,
            "/sync":     self._cmd_sync,
            "/changes":  self._cmd_changes,
            "/config":   self._cmd_config,
            "/search":   self._cmd_search,
            "/sites":    self._cmd_sites,
        }
        handler = dispatch.get(cmd)
        if handler:
            handler(args)
        else:
            self._chat_write(f"[red]Unknown command '{cmd}'. Type /help[/red]")

    def _cmd_help(self, _: str) -> None:
        self._chat_write("""
[bold]Slash commands:[/bold]
  [green]/mode [plan|agent|babysit|review][/green]  — switch mode
  [green]/babysit [PR#][/green]                     — babysit a PR
  [green]/review [PR#][/green]                      — review a PR
  [green]/plans[/green]                             — list plans (also: Plans tab)
  [green]/resume[/green]                            — resume last active plan
  [green]/index[/green]                             — rebuild RAG index
  [green]/sync[/green]                              — sync main branch now
  [green]/changes[/green]                           — show recent main changes
  [green]/memory [query][/green]                    — search agent memory
  [green]/diff[/green]                              — current branch diff
  [green]/status[/green]                            — git + PR status
  [green]/config[/green]                            — show/change providers & secrets
  [green]/finalize[/green]                          — extract plan from discussion

[bold]Keyboard shortcuts:[/bold]
  Ctrl+P  Plan mode    Ctrl+A  Agent mode
  Ctrl+B  Babysit      Ctrl+R  Review
  Ctrl+K  Config tab   Ctrl+S  Sync now
  Ctrl+I  Rebuild index  Ctrl+Q  Quit
""")

    def _cmd_mode(self, args: str) -> None:
        mode = args.strip().lower()
        valid = ("plan", "agent", "babysit", "review")
        if mode not in valid:
            self._chat_write(f"[red]Unknown mode. Options: {', '.join(valid)}[/red]")
            return
        self.action_set_mode(mode)

    def _cmd_status(self, _: str) -> None:
        self._show_status_worker()

    def _cmd_plans(self, _: str) -> None:
        plans = self.memory.list_plans()
        self.query_one(PlansTab).refresh_plans(plans)
        self.query_one("#tabs", TabbedContent).active = "tab-plans"

    def _cmd_resume(self, _: str) -> None:
        plan = self.memory.get_active_plan()
        if not plan:
            self._chat_write("[dim]No active plan[/dim]")
            return
        self.current_plan = plan
        done, total = plan.progress
        self._chat_write(
            f"\n[bold]Resuming:[/bold] {plan.task}\n"
            f"  Branch: [cyan]{plan.branch or 'none'}[/cyan]\n"
            f"  Progress: {done}/{total}"
        )
        for i, (step, is_done) in enumerate(zip(plan.steps, plan.steps_done)):
            icon = "✅" if is_done else "⬜"
            self._chat_write(f"  {icon} {i+1}. {step}")
        self._refresh_sidebar()
        self._chat_write("\n[dim]Switch to agent mode (Ctrl+A) and send any message to execute[/dim]")

    def _cmd_index(self, _: str) -> None:
        self._rebuild_index_worker()

    def _cmd_diff(self, _: str) -> None:
        diff = get_diff(self.cfg.repo_path)
        if diff:
            self._chat_write(f"```diff\n{diff[:4000]}\n```")
        else:
            self._chat_write("[dim]No changes vs main[/dim]")

    def _cmd_memory(self, args: str) -> None:
        query = args.strip() or None
        sessions = self.memory.recall_sessions(query=query, limit=5)
        if sessions:
            self._chat_write("\n[bold]Past work sessions:[/bold]")
            for s in sessions:
                status = "[green]merged[/green]" if s.merged else \
                         f"[blue]PR #{s.pr_number}[/blue]" if s.pr_number else "[dim]open[/dim]"
                self._chat_write(
                    f"  [cyan]{s.id}[/cyan] [{s.created_at[:10]}] {s.task[:50]} "
                    f"{status} · {len(s.discussion)} turns"
                )
        facts = self.memory.recall_facts(query=query)
        if facts:
            self._chat_write("\n[bold]Facts:[/bold]")
            for f in facts[:5]:
                self._chat_write(f"  [dim]{f['created_at'][:10]}[/dim] {f['content']}")
        if not sessions and not facts:
            self._chat_write("[dim]Nothing found[/dim]")

    def _cmd_babysit(self, args: str) -> None:
        pr_num = args.strip()
        if not pr_num.isdigit():
            try:
                branch = current_branch(self.cfg.repo_path)
                pr = self.pr_manager.get_pr_by_branch(branch)
                if pr:
                    pr_num = str(pr["number"])
                else:
                    self._chat_write("[red]No PR# given and no open PR for current branch[/red]")
                    return
            except Exception as e:
                self._chat_write(f"[red]{e}[/red]")
                return
        self.action_set_mode("babysit")
        self._babysit_worker(int(pr_num))

    def _cmd_review(self, args: str) -> None:
        pr_num = args.strip()
        if not pr_num.isdigit():
            self._chat_write("[red]Usage: /review <PR#>[/red]")
            return
        self.action_set_mode("review")
        self._review_worker(int(pr_num))

    def _cmd_finalize(self, _: str) -> None:
        if not self.current_plan or not self.current_plan.discussion:
            self._chat_write("[dim]No active discussion to finalize[/dim]")
            return
        self._finalize_worker()

    def _cmd_sync(self, _: str) -> None:
        self.action_manual_sync()

    def _cmd_changes(self, _: str) -> None:
        records = self.memory.recall_recent_changes(limit=10)
        self.query_one(ChangesTab).refresh_changes(records)
        self.query_one("#tabs", TabbedContent).active = "tab-changes"

    def _cmd_config(self, args: str) -> None:
        parts = args.strip().split()
        if not parts:
            self._show_config()
            return

        subcmd = parts[0].lower()

        if subcmd == "secrets":
            self._chat_write("\n[bold]Secrets status:[/bold]")
            for key, status in self.secrets.status().items():
                color = "green" if "[not set]" not in status else "dim"
                self._chat_write(f"  [{color}]{key:<24}[/{color}] {status}")
            return

        if subcmd == "set" and len(parts) >= 3:
            key, value = parts[1], parts[2]
            # Special case: context_limit updates ContextManager live
            if key == "context_limit":
                try:
                    self.ctx.limits.total = int(value)
                    self._chat_write(f"[green]✓[/green] context_limit set to {value} tokens")
                except ValueError:
                    self._chat_write(f"[red]Invalid value: {value}[/red]")
                return
            self.secrets.set_persistent(key, value)
            self._chat_write(f"[green]✓[/green] {key} saved to ~/.atman/.secrets")
            return

        if len(parts) >= 2:
            role, provider = parts[0], parts[1]
            ok, msg = self.router.switch(role, provider)
            if ok:
                self.provider_cfg.save(self._provider_cfg_file)
                self._chat_write(f"[green]✓[/green] {msg}")
                self._update_header()
                self._refresh_sidebar()
                self._refresh_config_tab()
            else:
                self._chat_write(f"[red]✗[/red] {msg}")
            return

        self._chat_write("[dim]Usage: /config [role provider] | [set key value] | [secrets][/dim]")

    def _show_config(self) -> None:
        self._chat_write("\n[bold]Providers:[/bold]")
        for role, current, options in self.router.status_table():
            icon = "🏠" if current in ("llamacpp", "local") else "☁"
            self._chat_write(f"  {role:<10} [cyan]{icon} {current}[/cyan]  [dim]{options}[/dim]")

        # Context window status
        lim = self.ctx.limits
        status = self.ctx.check(self._messages, self.current_plan)
        self._chat_write(
            f"\n[bold]Context window:[/bold] {lim.total:,} tokens · "
            f"warn at {lim.warning_ratio:.0%} · compress at {lim.critical_ratio:.0%}"
        )
        self._chat_write(
            f"  Now: [{status.color}]{status.display}[/{status.color}] "
            f"· compressed ×{self.ctx.compression_count}"
        )

        self._chat_write(
            "\n[dim]/config coder claude-sonnet  — switch coder[/dim]\n"
            "[dim]/config set anthropic_api_key sk-ant-...  — set key[/dim]\n"
            "[dim]/config set context_limit 32768  — change token limit[/dim]"
        )
        self.query_one("#tabs", TabbedContent).active = "tab-settings"
        self._refresh_config_tab()

    # ── Message dispatch by mode ──────────────────────────────────────────────

    def _add_to_history(self, role: str, content: str) -> None:
        """Add a message to history and check context usage."""
        self._messages.append({"role": role, "content": content})
        self._maybe_compress()

    def _maybe_compress(self) -> None:
        """Check token usage; if critical, compress in background."""
        status = self.ctx.check(self._messages, self.current_plan)
        if status.level == "warning":
            self._chat_write(
                f"[yellow]⚠ Context {status.display} — approaching limit[/yellow]"
            )
            self._refresh_sidebar()
        elif status.should_compress:
            self._chat_write(
                f"[red]◆ Context {status.display} — compressing...[/red]"
            )
            self._compress_context_worker()

    @work(thread=True, exclusive=False)
    def _compress_context_worker(self) -> None:
        """Compress context in background thread. Plan is preserved fully."""
        try:
            snapshot = self.ctx.compress(self._messages, self.current_plan)

            # Rebuild message history
            new_messages = self.ctx.rebuild_messages(snapshot)
            self._messages = new_messages

            self.call_from_thread(
                self._chat_write,
                f"\n[bold cyan]◆ Context compressed[/bold cyan] "
                f"[dim]({snapshot.tokens_before:,} → {snapshot.tokens_after:,} tokens · "
                f"saved {len(snapshot.key_facts)} facts to memory)[/dim]"
            )
            if snapshot.key_facts:
                self.call_from_thread(self._chat_write, "[dim]  Saved facts:[/dim]")
                for f in snapshot.key_facts[:3]:
                    self.call_from_thread(self._chat_write, f"  [dim]  • {f[:80]}[/dim]")
                if len(snapshot.key_facts) > 3:
                    self.call_from_thread(
                        self._chat_write,
                        f"  [dim]  ... and {len(snapshot.key_facts)-3} more → /memory[/dim]"
                    )

            # Plan is always preserved
            if self.current_plan:
                self.call_from_thread(
                    self._chat_write,
                    f"[dim]  Plan preserved: \"{self.current_plan.task}\" "
                    f"[{self.current_plan.progress_summary()}][/dim]"
                )

            self.call_from_thread(self._refresh_sidebar)

        except Exception as e:
            self.call_from_thread(
                self._chat_write, f"[red]Compression error: {e}[/red]"
            )

    def _handle_message(self, text: str) -> None:
        if self._busy:
            self._chat_write("[dim]⏳ Working... (Ctrl+C to interrupt)[/dim]")
            return

        # 1. URLs in message → fetch them first
        urls = extract_urls(text)
        if urls:
            self._fetch_urls_and_dispatch(text, urls)
            return

        # 2. Search intent → web search first, then dispatch
        if has_search_intent(text):
            self._search_and_dispatch(text)
            return

        # 3. Normal mode dispatch
        if self.mode == "plan":
            self._plan_discuss_worker(text)
        elif self.mode == "agent":
            self._agent_task_worker(text)
        elif self.mode == "babysit":
            self._chat_write("[dim]Use /babysit <PR#>[/dim]")
        elif self.mode == "review":
            self._chat_write("[dim]Use /review <PR#>[/dim]")

    # ── Actions (keyboard bindings) ───────────────────────────────────────────

    def action_set_mode(self, mode: str) -> None:
        self.mode = mode
        mode_colors = {
            "plan": "yellow", "agent": "green",
            "babysit": "cyan", "review": "magenta",
        }
        c = mode_colors.get(mode, "white")
        self._chat_write(f"[{c}]◆ Switched to {mode} mode[/{c}]")
        self._update_header()
        self._refresh_sidebar()

        # If switching to agent with active plan, hint
        if mode == "agent" and self.current_plan:
            next_step = self.current_plan.next_step()
            if next_step:
                self._chat_write(
                    f"[dim]Next step: {next_step} — "
                    f"send any message to execute plan[/dim]"
                )

    def action_show_config(self) -> None:
        self.query_one("#tabs", TabbedContent).active = "tab-settings"

    def action_show_setup(self) -> None:
        self.query_one("#tabs", TabbedContent).active = "tab-setup"
        self._refresh_config_tab()

    def action_manual_sync(self) -> None:
        self._sync_worker()

    def action_rebuild_index(self) -> None:
        self._rebuild_index_worker()

    # ── Workers (run in threads, update UI via call_from_thread) ─────────────

    def _search_and_dispatch(self, text: str) -> None:
        """Detected search intent — search web then pass results to mode handler."""
        self._search_worker(text)

    @work(thread=True, exclusive=False)
    def _search_worker(self, original_text: str) -> None:
        self._busy = True
        try:
            query = extract_search_query(original_text)
            self.call_from_thread(
                self._chat_write,
                f"[dim]◆ Searching dev sites for: [bold]{query}[/bold][/dim]"
            )

            session = search(query, fetch_content=True)

            if session.expanded:
                self.call_from_thread(
                    self._chat_write,
                    "[dim]  Dev sites thin — expanded to general web[/dim]"
                )

            good_results = [r for r in session.results if r.ok]
            if good_results:
                for r in good_results[:3]:
                    self.call_from_thread(
                        self._chat_write,
                        f"  [green]✓[/green] [{r.domain}] {r.title}"
                    )
            else:
                self.call_from_thread(
                    self._chat_write,
                    "[yellow]⚠ No useful results found[/yellow]"
                )

            # Inject search results into context and dispatch
            web_context = session.to_context(max_results=3)
            enriched = f"{original_text}\n\n{web_context}"

            self.call_from_thread(self._chat_write, "")

            if self.mode == "plan":
                if not self.current_plan:
                    self.current_plan = self.memory.create_plan(
                        task=original_text, steps=[],
                        discussion=[{"role": "user", "content": enriched}],
                    )
                else:
                    self.memory.append_to_discussion(self.current_plan, "user", enriched)
                context = self.rag.format_context(self.rag.search(original_text)) \
                          if self.rag.stats["chunks"] else ""
                history = self.memory.get_discussion_history(self.current_plan)
                self.call_from_thread(self._chat_write, "\n[bold cyan]◆ Thinking...[/bold cyan]")
                response = self.router.discuss(enriched, history, context)
                self.call_from_thread(self._chat_write, response)
                self.memory.append_to_discussion(self.current_plan, "assistant", response)
            elif self.mode == "agent":
                self._busy = False
                self.call_from_thread(lambda: self._agent_task_worker(enriched))
                return

        finally:
            self._busy = False

    def _cmd_search(self, args: str) -> None:
        """/search <query> — search dev sites directly."""
        if not args.strip():
            self._chat_write("[dim]Usage: /search <query>[/dim]")
            return
        self._search_worker(args.strip())

    def _cmd_sites(self, args: str) -> None:
        """/sites — list known dev sites. /sites add <domain> — add a site."""
        parts = args.strip().split()

        if parts and parts[0] == "add" and len(parts) >= 2:
            domain = parts[1].lstrip("https://").lstrip("http://").rstrip("/")
            label = " ".join(parts[2:]) if len(parts) > 2 else domain
            add_search_domain(domain, label)
            self._chat_write(f"[green]✓[/green] Added [cyan]{domain}[/cyan] to search priority list")
            return

        sites = get_known_sites()
        self._chat_write(f"\n[bold]Known dev sites ({len(sites)}):[/bold]")
        for s in sites:
            tags = ", ".join(s["tags"]) if s["tags"] else ""
            self._chat_write(
                f"  [cyan]{s['domain']:<35}[/cyan] "
                f"[dim]{s['label']:<20}[/dim] {tags}"
            )
        self._chat_write("\n[dim]/sites add <domain> [label] — add a site[/dim]")

    def _fetch_urls_and_dispatch(self, text: str, urls: list[str]) -> None:
        """Fetch URLs then pass enriched message to mode handler."""
        self._fetch_urls_worker(text, urls)

    @work(thread=True, exclusive=False)
    def _fetch_urls_worker(self, original_text: str, urls: list[str]) -> None:
        self._busy = True
        try:
            self.call_from_thread(
                self._chat_write,
                f"[dim]◆ Fetching {len(urls)} URL{'s' if len(urls) > 1 else ''}...[/dim]"
            )

            pages = []
            for url in urls:
                self.call_from_thread(self._chat_write, f"[dim]  → {url}[/dim]")
                # Use GitHub-specific fetcher for GitHub URLs
                if is_github_url(url):
                    page = fetch_github_raw(url, self.secrets.github_token)
                else:
                    from .web import fetch_url
                    page = fetch_url(url)

                if page.ok:
                    preview = page.content[:120].replace("\n", " ")
                    self.call_from_thread(
                        self._chat_write,
                        f"  [green]✓[/green] {page.title or page.domain} — {preview}..."
                    )
                else:
                    self.call_from_thread(
                        self._chat_write,
                        f"  [yellow]⚠[/yellow] {url}: {page.error}"
                    )
                pages.append(page)

            web_context = format_pages_for_context([p for p in pages if p.ok])

            if not web_context:
                self.call_from_thread(
                    self._chat_write,
                    "[yellow]Could not fetch any URLs — proceeding without web context[/yellow]"
                )
                web_context = ""

            # Now dispatch to mode handler with enriched context
            # Inject web content into the message for the LLM
            enriched = original_text
            if web_context:
                enriched = f"{original_text}\n\n{web_context}"

            self.call_from_thread(self._chat_write, "")  # blank line

            # Dispatch based on mode (directly, not via worker since we're in one)
            if self.mode == "plan":
                if not self.current_plan:
                    self.current_plan = self.memory.create_plan(
                        task=original_text, steps=[],
                        discussion=[{"role": "user", "content": enriched}],
                    )
                else:
                    self.memory.append_to_discussion(self.current_plan, "user", enriched)

                context = self.rag.format_context(self.rag.search(original_text)) \
                          if self.rag.stats["chunks"] else ""
                history = self.memory.get_discussion_history(self.current_plan)
                self.call_from_thread(self._chat_write, "\n[bold cyan]◆ Thinking...[/bold cyan]")
                response = self.router.discuss(enriched, history, context)
                self.call_from_thread(self._chat_write, response)
                self.memory.append_to_discussion(self.current_plan, "assistant", response)

            elif self.mode == "agent":
                # Run agent task with web content already in the message
                self._busy = False  # reset so _agent_task_worker can proceed
                self.call_from_thread(
                    lambda: self._agent_task_worker(enriched)
                )
                return  # _agent_task_worker will set _busy=False itself

        finally:
            self._busy = False


        self._busy = True
        try:
            # Branch guard
            try:
                branch, msgs = self.branch_guard.check_and_prepare(task)
                for m in msgs:
                    self.call_from_thread(self._chat_write, f"[dim]  {m}[/dim]")
            except RuntimeError as e:
                self.call_from_thread(self._chat_write, f"[red]Branch error: {e}[/red]")
                return

            if self.current_plan and self.current_plan.status == "active":
                # Execute existing plan
                self._run_executor(self.current_plan)
            else:
                # Auto-plan first, then execute
                self.call_from_thread(self._chat_write, "\n[bold cyan]◆ Planning...[/bold cyan]")
                summary, steps = auto_plan(task, self.router, self.rag)
                self.call_from_thread(self._chat_write, f"[dim]{summary}[/dim]")
                for i, s in enumerate(steps, 1):
                    self.call_from_thread(self._chat_write, f"  {i}. {s}")

                plan = self.memory.create_plan(
                    task=task,
                    steps=steps,
                    summary=summary,
                    branch=branch,
                )
                self.current_plan = plan
                self.call_from_thread(self._refresh_sidebar)

                self._run_executor(plan)

        finally:
            self._busy = False

    def _run_executor(self, plan: Plan) -> None:
        """
        Create and run a PlanExecutor, bridging output to Textual UI.
        Called from a worker thread.
        """
        def output(text: str, markup: bool = True) -> None:
            self.call_from_thread(self._chat_write, text) if markup else \
            self.call_from_thread(self._chat_write, text)
            # sidebar refresh on step completion markers
            if "✅" in text or "🚫" in text or "↩" in text:
                self.call_from_thread(self._refresh_sidebar)

        executor = PlanExecutor(
            plan=plan,
            router=self.router,
            rag=self.rag,
            memory=self.memory,
            output=output,
        )
        self._current_executor = executor
        executor.run()
        self._current_executor = None

        # After plan finishes — offer commit if there are changes
        _, out, _ = run_git(["status", "--porcelain"], self.cfg.repo_path)
        if out.strip():
            self.call_from_thread(
                self._chat_write,
                "\n[dim]Changes detected. Type /commit to commit, or keep editing.[/dim]"
            )
        self.call_from_thread(self._refresh_sidebar)

    @work(thread=True, exclusive=False)
    def _plan_discuss_worker(self, message: str) -> None:
        self._busy = True
        try:
            if not self.current_plan:
                self.current_plan = self.memory.create_plan(
                    task=message, steps=[],
                    discussion=[{"role": "user", "content": message}],
                )
            else:
                self.memory.append_to_discussion(self.current_plan, "user", message)

            context = self.rag.format_context(self.rag.search(message)) \
                      if self.rag.stats["chunks"] else ""

            self.call_from_thread(self._chat_write, "\n[bold cyan]◆ Thinking...[/bold cyan]")
            history = self.memory.get_discussion_history(self.current_plan)
            response = self.router.discuss(message, history, context)
            self.call_from_thread(self._chat_write, response)
            self.memory.append_to_discussion(self.current_plan, "assistant", response)
            # Track in context window
            self.call_from_thread(self._add_to_history, "assistant", response)

            if any(kw in response.lower() for kw in ["step 1", "1.", "## steps"]):
                self.call_from_thread(
                    self._chat_write,
                    "\n[dim]Plan emerging — type [bold]/finalize[/bold] to save it.[/dim]"
                )
            self.call_from_thread(self._refresh_sidebar)

        finally:
            self._busy = False

    @work(thread=True, exclusive=False)
    def _finalize_worker(self) -> None:
        self._busy = True
        try:
            import json, re
            history_text = "\n".join(
                f"{m['role'].upper()}: {m['content']}"
                for m in self.current_plan.discussion
            )
            extract_prompt = (
                f"Extract a structured plan from this discussion:\n\n{history_text}\n\n"
                f'Return JSON only: {{"task": "...", "summary": "...", "steps": ["..."]}}'
            )
            raw = self.router.analyze(extract_prompt)
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if not match:
                self.call_from_thread(self._chat_write, "[red]Could not extract plan[/red]")
                return
            data = json.loads(match.group())
            steps = data.get("steps", [])
            self.current_plan.task = data.get("task", self.current_plan.task)
            self.current_plan.summary = data.get("summary", "")
            self.current_plan.steps = steps
            self.current_plan.steps_done = [False] * len(steps)
            self.memory.update_plan(self.current_plan)

            self.call_from_thread(self._chat_write, f"\n[green]✓ Plan saved:[/green] {self.current_plan.task}")
            for i, step in enumerate(steps, 1):
                self.call_from_thread(self._chat_write, f"  {i}. {step}")
            self.call_from_thread(self._chat_write, "\n[dim]Press Ctrl+A to switch to agent mode and execute, or send any message[/dim]")
            self.call_from_thread(self._refresh_sidebar)

        except Exception as e:
            self.call_from_thread(self._chat_write, f"[red]Finalize error: {e}[/red]")
        finally:
            self._busy = False

    @work(thread=True, exclusive=False)
    def _babysit_worker(self, pr_number: int) -> None:
        self._busy = True
        try:
            self.call_from_thread(
                self._chat_write,
                f"\n[bold blue]◆ Babysitting PR #{pr_number}[/bold blue]\n"
                "[dim]  Priority: review comments → conflicts → CI → merge[/dim]"
            )
            max_attempts = self.cfg.babysit_max_fix_attempts
            for attempt in range(max_attempts):
                status = self.pr_manager.get_pr_status(pr_number)
                pr = status["pr"]
                branch = pr["head"]["ref"]

                ci = status["ci_status"]
                ci_color = {"passing": "green", "failing": "red", "pending": "yellow"}.get(ci, "white")
                self.call_from_thread(
                    self._chat_write,
                    f"  [dim]#{attempt+1}[/dim] CI:[{ci_color}]{ci}[/{ci_color}]  "
                    f"Reviews:{'✅' if status['approved'] else '⏳'}  "
                    f"Merge:{status.get('mergeable_state','?')}"
                )

                if status["unresolved_comments"]:
                    self.call_from_thread(self._chat_write, "  [bold]Resolving review comments...[/bold]")
                    self._resolve_review_comments_sync(pr_number, status["unresolved_comments"], branch)
                    time.sleep(5)
                    continue

                if status.get("mergeable_state") == "dirty":
                    self.call_from_thread(self._chat_write, "  [bold]Resolving conflicts...[/bold]")
                    # simplified: let user know
                    self.call_from_thread(
                        self._chat_write,
                        "[yellow]⚠ Merge conflicts detected — resolving...[/yellow]"
                    )
                    time.sleep(5)
                    continue

                if ci == "failing":
                    self.call_from_thread(self._chat_write, "  [bold]Fixing CI failures...[/bold]")
                    logs = self.pr_manager.get_ci_logs(pr_number)
                    analysis = self.router.analyze(
                        f"Analyze CI failures and suggest fixes:\n" +
                        "\n".join(f"=== {l['name']} ===\n{l['log']}" for l in logs)[:4000]
                    )
                    self.call_from_thread(self._chat_write, analysis)
                    time.sleep(10)
                    continue

                if ci == "pending":
                    self.call_from_thread(
                        self._chat_write,
                        f"  [dim]CI pending — waiting {self.cfg.babysit_poll_interval}s...[/dim]"
                    )
                    time.sleep(self.cfg.babysit_poll_interval)
                    continue

                if ci == "passing" and status.get("mergeable_state") == "clean":
                    need_approval = self.cfg.babysit_require_approval
                    if need_approval and not status["approved"]:
                        self.call_from_thread(
                            self._chat_write,
                            f"  [dim]CI green but waiting for approval "
                            f"(disable in Settings → Babysit → Require PR approval)[/dim]"
                        )
                        time.sleep(self.cfg.babysit_poll_interval)
                        continue
                    result = self.pr_manager.merge_pr(pr_number)
                    self.call_from_thread(
                        self._chat_write, f"[green]✅ PR #{pr_number} merged![/green]"
                    )
                    if self.current_plan:
                        session = self.memory.get_session_for_plan(self.current_plan.id)
                        if session:
                            self.memory.update_work_session(session, merged=True)
                        self.memory.complete_plan(self.current_plan.id)
                        self.current_plan = None
                    # Trigger sync
                    self.watcher.after_self_merge(pr_number=pr_number)
                    self.call_from_thread(self._refresh_sidebar)
                    return

                time.sleep(self.cfg.babysit_poll_interval)

            self.call_from_thread(
                self._chat_write,
                f"[yellow]⚠ Max attempts reached — PR #{pr_number} needs manual attention[/yellow]"
            )
        except Exception as e:
            self.call_from_thread(self._chat_write, f"[red]Babysit error: {e}[/red]")
        finally:
            self._busy = False

    @work(thread=True, exclusive=False)
    def _review_worker(self, pr_number: int) -> None:
        self._busy = True
        try:
            self.call_from_thread(
                self._chat_write, f"\n[bold magenta]◆ Reviewing PR #{pr_number}[/bold magenta]"
            )
            pr = self.pr_manager.get_pr(pr_number)
            diff = get_diff(self.cfg.repo_path, pr["base"]["ref"])
            self.call_from_thread(self._chat_write, "[dim]◆ Analyzing...[/dim]")

            review_parts = []
            for chunk in self.router.code_stream(
                f"Review this PR for the Atman project.\n"
                f"PR: {pr['title']}\n{pr.get('body','')}\n\nDiff:\n{diff[:5000]}"
            ):
                self.call_from_thread(self._chat_write, chunk)
                review_parts.append(chunk)

            review_text = "".join(review_parts)
            self.call_from_thread(
                self._chat_write,
                "\n[dim]Type [bold]/config[/bold] to check your GitHub token, "
                "then the review will be posted.[/dim]"
            )
            try:
                self.pr_manager.post_review(pr_number, review_text[:65000], [], "COMMENT")
                self.call_from_thread(
                    self._chat_write, f"[green]✓[/green] Review posted to PR #{pr_number}"
                )
            except Exception as e:
                self.call_from_thread(self._chat_write, f"[red]Post failed: {e}[/red]")
        finally:
            self._busy = False

    @work(thread=True, exclusive=False)
    def _show_status_worker(self) -> None:
        try:
            branch = current_branch(self.cfg.repo_path)
            _, log_out, _ = run_git(["log", "--oneline", "-5"], self.cfg.repo_path)
            self.call_from_thread(
                self._chat_write,
                f"\n[bold]Branch:[/bold] {branch}\n[bold]Recent commits:[/bold]\n{log_out}"
            )
            pr = self.pr_manager.get_pr_by_branch(branch)
            if pr:
                status = self.pr_manager.get_pr_status(pr["number"])
                ci = status["ci_status"]
                ci_c = {"passing": "green", "failing": "red", "pending": "yellow"}.get(ci, "white")
                self.call_from_thread(
                    self._chat_write,
                    f"\n[bold]PR #{pr['number']}:[/bold] {pr['title']}\n"
                    f"  CI: [{ci_c}]{ci}[/{ci_c}] · "
                    f"{'✅ approved' if status['approved'] else '⏳ pending'} · "
                    f"{status.get('mergeable_state','?')}"
                )
        except Exception as e:
            self.call_from_thread(self._chat_write, f"[red]Status error: {e}[/red]")

    @work(thread=True, exclusive=False)
    def _rebuild_index_worker(self) -> None:
        self.call_from_thread(self._chat_write, "[dim]◆ Building RAG index...[/dim]")
        n = self.rag.build(self.cfg.repo_path)
        self.call_from_thread(
            self._chat_write,
            f"[green]✓[/green] Indexed {n} chunks from {self.rag.stats['files']} files"
        )
        self.call_from_thread(self._refresh_sidebar)
        self.call_from_thread(self._update_header)

    @work(thread=True, exclusive=False)
    def _sync_worker(self) -> None:
        self.call_from_thread(self._chat_write, "[dim]◆ Syncing main...[/dim]")
        event = self.watcher.sync(source="manual")
        if event:
            all_files = event.files_added + event.files_changed + event.files_deleted
            self.call_from_thread(
                self._chat_write,
                f"[green]✓[/green] {event.commits_count} commit(s) · "
                f"+{event.insertions}/-{event.deletions} · {len(all_files)} files\n"
                + "\n".join(f"  [dim]{m}[/dim]" for m in event.commit_messages[:5])
            )
            records = self.memory.recall_recent_changes(limit=10)
            self.call_from_thread(
                lambda: self.query_one(ChangesTab).refresh_changes(records)
            )
        else:
            last_sha = self.watcher.last_seen_sha
            state_time = self.watcher._state.last_sync_at
            self.call_from_thread(
                self._chat_write,
                f"[dim]Main is up to date "
                f"(SHA: {last_sha[:8] if last_sha else 'none'} · "
                f"last: {state_time[:16] if state_time else 'never'})[/dim]"
            )

    # ── Sync helpers (called from worker threads) ─────────────────────────────

    def _resolve_review_comments_sync(self, pr_number: int, comments: list[dict], branch: str) -> None:
        for comment in comments:
            path = comment.get("path", "")
            body = comment.get("body", "")
            comment_id = comment["id"]
            context = self.rag.format_context(self.rag.search(f"{path} {body}"))
            analysis = self.router.analyze(f"Fix review comment: {body}\nFile: {path}\n{context}")
            commit_all(f"fix: address review comment on {path}", self.cfg.repo_path)
            push_branch(branch, self.cfg.repo_path)
            self.pr_manager.reply_to_comment(pr_number, comment_id, f"Fixed. {analysis[:200]}")
            self.call_from_thread(self._chat_write, f"  [green]✓[/green] Addressed: {path}")

    # ── UI refresh helpers ────────────────────────────────────────────────────

    def _refresh_sidebar(self) -> None:
        try:
            self.query_one(StatusSidebar).refresh_status()
        except NoMatches:
            pass

    def _refresh_all(self) -> None:
        self._refresh_sidebar()
        self._refresh_config_tab()
        plans = self.memory.list_plans()
        try:
            self.query_one(PlansTab).refresh_plans(plans)
        except NoMatches:
            pass

    def _refresh_config_tab(self) -> None:
        """Refresh the Settings tab — SettingsTab is self-contained, just switch to it."""
        try:
            self.query_one("#tabs", TabbedContent).active = "tab-settings"
        except NoMatches:
            pass

    def _chat_separator(self) -> None:
        self._chat_write("[dim]" + "─" * 60 + "[/dim]")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Atman Agent CLI (Textual TUI)")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--mode", choices=("plan", "agent", "babysit", "review"), default="agent")
    parser.add_argument("--llm-url", default=None)
    args = parser.parse_args()

    cfg = AgentConfig(repo_path=args.repo)
    if args.llm_url:
        cfg.llm_url = args.llm_url

    app = AtmanApp(cfg)
    app.mode = args.mode
    app.run()


if __name__ == "__main__":
    main()
