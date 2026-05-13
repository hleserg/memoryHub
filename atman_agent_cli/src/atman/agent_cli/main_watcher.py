"""
atman/agent_cli/main_watcher.py
Background watcher: tracks changes in main branch without LLM.
Records diffs, authors, timestamps to agent memory.
Runs in a daemon thread — fires and forgets.
"""
from __future__ import annotations

import json
import time
import threading
import logging
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Callable

from .config import AgentConfig
from .git import run_git, current_branch, pull_main

log = logging.getLogger("atman.watcher")


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class CommitEvent:
    """One commit or a batch of commits that landed on main."""
    sha: str                        # HEAD SHA after the event
    prev_sha: str                   # SHA before (our last known)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    source: str = "unknown"         # "self_merge" | "external_merge" | "webhook" | "init"
    pr_number: int | None = None
    pr_title: str | None = None
    author: str = ""

    # Git stats (no LLM)
    commits_count: int = 0
    files_changed: list[str] = field(default_factory=list)
    files_added: list[str] = field(default_factory=list)
    files_deleted: list[str] = field(default_factory=list)
    insertions: int = 0
    deletions: int = 0
    commit_messages: list[str] = field(default_factory=list)


@dataclass
class WatcherState:
    last_seen_sha: str = ""
    last_sync_at: str = ""
    events: list[dict] = field(default_factory=list)   # list of CommitEvent dicts


# ── MainWatcher ───────────────────────────────────────────────────────────────

