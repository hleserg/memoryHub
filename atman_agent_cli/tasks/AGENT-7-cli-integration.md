# AGENT-7 — CLI Integration

## Контекст

Файл `cli.py` (~2249 строк) уже написан. `AtmanApp` работает, большинство команд есть.

**Запускать ПОСЛЕДНИМ — после AGENT-1 через AGENT-6 завершили свои файлы.**

**Только добавить/изменить в `cli.py` — не переписывать файл целиком.**

Импорты уже есть: `BranchGuard`, `PRManager`, `commit_all`, `PlanExecutor`, `auto_plan`, `RAGIndex`, `ProviderRouter`, `extract_urls`, `fetch_github_raw`, `search`.

---

## TASK-1.1 — Команда `/commit`

В `_handle_slash` dispatch добавить `"/commit": self._cmd_commit`.

**Добавить метод:**

```python
def _cmd_commit(self, args: str) -> None:
    """/commit [message] — show diff preview and commit with confirmation."""
    self._commit_worker(args.strip())

@work(thread=True, exclusive=False)
def _commit_worker(self, message: str) -> None:
    try:
        # Show staged diff stat
        _, stat, _ = run_git(["diff", "--staged", "--stat"], self.cfg.repo_path)
        _, unstaged, _ = run_git(["status", "--porcelain"], self.cfg.repo_path)

        if not stat.strip() and not unstaged.strip():
            self.call_from_thread(self._chat_write, "[dim]Nothing to commit[/dim]")
            return

        if unstaged.strip() and not stat.strip():
            # Stage everything first
            run_git(["add", "-A"], self.cfg.repo_path)
            _, stat, _ = run_git(["diff", "--staged", "--stat"], self.cfg.repo_path)

        self.call_from_thread(
            self._chat_write,
            f"\n[bold]Staged changes:[/bold]\n```\n{stat}\n```"
        )

        # Enforce branch safety
        from .git import BranchGuardError
        try:
            self.branch_guard.safe_push.__func__  # just check the method exists
        except AttributeError:
            pass

        branch = current_branch(self.cfg.repo_path)
        if branch in ('main', 'master', self.cfg.main_branch):
            # BranchGuard creates feature branch automatically
            branch, msgs = self.branch_guard.check_and_prepare(
                message or "agent-changes"
            )
            for m in msgs:
                self.call_from_thread(self._chat_write, f"[dim]{m}[/dim]")

        # Use provided message or generate one
        if not message:
            prompt = (
                f"Write a concise git commit message (one line) for these changes:\n{stat}\n"
                "Follow conventional commits: feat/fix/refactor/chore/docs: <description>"
            )
            message = self.router.analyze(prompt).strip().split('\n')[0]
            self.call_from_thread(self._chat_write, f"[dim]Message: {message}[/dim]")

        ok, out = commit_all(message, self.cfg.repo_path)
        if ok:
            self.call_from_thread(
                self._chat_write,
                f"[green]✓ Committed:[/green] {message}"
            )
        else:
            self.call_from_thread(self._chat_write, f"[red]Commit failed:[/red] {out}")

    except Exception as e:
        self.call_from_thread(self._chat_write, f"[red]Commit error: {e}[/red]")
```

Также добавить `/commit` в `/help` и в `BINDINGS` если нужно.

---

## TASK-1.2 — Fix streaming (call_from_thread + markup=False)

В `_run_executor()` (строка ~1894) — исправить `output` callback:

```python
def _run_executor(self, plan: Plan) -> None:
    def output(text: str, markup: bool = True) -> None:
        if markup:
            self.call_from_thread(self._chat_write, text)
        else:
            # Streaming chunk: write без markup через RichLog напрямую
            self.call_from_thread(
                self.query_one(ChatPane).write_chunk, text
            )
        if "✅" in text or "🚫" in text or "↩" in text:
            self.call_from_thread(self._refresh_sidebar)
    # ... остальное без изменений
```

`ChatPane.write_chunk()` уже существует (строка ~254) — использует `RichLog.write(chunk, markup=False)`.

---

## TASK-1.3 — Interrupt binding Ctrl+C

**Добавить в `BINDINGS`:**
```python
Binding("ctrl+c", "interrupt_executor", "Stop", show=False),
```

**Добавить action:**
```python
def action_interrupt_executor(self) -> None:
    if self._current_executor:
        self._current_executor.stop()
        self._chat_write("[yellow]⏹ Interrupting... (will stop at next step)[/yellow]")
    else:
        self._chat_write("[dim]No executor running[/dim]")
```

