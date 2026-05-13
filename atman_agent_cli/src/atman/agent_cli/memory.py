"""
atman/agent_cli/memory.py
Agent memory backed by Atman FactualMemory + ExperienceStore.
Stores plans, discussion context, decisions, task history.
Falls back to local JSONL if Atman not available.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import AgentConfig
from .main_watcher import CommitEvent


@dataclass
class WorkSession:
    """
    Full context of a work session: discussion → plan → implementation → PR.
    Stored alongside the Plan so context is never lost.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    plan_id: str = ""
    task: str = ""

    # Conversation that led to the plan
    discussion: list[dict] = field(default_factory=list)  # [{"role": ..., "content": ...}]

    # What was built
    commits: list[str] = field(default_factory=list)  # commit SHAs or messages
    branch: str = ""
    pr_number: int | None = None
    pr_url: str = ""
    files_changed: list[str] = field(default_factory=list)

    # Outcome
    merged: bool = False
    outcome_notes: str = ""  # why something didn't merge, what was fixed, etc.

    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def touch(self) -> None:
        self.updated_at = datetime.now().isoformat()

    def summary(self) -> str:
        status = (
            "merged"
            if self.merged
            else f"PR #{self.pr_number}"
            if self.pr_number
            else "in progress"
        )
        return (
            f"Task: {self.task} | "
            f"Branch: {self.branch} | "
            f"Status: {status} | "
            f"Files: {len(self.files_changed)} | "
            f"Discussion: {len(self.discussion)} turns"
        )


# Step states
STEP_PENDING = "pending"
STEP_DONE = "done"
STEP_BLOCKED = "blocked"  # tried, couldn't complete
STEP_IN_PROGRESS = "in_progress"


@dataclass
class StepMeta:
    """Rich metadata for a single plan step."""

    state: str = STEP_PENDING  # pending | done | blocked | in_progress
    blocked_reason: str = ""  # why it couldn't be done
    attempts: int = 0  # how many times we tried
    notes: str = ""  # what was done / result summary
    started_at: str = ""
    finished_at: str = ""

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "blocked_reason": self.blocked_reason,
            "attempts": self.attempts,
            "notes": self.notes,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> StepMeta:
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Plan:
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    task: str = ""
    summary: str = ""
    steps: list[str] = field(default_factory=list)

    # Legacy bool list — kept for backward compat, derived from steps_meta
    steps_done: list[bool] = field(default_factory=list)

    # Rich step metadata (parallel to steps list)
    steps_meta: list[dict] = field(default_factory=list)

    discussion: list[dict] = field(default_factory=list)
    branch: str = ""
    pr_number: int | None = None
    status: str = "active"  # active | done | abandoned
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def __post_init__(self) -> None:
        # Ensure steps_meta and steps_done are in sync with steps
        n = len(self.steps)
        if len(self.steps_meta) < n:
            for _ in range(n - len(self.steps_meta)):
                self.steps_meta.append(StepMeta().to_dict())
        if len(self.steps_done) < n:
            self.steps_done.extend([False] * (n - len(self.steps_done)))

    def _meta(self, index: int) -> StepMeta:
        return StepMeta.from_dict(self.steps_meta[index])

    def _set_meta(self, index: int, meta: StepMeta) -> None:
        self.steps_meta[index] = meta.to_dict()
        self.steps_done[index] = meta.state == STEP_DONE
        self.updated_at = datetime.now().isoformat()

    # ── Step state API ────────────────────────────────────────────────────────

    def mark_step_done(self, index: int, notes: str = "") -> None:
        meta = self._meta(index)
        meta.state = STEP_DONE
        meta.notes = notes
        meta.finished_at = datetime.now().isoformat()
        self._set_meta(index, meta)

    def mark_step_blocked(self, index: int, reason: str) -> None:
        meta = self._meta(index)
        meta.state = STEP_BLOCKED
        meta.blocked_reason = reason
        meta.attempts += 1
        meta.finished_at = datetime.now().isoformat()
        self._set_meta(index, meta)

    def mark_step_in_progress(self, index: int) -> None:
        meta = self._meta(index)
        meta.state = STEP_IN_PROGRESS
        meta.started_at = datetime.now().isoformat()
        meta.attempts += 1
        self._set_meta(index, meta)

    def unblock_step(self, index: int) -> None:
        """Reset a blocked step back to pending so it can be retried."""
        meta = self._meta(index)
        meta.state = STEP_PENDING
        meta.blocked_reason = ""
        self._set_meta(index, meta)

    def get_state(self, index: int) -> str:
        return self._meta(index).state

    def get_blocked_reason(self, index: int) -> str:
        return self._meta(index).blocked_reason

    def get_notes(self, index: int) -> str:
        return self._meta(index).notes

    # ── Navigation ────────────────────────────────────────────────────────────

    def next_pending_index(self) -> int | None:
        """Find the first pending (not done, not blocked) step."""
        for i, _step in enumerate(self.steps):
            if self.get_state(i) == STEP_PENDING:
                return i
        return None

    def blocked_indices_before(self, current_index: int) -> list[int]:
        """Return indices of blocked steps that come before current_index."""
        return [i for i in range(current_index) if self.get_state(i) == STEP_BLOCKED]

    def next_step(self) -> str | None:
        idx = self.next_pending_index()
        return self.steps[idx] if idx is not None else None

    def all_done_or_blocked(self) -> bool:
        return all(self.get_state(i) in (STEP_DONE, STEP_BLOCKED) for i in range(len(self.steps)))

    @property
    def progress(self) -> tuple[int, int]:
        done = sum(1 for i in range(len(self.steps)) if self.get_state(i) == STEP_DONE)
        return done, len(self.steps)

    def progress_summary(self) -> str:
        icons = {
            STEP_DONE: "✅",
            STEP_BLOCKED: "🚫",
            STEP_IN_PROGRESS: "⚡",
            STEP_PENDING: "⬜",
        }
        return " ".join(icons.get(self.get_state(i), "?") for i in range(len(self.steps)))

    def touch(self) -> None:
        self.updated_at = datetime.now().isoformat()