class MainWatcher:
    """
    Watches main branch for changes.
    All operations are LLM-free — pure git stats.
    Runs in background daemon thread.

    Two triggers:
    1. Periodic poll (default every 60s) — catches external merges
    2. Manual trigger after self-merge — immediate

    Stores WatcherState to disk so agent can recall history across sessions.
    """

    def __init__(
        self,
        cfg: AgentConfig,
        on_change: Callable[[CommitEvent], None] | None = None,
    ) -> None:
        self.cfg = cfg
        self.repo = cfg.repo_path
        self.main = cfg.main_branch
        self.state_file = cfg.memory_path / "main_watcher_state.json"
        self.on_change = on_change  # optional callback for UI notification

        self._state = self._load_state()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    # ── State persistence ─────────────────────────────────────────────────────

    def _load_state(self) -> WatcherState:
        if not self.state_file.exists():
            return WatcherState()
        try:
            data = json.loads(self.state_file.read_text())
            state = WatcherState(
                last_seen_sha=data.get("last_seen_sha", ""),
                last_sync_at=data.get("last_sync_at", ""),
                events=data.get("events", []),
            )
            # Bootstrap: if no SHA stored yet, record current main HEAD
            if not state.last_seen_sha:
                state.last_seen_sha = self._get_main_sha(fetch=False)
            return state
        except Exception:
            return WatcherState()

    def _save_state(self) -> None:
        self.state_file.write_text(
            json.dumps(asdict(self._state), indent=2, ensure_ascii=False)
        )

    # ── Git helpers ───────────────────────────────────────────────────────────

    def _get_main_sha(self, fetch: bool = True) -> str:
        if fetch:
            run_git(["fetch", "origin", self.main, "--quiet"], self.repo)
        _, sha, _ = run_git(["rev-parse", f"origin/{self.main}"], self.repo)
        return sha.strip()

    def _get_diff_stats(self, from_sha: str, to_sha: str) -> dict:
        """Extract structured diff stats between two SHAs. No LLM."""
        stats: dict = {
            "commits_count": 0,
            "files_changed": [],
            "files_added": [],
            "files_deleted": [],
            "insertions": 0,
            "deletions": 0,
            "commit_messages": [],
            "author": "",
        }

        # Commit count and messages
        _, log_out, _ = run_git(
            ["log", f"{from_sha}..{to_sha}", "--oneline", "--no-merges"],
            self.repo,
        )
        lines = [l for l in log_out.splitlines() if l.strip()]
        stats["commits_count"] = len(lines)
        stats["commit_messages"] = [l[8:].strip() for l in lines[:20]]  # skip SHA

        # Author of last commit
        _, author_out, _ = run_git(
            ["log", "-1", "--format=%an", to_sha], self.repo
        )
        stats["author"] = author_out.strip()

        # Files changed with status
        _, diff_out, _ = run_git(
            ["diff", "--name-status", from_sha, to_sha], self.repo
        )
        for line in diff_out.splitlines():
            if not line.strip():
                continue
            parts = line.split("\t", 1)
            if len(parts) < 2:
                continue
            status, file_path = parts[0][0], parts[1]
            if status == "A":
                stats["files_added"].append(file_path)
            elif status == "D":
                stats["files_deleted"].append(file_path)
            else:
                stats["files_changed"].append(file_path)

        # Insertion/deletion counts
        _, numstat_out, _ = run_git(
            ["diff", "--numstat", from_sha, to_sha], self.repo
        )
        for line in numstat_out.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                try:
                    stats["insertions"] += int(parts[0]) if parts[0] != "-" else 0
                    stats["deletions"] += int(parts[1]) if parts[1] != "-" else 0
                except ValueError:
                    pass

        return stats

    # ── Core sync ─────────────────────────────────────────────────────────────

    def sync(self, source: str = "poll", pr_number: int | None = None, pr_title: str | None = None) -> CommitEvent | None:
        """
        Check if main has new commits since last seen SHA.
        Records the event if yes. Returns CommitEvent or None.
        Thread-safe.
        """
        with self._lock:
            try:
                current_sha = self._get_main_sha(fetch=True)
                prev_sha = self._state.last_seen_sha

                if not prev_sha:
                    # First run — just record current position
                    self._state.last_seen_sha = current_sha
                    self._state.last_sync_at = datetime.now(timezone.utc).isoformat()
                    self._save_state()
                    log.debug(f"Watcher initialized at {current_sha[:8]}")
                    return None

                if current_sha == prev_sha:
                    return None  # nothing new

                # New commits on main!
                log.info(f"Main changed: {prev_sha[:8]} → {current_sha[:8]} ({source})")

                diff_stats = self._get_diff_stats(prev_sha, current_sha)

                event = CommitEvent(
                    sha=current_sha,
                    prev_sha=prev_sha,
                    source=source,
                    pr_number=pr_number,
                    pr_title=pr_title,
                    **diff_stats,
                )

                # Update state
                self._state.last_seen_sha = current_sha
                self._state.last_sync_at = datetime.now(timezone.utc).isoformat()
                self._state.events.append(asdict(event))
                # Keep last 200 events
                if len(self._state.events) > 200:
                    self._state.events = self._state.events[-200:]
                self._save_state()

                if self.on_change:
                    self.on_change(event)

                return event

            except Exception as e:
                log.warning(f"Watcher sync error: {e}")
                return None

    def after_self_merge(self, pr_number: int | None = None, pr_title: str | None = None) -> None:
        """
        Call this immediately after agent merges a PR.
        Switches to main, pulls, records the event.
        """
        log.info("Self-merge detected — syncing main")
        try:
            pull_main(self.repo, self.main)
        except Exception as e:
            log.warning(f"Could not pull main: {e}")

        self.sync(source="self_merge", pr_number=pr_number, pr_title=pr_title)

    # ── Background polling ────────────────────────────────────────────────────

    def start_background(self, interval: int = 60) -> None:
        """Start daemon thread that polls main every `interval` seconds."""
        if self._thread and self._thread.is_alive():
            return

        self._stop_event.clear()

        def _loop():
            # Initial sync on startup
            self.sync(source="init")
            while not self._stop_event.wait(interval):
                self.sync(source="poll")

        self._thread = threading.Thread(target=_loop, daemon=True, name="main-watcher")
        self._thread.start()
        log.debug(f"MainWatcher started (interval={interval}s)")

    def stop(self) -> None:
        self._stop_event.set()

    # ── Query API for agent context ───────────────────────────────────────────

    def recent_changes(self, limit: int = 10) -> list[CommitEvent]:
        """Return recent main events as CommitEvent objects."""
        events = self._state.events[-limit:]
        return [CommitEvent(**e) for e in reversed(events)]

    def format_for_context(self, limit: int = 5) -> str:
        """
        Format recent main changes as text for LLM context injection.
        Agent uses this to stay current without re-indexing everything.
        """
        events = self.recent_changes(limit)
        if not events:
            return "No recent changes recorded for main branch."

        lines = [f"## Recent changes in {self.main} (last {len(events)} events)\n"]

        for ev in events:
            ts = ev.timestamp[:16].replace("T", " ")
            source_label = {
                "self_merge": "🤖 self-merged",
                "external_merge": "👤 external merge",
                "webhook": "🪝 webhook",
                "poll": "🔄 detected by poll",
                "init": "🚀 init",
            }.get(ev.source, ev.source)

            lines.append(f"### {ts} — {source_label}")
            if ev.pr_title:
                lines.append(f"PR: {ev.pr_title}" + (f" (#{ev.pr_number})" if ev.pr_number else ""))
            if ev.author:
                lines.append(f"Author: {ev.author}")
            lines.append(f"Commits: {ev.commits_count}  +{ev.insertions}/-{ev.deletions}")

            all_files = ev.files_added + ev.files_changed + ev.files_deleted
            if all_files:
                lines.append("Files:")
                for f in ev.files_added[:5]:
                    lines.append(f"  + {f}")
                for f in ev.files_changed[:10]:
                    lines.append(f"  ~ {f}")
                for f in ev.files_deleted[:5]:
                    lines.append(f"  - {f}")
                if len(all_files) > 20:
                    lines.append(f"  ... and {len(all_files) - 20} more")

            if ev.commit_messages:
                lines.append("Commits:")
                for msg in ev.commit_messages[:5]:
                    lines.append(f"  · {msg}")

            lines.append("")

        lines.append(f"Last known SHA: {self._state.last_seen_sha[:12]}")
        return "\n".join(lines)

    @property
    def last_seen_sha(self) -> str:
        return self._state.last_seen_sha

    @property
    def events_count(self) -> int:
        return len(self._state.events)