---

## TASK-1.5 — Plan tab: клик по плану → выполнить

В `PlansTab` (строка ~265) — добавить обработчик клика по плану в DataTable:

```python
class PlansTab(Widget):
    # ... существующий код ...

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        plan_id = str(event.row_key.value)
        plans = self.app.memory.list_plans()
        selected = next((p for p in plans if p.id == plan_id), None)
        if selected:
            self.app.current_plan = selected
            done, total = selected.progress
            self.app.query_one(ChatPane).write(
                f"\n[bold]Plan selected:[/bold] {selected.task}\n"
                f"  Progress: {done}/{total}\n"
                f"[dim]Press Ctrl+A and send any message to execute[/dim]"
            )
```

---

## TASK-1.6 — RAG search_fusion в plan mode

В `_plan_discuss_worker` (строка ~1927) — заменить `rag.search` на `search_fusion` если planner available:

```python
# Было:
context = self.rag.format_context(self.rag.search(message)) \
          if self.rag.stats["chunks"] else ""

# Стало:
if self.rag.stats["chunks"]:
    if hasattr(self.rag, 'search_fusion') and self.rag.planner:
        chunks = self.rag.search_fusion(message)
    else:
        chunks = self.rag.search(message)
    context = self.rag.format_context(chunks)
else:
    context = ""
```

Также в `on_mount()` при инициализации — передать `planner=self.router` в `RAGIndex` если он принимает этот параметр:
```python
self.rag = RAGIndex(cfg, planner=self.router)
```

---

## TASK-3.4 — GitHub Issue → автоматический приём в работу

В `_fetch_urls_worker` (строка ~1780) — после успешного fetch GitHub issue URL добавить предложение:

```python
# Внутри _fetch_urls_worker, после обработки страниц:
for page in pages:
    if page.ok and 'github.com' in page.url and '/issues/' in page.url:
        # Предложить взять в работу
        self.call_from_thread(
            self._chat_write,
            f"\n[dim]GitHub issue loaded. Take as task? Type [bold]/task[/bold] to start.[/dim]"
        )
        self._pending_issue_url = page.url
        self._pending_issue_content = page.content
        break
```

**Добавить команду `/task`** в dispatch:
```python
"/task": self._cmd_take_issue,
```

```python
def _cmd_take_issue(self, _: str) -> None:
    """Take pending GitHub issue as current task."""
    if not hasattr(self, '_pending_issue_content') or not self._pending_issue_content:
        self._chat_write("[dim]No pending issue. Send a GitHub issue URL first.[/dim]")
        return
    # Создать план из issue
    content = self._pending_issue_content
    # Проверить наличие чеклиста [ ] в issue
    import re
    checkboxes = re.findall(r'- \[ \] (.+)', content)
    if checkboxes:
        steps = checkboxes
        task = content.split('\n')[0][:100]
    else:
        task = content.split('\n')[0][:100]
        steps = []

    self.current_plan = self.memory.create_plan(
        task=task, steps=steps,
        discussion=[{"role": "user", "content": content}],
    )
    self._chat_write(f"[green]✓ Issue taken as task:[/green] {task}")
    if steps:
        for i, s in enumerate(steps, 1):
            self._chat_write(f"  {i}. {s}")
    self._refresh_sidebar()
    self._pending_issue_content = ""
```

---

## TASK-4.2 — Diff preview в /commit

Уже учтено в TASK-1.1 — `_commit_worker` показывает `git diff --staged --stat` перед коммитом.

**Расширить** — добавить возможность развернуть полный diff:
```python
# В _cmd_commit — добавить подкоманду:
# /commit diff → показать полный diff
# /commit → стандартный коммит с stat

def _cmd_commit(self, args: str) -> None:
    if args.strip() == 'diff':
        diff = get_diff(self.cfg.repo_path)
        self._chat_write(f"```diff\n{diff[:5000]}\n```")
        return
    self._commit_worker(args.strip())
```

---

## TASK-4.3 — `/ask` команда

**Добавить в dispatch:** `"/ask": self._cmd_ask`

