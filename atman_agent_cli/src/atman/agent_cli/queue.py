"""
Task queue persisted as JSON lines under ~/.atman/agent_memory/task_queue.jsonl,
plus Textual QueueScreen and AgentStatusBar (TASK-3.6 / TASK-3.7).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import ClassVar, Literal, cast

from textual.app import ComposeResult, RenderResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen, Screen
from textual.widget import Widget
from textual.widgets import Button, DataTable, Input, Label, Static

QUEUE_PATH = Path.home() / ".atman" / "agent_memory" / "task_queue.jsonl"


@dataclass
class QueueTask:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    description: str = ""
    priority: Literal["now", "later"] = "now"
    status: Literal["pending", "in_progress", "done", "blocked"] = "pending"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    order: int = 0


class TaskQueue:
    def __init__(self, path: Path = QUEUE_PATH) -> None:
        self.path = path
        self._tasks: list[QueueTask] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        self._tasks = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                with suppress(Exception):
                    self._tasks.append(QueueTask(**json.loads(line)))
        self._tasks.sort(key=lambda t: t.order)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            "\n".join(json.dumps(asdict(t)) for t in self._tasks) + ("\n" if self._tasks else ""),
            encoding="utf-8",
        )

    def add(self, title: str, description: str = "", priority: str = "now") -> QueueTask:
        p: Literal["now", "later"] = "later" if priority == "later" else "now"
        task = QueueTask(
            title=title,
            description=description,
            priority=p,
            order=len(self._tasks),
        )
        self._tasks.append(task)
        self._save()
        return task

    def delete(self, task_id: str) -> bool:
        before = len(self._tasks)
        self._tasks = [t for t in self._tasks if t.id != task_id]
        if len(self._tasks) < before:
            self._reorder()
            self._save()
            return True
        return False

    def move_up(self, task_id: str) -> None:
        idx = self._index(task_id)
        if idx > 0:
            self._tasks[idx], self._tasks[idx - 1] = self._tasks[idx - 1], self._tasks[idx]
            self._reorder()
            self._save()

    def move_down(self, task_id: str) -> None:
        idx = self._index(task_id)
        if idx < len(self._tasks) - 1:
            self._tasks[idx], self._tasks[idx + 1] = self._tasks[idx + 1], self._tasks[idx]
            self._reorder()
            self._save()

    def toggle_priority(self, task_id: str) -> None:
        task = self._get(task_id)
        task.priority = "later" if task.priority == "now" else "now"
        self._save()

    def set_status(self, task_id: str, status: str) -> None:
        valid: tuple[Literal["pending", "in_progress", "done", "blocked"], ...] = (
            "pending",
            "in_progress",
            "done",
            "blocked",
        )
        if status not in valid:
            raise ValueError(f"invalid status {status!r}")
        self._get(task_id).status = cast(
            Literal["pending", "in_progress", "done", "blocked"],
            status,
        )
        self._save()

    def next_pending(self) -> QueueTask | None:
        """First task with priority='now' and status='pending'."""
        return next((t for t in self._tasks if t.priority == "now" and t.status == "pending"), None)

    def all(self) -> list[QueueTask]:
        return list(self._tasks)

    def _index(self, task_id: str) -> int:
        for i, t in enumerate(self._tasks):
            if t.id == task_id:
                return i
        raise ValueError(f"Task {task_id} not found")

    def _get(self, task_id: str) -> QueueTask:
        return self._tasks[self._index(task_id)]

    def _reorder(self) -> None:
        for i, t in enumerate(self._tasks):
            t.order = i


def _cursor_task_id(table: DataTable) -> str | None:
    """Row key UUID for the cursor row."""
    try:
        if table.row_count == 0:
            return None
        rk = table.coordinate_to_cell_key(table.cursor_coordinate).row_key
        v = rk.value
        return str(v) if v is not None else None
    except Exception:
        return None


class _AddTaskDialog(ModalScreen[None]):
    """Simple modal to enter title and optional description."""

    def __init__(self, *, on_confirm: Callable[[str, str], None]) -> None:
        super().__init__()
        self._on_confirm = on_confirm

    def compose(self) -> ComposeResult:
        yield Label("Title")
        yield Input(placeholder="Task title", id="inp-queue-title")
        yield Label("Description")
        yield Input(placeholder="Optional details", id="inp-queue-desc")
        with Horizontal():
            yield Button("OK", id="btn-queue-ok", variant="primary")
            yield Button("Cancel", id="btn-queue-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-queue-cancel":
            self.dismiss()
            return
        if event.button.id == "btn-queue-ok":
            title = self.query_one("#inp-queue-title", Input).value.strip()
            desc = self.query_one("#inp-queue-desc", Input).value.strip()
            if title:
                self._on_confirm(title, desc)
            self.dismiss()


class QueueScreen(Screen[None]):
    """
    ┌─ Task Queue ──────────────────────────────────────────────┐
    │  ┌─ Queue ──────────────┐  ┌─ Description ──────────────┐ │
    │  │ ⚡ [now] Fix stream   │  │                            │ │
    │  └─────────────────────┘  └────────────────────────────┘ │
    │  [Add] [Delete] ...                                      │
    └───────────────────────────────────────────────────────────┘
    """

    BINDINGS: ClassVar[list[tuple[str, str, str]]] = [
        ("escape", "dismiss_action", "Close"),
        ("a", "add_task", "Add"),
        ("d", "delete_task", "Delete"),
        ("up", "move_up", "↑"),
        ("down", "move_down", "↓"),
        ("t", "toggle_priority", "Toggle now/later"),
        ("enter", "start_task", "→ Start"),
    ]

    def __init__(
        self,
        queue: TaskQueue,
        on_start: Callable[[QueueTask], None] | None = None,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.queue = queue
        self.on_start = on_start

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="queue-list"):
                yield DataTable(id="task-table", cursor_type="row")
            with Vertical(id="queue-desc"):
                yield Static("", id="task-description")
        with Horizontal(id="queue-buttons"):
            yield Button("Add", id="btn-add")
            yield Button("Delete", id="btn-delete")
            yield Button("↑", id="btn-up")
            yield Button("↓", id="btn-down")
            yield Button("Toggle now/later", id="btn-toggle")
            yield Button("→ Start", id="btn-start", variant="success")

    def on_mount(self) -> None:
        self._refresh_table()

    def action_dismiss_action(self) -> None:
        self.dismiss()

    def _refresh_table(self) -> None:
        table = self.query_one("#task-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Priority", "Status", "Title")
        for task in self.queue.all():
            icon = "⚡" if task.priority == "now" else "░░"
            table.add_row(f"{icon} [{task.priority}]", task.status, task.title, key=task.id)

    def _update_description_panel(self, task_id: str) -> None:
        tasks = {t.id: t for t in self.queue.all()}
        if task_id in tasks:
            self.query_one("#task-description", Static).update(
                tasks[task_id].description or "(no description)"
            )

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key.value:
            self._update_description_panel(str(event.row_key.value))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key.value:
            self._update_description_panel(str(event.row_key.value))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn = event.button.id
        if btn == "btn-add":
            self.action_add_task()
        elif btn == "btn-delete":
            self.action_delete_task()
        elif btn == "btn-up":
            self.action_move_up()
        elif btn == "btn-down":
            self.action_move_down()
        elif btn == "btn-toggle":
            self.action_toggle_priority()
        elif btn == "btn-start":
            self.action_start_task()

    def action_add_task(self) -> None:
        self.app.push_screen(_AddTaskDialog(on_confirm=self._on_add_confirm))

    def _on_add_confirm(self, title: str, description: str) -> None:
        self.queue.add(title, description, priority="now")
        self._refresh_table()

    def action_delete_task(self) -> None:
        table = self.query_one("#task-table", DataTable)
        tid = _cursor_task_id(table)
        if tid is not None:
            self.queue.delete(tid)
            self._refresh_table()

    def action_move_up(self) -> None:
        table = self.query_one("#task-table", DataTable)
        tid = _cursor_task_id(table)
        if tid is not None:
            self.queue.move_up(tid)
            self._refresh_table()

    def action_move_down(self) -> None:
        table = self.query_one("#task-table", DataTable)
        tid = _cursor_task_id(table)
        if tid is not None:
            self.queue.move_down(tid)
            self._refresh_table()

    def action_toggle_priority(self) -> None:
        table = self.query_one("#task-table", DataTable)
        tid = _cursor_task_id(table)
        if tid is not None:
            self.queue.toggle_priority(tid)
            self._refresh_table()

    def action_start_task(self) -> None:
        table = self.query_one("#task-table", DataTable)
        tid = _cursor_task_id(table)
        if tid is None:
            return
        tasks_map = {t.id: t for t in self.queue.all()}
        if tid in tasks_map and self.on_start:
            self.queue.set_status(tid, "in_progress")
            self.on_start(tasks_map[tid])
            self.dismiss()


class AgentStatusBar(Widget):
    """
    Status strip for Textual screens; compose with:
        yield AgentStatusBar(id="status-bar")

    ● Busy │ Executing: "…" │ Plan: N/M │ branch │ chunks │ tokens
    """

    DEFAULT_CSS = """
    AgentStatusBar {
        height: 1;
        background: $surface;
        color: $text-muted;
        dock: bottom;
    }
    """

    is_busy: reactive[bool] = reactive(False)
    current_task: reactive[str] = reactive("")
    plan_progress: reactive[str] = reactive("")
    branch: reactive[str] = reactive("main")
    rag_chunks: reactive[int] = reactive(0)
    tokens_used: reactive[int] = reactive(0)
    tokens_limit: reactive[int] = reactive(8192)

    def render(self) -> RenderResult:
        icon = "●" if self.is_busy else "○"
        task_text = self.current_task.strip()
        status = (
            (f'Executing: "{task_text}"')
            if self.is_busy and task_text
            else ("Executing" if self.is_busy else "Idle")
        )
        plan = self.plan_progress or "─"
        limit_k = max(self.tokens_limit, 1)
        tokens = f"{self.tokens_used / 1000:.1f}k/{limit_k / 1000:.0f}k tokens"
        parts = [icon, status, plan, self.branch, f"{self.rag_chunks} chunks", tokens]
        return "  │  ".join(parts)

    def update_status(
        self,
        *,
        busy: bool | None = None,
        task: str | None = None,
        plan_step: int | None = None,
        plan_total: int | None = None,
        branch: str | None = None,
        chunks: int | None = None,
        tokens_used: int | None = None,
        tokens_limit: int | None = None,
    ) -> None:
        if busy is not None:
            self.is_busy = busy
        if task is not None:
            self.current_task = task
        if plan_step is not None and plan_total is not None:
            self.plan_progress = f"Plan: {plan_step}/{plan_total}"
        if branch is not None:
            self.branch = branch
        if chunks is not None:
            self.rag_chunks = chunks
        if tokens_used is not None:
            self.tokens_used = tokens_used
        if tokens_limit is not None:
            self.tokens_limit = tokens_limit