class AgentMemory:
    """
    Agent memory using Atman as backend when available,
    falling back to local JSONL.
    """

    def __init__(self, cfg: AgentConfig) -> None:
        self.cfg = cfg
        self._plans_file = cfg.memory_path / "plans.jsonl"
        self._facts_file = cfg.memory_path / "facts.jsonl"
        self._sessions_file = cfg.memory_path / "work_sessions.jsonl"

        self._atman_available = self._try_init_atman()
        self._plans: dict[str, Plan] = self._load_plans()
        self._sessions: dict[str, WorkSession] = self._load_sessions()

    def _try_init_atman(self) -> bool:
        """Try to initialize Atman memory components."""
        try:
            from atman.adapters.storage.file_state_store import FileStateStore
            from atman.core.services.experience_service import ExperienceService

            store = FileStateStore(base_path=self.cfg.memory_path / "atman_store")
            self._experience_service = ExperienceService(store=store)
            return True
        except Exception:
            return False

    def _load_plans(self) -> dict[str, Plan]:
        plans: dict[str, Plan] = {}
        if not self._plans_file.exists():
            return plans
        for line in self._plans_file.read_text().splitlines():
            if line.strip():
                try:
                    data = json.loads(line)
                    p = Plan(**data)
                    plans[p.id] = p
                except Exception:
                    continue
        return plans

    def _save_plan(self, plan: Plan) -> None:
        """Upsert plan to JSONL (rewrite file)."""
        self._plans[plan.id] = plan
        lines = [json.dumps(asdict(p), ensure_ascii=False) for p in self._plans.values()]
        self._plans_file.write_text("\n".join(lines) + "\n")

        # Also store in Atman if available
        if self._atman_available:
            self._store_in_atman(plan)

    def _store_in_atman(self, plan: Plan) -> None:
        """Persist plan summary as Atman fact for long-term memory."""
        try:
            from atman.adapters.memory.file_backend import FileBackend
            from atman.core.models.fact import FactRecord

            backend = FileBackend(base_path=self.cfg.memory_path / "atman_facts")
            fact = FactRecord(
                content=f"Agent plan '{plan.id}': {plan.task}. "
                f"Steps: {'; '.join(plan.steps)}. "
                f"Status: {plan.status}.",
                source="agent_cli",
                tags=["agent", "plan", plan.id],
            )
            backend.add(fact)
        except Exception:
            pass

    def _load_sessions(self) -> dict[str, WorkSession]:
        sessions: dict[str, WorkSession] = {}
        if not self._sessions_file.exists():
            return sessions
        for line in self._sessions_file.read_text().splitlines():
            if line.strip():
                try:
                    s = WorkSession(**json.loads(line))
                    sessions[s.id] = s
                except Exception:
                    continue
        return sessions

    def _save_session(self, session: WorkSession) -> None:
        self._sessions[session.id] = session
        lines = [json.dumps(asdict(s), ensure_ascii=False) for s in self._sessions.values()]
        self._sessions_file.write_text("\n".join(lines) + "\n")

        # Mirror into Atman ExperienceStore if available
        if self._atman_available:
            self._store_session_in_atman(session)

    def _store_session_in_atman(self, session: WorkSession) -> None:
        """Store work session as Atman experience for long-term recall."""
        try:
            from atman.adapters.storage.jsonl_experience_store import JsonlExperienceStore
            from atman.core.models.experience import KeyMoment, SessionExperience

            store = JsonlExperienceStore(base_path=self.cfg.memory_path / "atman_experiences")
            exp = SessionExperience(
                session_id=uuid.UUID(session.id.ljust(32, "0")[:32]),
                key_moments=[
                    KeyMoment(
                        what_happened=f"Discussed: {session.task}",
                        why_it_matters="Design decision and implementation context",
                        what_changed=session.outcome_notes or "Code implemented and PR created",
                    )
                ],
                key_insight=session.summary(),
            )
            store.save(exp)
        except Exception:
            pass

    # ── WorkSession CRUD ──────────────────────────────────────────────────────

    def start_work_session(self, plan: Plan) -> WorkSession:
        """Create a WorkSession linked to a Plan, copying discussion history."""
        session = WorkSession(
            plan_id=plan.id,
            task=plan.task,
            discussion=list(plan.discussion),  # copy discussion from plan
            branch=plan.branch,
            pr_number=plan.pr_number,
        )
        self._save_session(session)
        return session

    def update_work_session(
        self,
        session: WorkSession,
        *,
        commit: str | None = None,
        files_changed: list[str] | None = None,
        pr_number: int | None = None,
        pr_url: str | None = None,
        merged: bool | None = None,
        outcome_notes: str | None = None,
        append_discussion: dict | None = None,
    ) -> None:
        """Update a work session with new context. All params optional."""
        if commit:
            session.commits.append(commit)
        if files_changed:
            session.files_changed.extend(f for f in files_changed if f not in session.files_changed)
        if pr_number is not None:
            session.pr_number = pr_number
        if pr_url is not None:
            session.pr_url = pr_url
        if merged is not None:
            session.merged = merged
        if outcome_notes:
            session.outcome_notes = (session.outcome_notes + "\n" + outcome_notes).strip()
        if append_discussion:
            session.discussion.append(append_discussion)
        session.touch()
        self._save_session(session)

    def get_session_for_plan(self, plan_id: str) -> WorkSession | None:
        for s in self._sessions.values():
            if s.plan_id == plan_id:
                return s
        return None

    def recall_sessions(self, query: str | None = None, limit: int = 10) -> list[WorkSession]:
        """Search work sessions by task text."""
        sessions = sorted(self._sessions.values(), key=lambda s: s.updated_at, reverse=True)
        if query:
            q = query.lower()
            sessions = [
                s
                for s in sessions
                if q in s.task.lower() or any(q in turn["content"].lower() for turn in s.discussion)
            ]
        return sessions[:limit]

    def recall_context_for_task(self, task: str) -> str:
        """
        Find the most relevant past work session and return its full context.
        Used for /memory queries and RAG-style context injection.
        """
        sessions = self.recall_sessions(query=task, limit=3)
        if not sessions:
            return ""

        parts = []
        for s in sessions:
            disc = "\n".join(
                f"  {m['role'].upper()}: {m['content'][:300]}"
                for m in s.discussion[-6:]  # last 6 turns
            )
            parts.append(
                f"=== Past session: {s.task} ({s.created_at[:10]}) ===\n"
                f"Branch: {s.branch} | PR: #{s.pr_number or 'none'} | "
                f"{'MERGED' if s.merged else 'open'}\n"
                f"Files changed: {', '.join(s.files_changed[:5]) or 'none'}\n"
                f"Discussion:\n{disc}\n"
                f"Outcome: {s.outcome_notes or 'completed'}"
            )
        return "\n\n".join(parts)

    # ── Plan CRUD ─────────────────────────────────────────────────────────────

    def create_plan(
        self,
        task: str,
        steps: list[str],
        summary: str = "",
        branch: str = "",
        discussion: list[dict] | None = None,
    ) -> Plan:
        plan = Plan(
            task=task,
            summary=summary,
            steps=steps,
            steps_done=[False] * len(steps),
            branch=branch,
            discussion=discussion or [],
        )
        self._save_plan(plan)
        return plan

    def get_active_plan(self) -> Plan | None:
        """Get the most recently updated active plan."""
        active = [p for p in self._plans.values() if p.status == "active"]
        if not active:
            return None
        return max(active, key=lambda p: p.updated_at)

    def get_plan(self, plan_id: str) -> Plan | None:
        return self._plans.get(plan_id)

    def list_plans(self, status: str | None = None) -> list[Plan]:
        plans = list(self._plans.values())
        if status:
            plans = [p for p in plans if p.status == status]
        return sorted(plans, key=lambda p: p.updated_at, reverse=True)

    def update_plan(self, plan: Plan) -> None:
        plan.touch()
        self._save_plan(plan)

    def abandon_plan(self, plan_id: str) -> None:
        if plan_id in self._plans:
            self._plans[plan_id].status = "abandoned"
            self._save_plan(self._plans[plan_id])

    def complete_plan(self, plan_id: str) -> None:
        if plan_id in self._plans:
            self._plans[plan_id].status = "done"
            self._save_plan(self._plans[plan_id])

    # ── Discussion history (for planning mode) ────────────────────────────────

    def append_to_discussion(self, plan: Plan, role: str, content: str) -> None:
        plan.discussion.append({"role": role, "content": content})
        self.update_plan(plan)

    def get_discussion_history(self, plan: Plan) -> list[dict]:
        return plan.discussion

    # ── Standalone facts ──────────────────────────────────────────────────────

    def remember_fact(self, content: str, tags: list[str] | None = None) -> None:
        """Store an arbitrary fact (decision, context, etc.)."""
        record = {
            "content": content,
            "tags": tags or [],
            "created_at": datetime.now().isoformat(),
        }
        with open(self._facts_file, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def recall_facts(self, query: str | None = None, tags: list[str] | None = None) -> list[dict]:
        """Retrieve facts, optionally filtered."""
        if not self._facts_file.exists():
            return []
        facts = []
        for line in self._facts_file.read_text().splitlines():
            if line.strip():
                try:
                    f = json.loads(line)
                    if tags and not any(t in f.get("tags", []) for t in tags):
                        continue
                    if query and query.lower() not in f["content"].lower():
                        continue
                    facts.append(f)
                except Exception:
                    continue
        return facts

    @property
    def backend_name(self) -> str:
        return "Atman" if self._atman_available else "local JSONL"

    # ── Changeset storage (no LLM, called from sync service) ──────────────────

    def save_changeset_from_event(self, event: CommitEvent) -> None:
        """
        Adapter: converts MainWatcher CommitEvent → changeset record.
        Called from the on_change callback — no LLM, fire-and-forget.
        """
        all_files = event.files_added + event.files_changed + event.files_deleted
        record = {
            "from_sha": event.prev_sha,
            "to_sha": event.sha,
            "branch": "main",
            "synced_at": event.timestamp,
            "commit_log": event.commit_messages,
            "files_changed": all_files,
            "files_added": event.files_added,
            "files_deleted": event.files_deleted,
            "diff_stat": f"+{event.insertions}/-{event.deletions} in {len(all_files)} files",
            "authors": [event.author] if event.author else [],
            "triggered_by": event.source,
            "pr_number": event.pr_number,
            "pr_title": event.pr_title or "",
        }
        changesets_file = self.cfg.memory_path / "changesets.jsonl"
        with open(changesets_file, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def save_changeset(self, changeset: Any) -> None:
        """
        Persist a main-branch changeset. Called by MainSyncService — no LLM.
        Stores timestamp so agent always knows what's fresh vs stale.
        """
        from dataclasses import asdict

        record = asdict(changeset)
        changesets_file = self.cfg.memory_path / "changesets.jsonl"
        with open(changesets_file, "a") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def recall_recent_changes(self, limit: int = 10) -> list[dict]:
        """
        Return recent changesets, newest first.
        Agent uses this to understand what's landed in main since it last looked.
        """
        changesets_file = self.cfg.memory_path / "changesets.jsonl"
        if not changesets_file.exists():
            return []
        records = []
        for line in changesets_file.read_text().splitlines():
            if line.strip():
                try:
                    records.append(json.loads(line))
                except Exception:
                    continue
        return sorted(records, key=lambda r: r.get("synced_at", ""), reverse=True)[:limit]

    def format_recent_changes_for_context(self, limit: int = 5) -> str:
        """
        Format recent changesets as context string for LLM injection.
        Includes timestamp so agent knows how fresh the info is.
        """
        records = self.recall_recent_changes(limit)
        if not records:
            return ""
        parts = ["## Recent changes in main (from memory):"]
        for r in records:
            age = r.get("synced_at", "")[:10]
            trigger = r.get("triggered_by", "?")
            pr_info = f" (PR #{r['pr_number']}: {r['pr_title']})" if r.get("pr_number") else ""
            parts.append(
                f"\n[{age}] {r.get('diff_stat', '')}{pr_info} [{trigger}]\n"
                f"  Commits: {len(r.get('commit_log', []))}\n"
                f"  Files: {', '.join(r.get('files_changed', [])[:8])}"
                + (" ..." if len(r.get("files_changed", [])) > 8 else "")
            )
        return "\n".join(parts)


SUMMARIES_PATH = Path.home() / ".atman" / "agent_memory" / "session_summaries.jsonl"


@dataclass
class SessionSummary:
    session_id: str
    started_at: str  # ISO datetime
    ended_at: str  # ISO datetime
    task_description: str
    files_changed: list[str]
    decisions_made: list[str]
    open_questions: list[str]
    next_suggested_step: str
    outcome: str  # completed | blocked | abandoned


class SessionSummaryStore:
    def __init__(self, path: Path = SUMMARIES_PATH):
        self.path = path

    def save(self, summary: SessionSummary) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(summary)) + "\n")

    def load_last(self, n: int = 1) -> list[SessionSummary]:
        if not self.path.exists():
            return []
        lines = [ln for ln in self.path.read_text().splitlines() if ln.strip()]
        return [SessionSummary(**json.loads(ln)) for ln in lines[-n:]]

    def format_for_prompt(self, summary: SessionSummary) -> str:
        lines = [
            f"=== Previous Session ({summary.started_at[:10]}) ===",
            f"Task: {summary.task_description}",
            f"Outcome: {summary.outcome}",
        ]
        if summary.files_changed:
            lines.append(f"Files changed: {', '.join(summary.files_changed)}")
        if summary.decisions_made:
            lines.append("Decisions:")
            lines.extend(f"  - {d}" for d in summary.decisions_made)
        if summary.open_questions:
            lines.append("Open questions:")
            lines.extend(f"  - {q}" for q in summary.open_questions)
        if summary.next_suggested_step:
            lines.append(f"Suggested next step: {summary.next_suggested_step}")
        return "\n".join(lines)