```python
def _cmd_ask(self, args: str) -> None:
    """/ask <question> — read-only RAG query, no mode switch."""
    if not args.strip():
        self._chat_write("[dim]Usage: /ask <question about the codebase>[/dim]")
        return
    self._ask_worker(args.strip())

@work(thread=True, exclusive=False)
def _ask_worker(self, question: str) -> None:
    try:
        if not self.rag.stats["chunks"]:
            self.call_from_thread(
                self._chat_write, "[dim]RAG index empty. Run /index first.[/dim]"
            )
            return

        self.call_from_thread(
            self._chat_write, f"\n[bold cyan]◆ Searching codebase for:[/bold cyan] {question}"
        )

        if hasattr(self.rag, 'search_fusion') and self.rag.planner:
            chunks = self.rag.search_fusion(question)
        else:
            chunks = self.rag.search(question)

        context = self.rag.format_context(chunks)
        prompt = f"Answer this question about the codebase based on the context:\n\n{question}"
        text, citations = self.router.plan_with_documents(question, chunks) \
            if hasattr(self.router, 'plan_with_documents') \
            else (self.router.analyze(f"{context}\n\n{prompt}"), [])

        self.call_from_thread(self._chat_write, text)

        if citations:
            sources = ", ".join(f"{c['source']}" for c in citations[:5])
            self.call_from_thread(self._chat_write, f"\n[dim]📎 Sources: {sources}[/dim]")

    except Exception as e:
        self.call_from_thread(self._chat_write, f"[red]Ask error: {e}[/red]")
```

Добавить `/ask` в `_cmd_help`.

---

## TASK-4.6 — `/export` план в epic-формат

**Добавить в dispatch:** `"/export": self._cmd_export`

```python
def _cmd_export(self, args: str) -> None:
    """/export [epic#] — export current plan as epic file."""
    if not self.current_plan or not self.current_plan.steps:
        self._chat_write("[dim]No active plan to export. Use /finalize first.[/dim]")
        return

    epic_num = args.strip() or "00"
    slug = self.current_plan.task[:30].lower().replace(' ', '_')
    slug = ''.join(c for c in slug if c.isalnum() or c == '_')
    filename = f"E{epic_num}_{slug}.md"
    output_path = self.cfg.repo_path / filename

    lines = [
        f"# E{epic_num} — {self.current_plan.task}",
        "",
        f"**Summary:** {self.current_plan.summary or self.current_plan.task}",
        "",
        "## Subtasks",
        "",
    ]
    for i, step in enumerate(self.current_plan.steps, 1):
        state = self.current_plan.get_state(i - 1)
        check = "x" if state == "done" else " "
        lines.append(f"- [{check}] {step}")

    lines += ["", "## Labels", "", "- agent", "- auto-generated"]

    output_path.write_text('\n'.join(lines), encoding='utf-8')
    self._chat_write(f"[green]✓ Exported:[/green] {filename}")
```

---

## Queue tab + AgentStatusBar (интеграция с AGENT-5)

**В `compose()`** — добавить Queue таб и статусбар (после AGENT-5 создаст `queue.py`):

```python
def compose(self) -> ComposeResult:
    from .queue import AgentStatusBar, QueueScreen, TaskQueue  # добавить импорт вверху файла
    yield Header(show_clock=True)
    with TabbedContent(id="tabs"):
        with TabPane("Chat", id="tab-chat"):
            yield ChatPane()
        with TabPane("Plans", id="tab-plans"):
            yield PlansTab()
        with TabPane("Queue", id="tab-queue"):     # ← новый таб
            yield Static("Press Q to open queue manager", id="queue-placeholder")
        with TabPane("Settings", id="tab-settings"):
            yield SettingsTab(self)
        with TabPane("Setup CI", id="tab-setup"):
            yield SetupTab(self)
        with TabPane("Changes", id="tab-changes"):
            yield ChangesTab()
    yield AgentStatusBar(id="status-bar")          # ← новый виджет
    yield Footer()
```

**В `on_mount()`** — инициализировать TaskQueue:
```python
from .queue import TaskQueue
self.task_queue = TaskQueue()
```

**Добавить binding `q`** и action:
```python
Binding("q", "open_queue", "Queue", show=True),

def action_open_queue(self) -> None:
    from .queue import QueueScreen
    self.push_screen(QueueScreen(
        queue=self.task_queue,
        on_start=self._start_from_queue,
    ))

def _start_from_queue(self, task) -> None:
    self.current_plan = self.memory.create_plan(
        task=task.title, steps=[task.description] if task.description else [],
    )
    self.action_set_mode("agent")
    self._chat_write(f"\n[green]◆ Starting from queue:[/green] {task.title}")
    self._refresh_sidebar()
```

