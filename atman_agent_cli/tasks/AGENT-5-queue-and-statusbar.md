# AGENT-5 — Task Queue + Status Bar (Textual)

## Контекст

Ты создаёшь новый модуль `queue.py` и Textual-виджет `AgentStatusBar`.

**Создать:**
- `atman_agent_cli/src/atman/agent_cli/queue.py`

**Минимальное касание существующих файлов:**
- `cli.py` — только добавить импорт и подключить `AgentStatusBar` в `compose()`. Описано в CLI Integration Notes.

Никаких конфликтов с другими агентами — `queue.py` новый файл.

---

## TASK-3.6 — Task Queue

**Файл:** `queue.py`

```python
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Literal

QUEUE_PATH = Path.home() / '.atman' / 'agent_memory' / 'task_queue.jsonl'


@dataclass
class QueueTask:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ''
    description: str = ''
    priority: Literal['now', 'later'] = 'now'
    status: Literal['pending', 'in_progress', 'done', 'blocked'] = 'pending'
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    order: int = 0


class TaskQueue:
    def __init__(self, path: Path = QUEUE_PATH):
        self.path = path
        self._tasks: list[QueueTask] = []
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        self._tasks = []
        for line in self.path.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    self._tasks.append(QueueTask(**json.loads(line)))
                except Exception:
                    pass
        self._tasks.sort(key=lambda t: t.order)

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            '\n'.join(json.dumps(asdict(t)) for t in self._tasks),
            encoding='utf-8',
        )

    def add(self, title: str, description: str = '', priority: str = 'now') -> QueueTask:
        task = QueueTask(
            title=title,
            description=description,
            priority=priority,
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
        task.priority = 'later' if task.priority == 'now' else 'now'
        self._save()

    def set_status(self, task_id: str, status: str) -> None:
        self._get(task_id).status = status
        self._save()

    def next_pending(self) -> QueueTask | None:
        """Первая задача priority='now' со status='pending'."""
        return next(
            (t for t in self._tasks if t.priority == 'now' and t.status == 'pending'),
            None,
        )

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
```

---

## TASK-3.6 — QueueScreen (Textual full-screen)

```python
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import DataTable, Static, TextArea, Button, Label
from textual.containers import Horizontal, Vertical


class QueueScreen(Screen):
    """
    ┌─ Task Queue ──────────────────────────────────────────────┐
    │  ┌─ Queue ──────────────┐  ┌─ Description ──────────────┐ │
    │  │ ⚡ [now] Fix stream  │  │                            │ │
    │  │ ⚡ [now] Add /commit │  │  Description text here...  │ │
    │  │ ░░ [later] Telegram  │  │                            │ │
    │  └─────────────────────┘  └────────────────────────────┘ │
    │  [Add] [Delete] [↑] [↓] [Toggle] [→ Start]               │
    └───────────────────────────────────────────────────────────┘
    """

    BINDINGS = [
        ("escape", "dismiss", "Close"),
        ("a", "add_task", "Add"),
        ("d", "delete_task", "Delete"),
        ("up", "move_up", "↑"),
        ("down", "move_down", "↓"),
        ("t", "toggle_priority", "Toggle now/later"),
        ("enter", "start_task", "→ Start"),
    ]

    def __init__(self, queue: 'TaskQueue', on_start: callable = None, **kwargs):
        super().__init__(**kwargs)
        self.queue = queue
        self.on_start = on_start  # callback(task: QueueTask)

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

    def _refresh_table(self) -> None:
        table = self.query_one("#task-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Priority", "Status", "Title")
        for task in self.queue.all():
            icon = "⚡" if task.priority == "now" else "░░"
            table.add_row(f"{icon} [{task.priority}]", task.status, task.title, key=task.id)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        task_id = str(event.row_key.value)
        tasks = {t.id: t for t in self.queue.all()}
        if task_id in tasks:
            self.query_one("#task-description", Static).update(
                tasks[task_id].description or "(no description)"
            )

    def action_add_task(self) -> None:
        # Показать простой диалог ввода
        self.app.push_screen(_AddTaskDialog(on_confirm=self._on_add_confirm))

    def _on_add_confirm(self, title: str, description: str) -> None:
        self.queue.add(title, description, priority='now')
        self._refresh_table()

    def action_delete_task(self) -> None:
        table = self.query_one("#task-table", DataTable)
        if table.cursor_row is not None:
            row_key = table.get_row_at(table.cursor_row)
            task_id = str(table.cursor_row_key.value)
            self.queue.delete(task_id)
            self._refresh_table()

    def action_move_up(self) -> None:
        table = self.query_one("#task-table", DataTable)
        if table.cursor_row_key:
            self.queue.move_up(str(table.cursor_row_key.value))
            self._refresh_table()

    def action_move_down(self) -> None:
        table = self.query_one("#task-table", DataTable)
        if table.cursor_row_key:
            self.queue.move_down(str(table.cursor_row_key.value))
            self._refresh_table()

    def action_toggle_priority(self) -> None:
        table = self.query_one("#task-table", DataTable)
        if table.cursor_row_key:
            self.queue.toggle_priority(str(table.cursor_row_key.value))
            self._refresh_table()

    def action_start_task(self) -> None:
        table = self.query_one("#task-table", DataTable)
        if table.cursor_row_key:
            task_id = str(table.cursor_row_key.value)
            tasks = {t.id: t for t in self.queue.all()}
            if task_id in tasks and self.on_start:
                self.queue.set_status(task_id, 'in_progress')
                self.on_start(tasks[task_id])
                self.dismiss()
```

---

## TASK-3.7 — AgentStatusBar (виджет)

```python
from textual.reactive import reactive
from textual.widget import Widget
from textual.app import RenderResult


class AgentStatusBar(Widget):
    """
    Строка состояния для любого Textual Screen.
    Подключать через compose(): yield AgentStatusBar(id="status-bar")

    ● Busy  │  Executing: "Fix streaming"  │  Plan: 3/7  │  feat/fix  │  247 chunks  │  4.2k/8k tokens
    ○ Idle  │  Last: "Fix streaming" (done)│  ─────────  │  main       │  247 chunks  │  0.8k/8k tokens
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
        status = f"Executing: {self.current_task!r}" if self.is_busy else f"Idle"
        plan = self.plan_progress or "─"
        tokens = f"{self.tokens_used/1000:.1f}k/{self.tokens_limit/1000:.0f}k tokens"
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
```

---

## CLI Integration Notes

> В `cli.py` в методе `compose()`:
> ```python
> from .queue import TaskQueue, QueueScreen
> from .queue import AgentStatusBar
>
> def compose(self) -> ComposeResult:
>     yield Header()
>     with TabbedContent():
>         yield TabPane("Chat", id="tab-chat")
>         yield TabPane("Plans", id="tab-plans")
>         yield TabPane("Queue", id="tab-queue")   # ← новый таб
>         yield TabPane("Config", id="tab-config")
>     yield AgentStatusBar(id="status-bar")        # ← новый виджет
>     yield Footer()
> ```
>
> При переходе на Queue таб: `self.app.push_screen(QueueScreen(queue=self.task_queue, on_start=self._start_from_queue))`.
>
> Обновление статусбара: `self.query_one(AgentStatusBar).update_status(busy=True, task="Fix streaming", plan_step=2, plan_total=7)`.
>
> Auto pick-up после завершения задачи executor'ом:
> ```python
> next_task = self.task_queue.next_pending()
> if next_task:
>     self._start_from_queue(next_task)
> ```