**Обновлять AgentStatusBar** в `_run_executor()`:
```python
from .queue import AgentStatusBar  # вверху файла
# В _run_executor, после создания executor:
try:
    bar = self.query_one(AgentStatusBar)
    bar.update_status(busy=True, task=plan.task, branch=current_branch(self.cfg.repo_path))
except Exception:
    pass
# ... executor.run() ...
try:
    bar = self.query_one(AgentStatusBar)
    bar.update_status(busy=False)
except Exception:
    pass
```

---

## Telegram интеграция (AGENT-4)

**В `on_mount()`** — если `telegram.py` создан и токен задан:

```python
telegram_token = self.secrets.get('telegram_token', '')
if telegram_token:
    try:
        from .telegram import TelegramBot
        allowed_ids_raw = os.getenv('ATMAN_TELEGRAM_ALLOWED_IDS', '')
        allowed_ids = [int(x) for x in allowed_ids_raw.split(',') if x.strip().isdigit()]
        self.telegram = TelegramBot(
            token=telegram_token,
            allowed_ids=allowed_ids,
            on_message=lambda text, cid: self.call_from_thread(
                self._inject_telegram_message, text
            ),
            on_file=lambda path, mime, cid: self.call_from_thread(
                self._notify_file_received, path
            ),
        )
        import asyncio
        asyncio.create_task(self.telegram.start())
        self._chat_write("[dim]Telegram bot started[/dim]")
    except Exception as e:
        self._chat_write(f"[dim]Telegram not available: {e}[/dim]")
else:
    self.telegram = None

def _inject_telegram_message(self, text: str) -> None:
    self._chat_write(f"\n[cyan]📱 Telegram:[/cyan] {text}")
    self._handle_message(text)

def _notify_file_received(self, path) -> None:
    self._chat_write(f"\n[cyan]📎 File received:[/cyan] {path}")
```

**При `action_quit()`** — остановить Telegram:
```python
async def action_quit(self) -> None:
    if getattr(self, 'telegram', None):
        await self.telegram.stop()
    self.exit()
```

---

## Session summary при выходе (AGENT-6)

**В `action_quit()`** — генерировать и сохранять summary:
```python
async def action_quit(self) -> None:
    if self._messages and hasattr(self, '_session_start'):
        try:
            from .memory import SessionSummaryStore
            summary = await self.ctx.generate_session_summary(
                session_id=getattr(self, '_session_id', 'unknown'),
                started_at=self._session_start,
                message_history=self._messages,
                router=self.router,
                outcome='completed',
            )
            SessionSummaryStore().save(summary)
        except Exception:
            pass
    if getattr(self, 'telegram', None):
        await self.telegram.stop()
    self.exit()
```

**В `on_mount()`** — инициализировать `_session_start`:
```python
from datetime import datetime
self._session_start = datetime.utcnow()
self._session_id = str(uuid.uuid4())  # если uuid уже импортирован
```

**При старте** — загрузить предыдущую summary в system prompt:
```python
from .memory import SessionSummaryStore
last_summaries = SessionSummaryStore().load_last(1)
if last_summaries:
    prev_ctx = SessionSummaryStore().format_for_prompt(last_summaries[0])
    self._messages.insert(0, {"role": "system", "content": prev_ctx})
```

---

## /config set llm_url (AGENT-3)

В `_cmd_config` — в блоке `if subcmd == "set"`:

```python
if key == "llm_url":
    self.router.update_llm_url(value)  # метод из AGENT-3
    self._chat_write(f"[green]✓[/green] llm_url → {value}")
    return
```

---

## SearchHistory.record() (AGENT-6)

В `_search_worker` — после получения результатов:
```python
from .search import SearchHistory
SearchHistory().record(
    query=query,
    results_count=len(good_results),
    session_id=getattr(self, '_session_id', ''),
)
```

`/search` без аргументов — изменить `_cmd_search`:
```python
def _cmd_search(self, args: str) -> None:
    if not args.strip():
        from .search import SearchHistory
        history = SearchHistory().load_recent(10)
        self._chat_write(SearchHistory().format_list(history))
        self._chat_write("[dim]/search <query> — new search[/dim]")
        return
    self._search_worker(args.strip())
```

---

## /help — обновить

Добавить в `_cmd_help` новые команды:
```
  /commit [message]    — show diff and commit
  /ask <question>      — query codebase (read-only)
  /task                — take pending GitHub issue as task
  /export [epic#]      — export plan as epic file
  /search              — show search history (no args)
  q                    — open task queue
```
