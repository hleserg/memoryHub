# AGENT-6 — Backend: git safety, memory, web, notifications, search history

## Контекст

Все файлы уже существуют — только добавлять/изменять, не переписывать:
- `git.py` — `BranchGuard` и `PRManager` уже есть, добавить `BranchGuardError` + guard на push
- `web.py` — playwright есть но только явный, добавить авто-детект
- `memory.py` — добавить `SessionSummary` + `SessionSummaryStore`
- `context_manager.py` — добавить `generate_session_summary()`
- `search.py` — добавить `SearchHistory`
- `sync.py` — не существует, если нужен — создать минимальный файл для `SyncNotifier`

---

## TASK-3.1 — git safety net: BranchGuardError + push guard

**В `git.py` — добавить** (перед классом `BranchGuard`):

```python
class BranchGuardError(Exception):
    pass
```

**Добавить метод в `BranchGuard`:**

```python
class BranchGuard:
    # ... существующий код без изменений ...

    def safe_push(self, branch: str | None = None, remote: str = 'origin') -> tuple[bool, str]:
        """
        Пуш с проверкой защищённой ветки.
        Raises BranchGuardError если попытка пушить в main/master.
        """
        branch = branch or current_branch(self.repo)
        if branch in (self.cfg.main_branch, 'master', 'main'):
            raise BranchGuardError(
                f"Direct push to '{branch}' is forbidden. "
                "Create a PR: BranchGuard.safe_push() blocked."
            )
        return push_branch(branch, self.repo)
```

`check_and_prepare()` уже гарантирует работу на feature branch. Достаточно добавить `safe_push` и использовать его в cli.py вместо прямого `push_branch`.

**CLI Integration Notes (для AGENT-7):**
> При `/push` → `guard.safe_push()` → если `BranchGuardError` → показать в чате предупреждение.
> Системный промпт агента (добавить в константу `SYSTEM_CODER` в providers.py):
> `"You MUST NOT commit or push directly to main. Always use a feature branch and create a PR."`

---

## TASK-4.1 — Structured session summaries

### В memory.py — добавить в конец файла:

```python
import json as _json
from datetime import datetime as _datetime
from typing import Literal as _Literal

SUMMARIES_PATH = Path.home() / '.atman' / 'agent_memory' / 'session_summaries.jsonl'


@dataclass
class SessionSummary:
    session_id: str
    started_at: str         # ISO datetime
    ended_at: str           # ISO datetime
    task_description: str
    files_changed: list[str]
    decisions_made: list[str]
    open_questions: list[str]
    next_suggested_step: str
    outcome: str            # 'completed' | 'blocked' | 'abandoned'


class SessionSummaryStore:
    def __init__(self, path: Path = SUMMARIES_PATH):
        self.path = path

    def save(self, summary: SessionSummary) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        from dataclasses import asdict
        with self.path.open('a', encoding='utf-8') as f:
            f.write(_json.dumps(asdict(summary)) + '\n')

    def load_last(self, n: int = 1) -> list[SessionSummary]:
        if not self.path.exists():
            return []
        lines = [l for l in self.path.read_text().splitlines() if l.strip()]
        return [SessionSummary(**_json.loads(l)) for l in lines[-n:]]

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
        return '\n'.join(lines)
```

Убедиться что `Path` и `dataclass`/`field` уже импортированы в начале файла (они есть).

### В context_manager.py — добавить метод:

```python
async def generate_session_summary(
    self,
    session_id: str,
    started_at,  # datetime
    message_history: list[dict],
    router,      # ProviderRouter
    outcome: str = 'completed',
) -> 'SessionSummary':
    from .memory import SessionSummary
    from datetime import datetime

    history_text = '\n'.join(
        f"{m['role']}: {m.get('content', '')[:300]}"
        for m in message_history[-30:]
    )
    prompt = f"""Analyze this conversation and extract a structured summary.

Conversation:
{history_text}

Return JSON with these exact fields:
- task_description: one sentence what was being worked on
- files_changed: list of file paths mentioned as changed
- decisions_made: list of key decisions made (max 5)
- open_questions: list of unresolved questions (max 3)
- next_suggested_step: one sentence what to do next

Return only valid JSON, no markdown."""

    import json, re
    raw = router.analyze(prompt)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        data = json.loads(match.group()) if match else {}

    return SessionSummary(
        session_id=session_id,
        started_at=started_at.isoformat() if hasattr(started_at, 'isoformat') else str(started_at),
        ended_at=datetime.utcnow().isoformat(),
        task_description=data.get('task_description', ''),
        files_changed=data.get('files_changed', []),
        decisions_made=data.get('decisions_made', []),
        open_questions=data.get('open_questions', []),
        next_suggested_step=data.get('next_suggested_step', ''),
        outcome=outcome,
    )
```

**CLI Integration Notes (для AGENT-7):**
> При `/quit`:
> ```python
> summary = await ctx_manager.generate_session_summary(
>     session_id, session_start, message_history, router, 'completed'
> )
> SessionSummaryStore().save(summary)
> ```
> При старте: загрузить последнюю summary → вставить `format_for_prompt()` в system prompt.

---

## TASK-4.5 — Playwright автодетект в web.py

**Изменить `fetch_url()`** — добавить авто-триггер playwright при коротком контенте:

```python
import shutil

# Добавить в модуль (рядом с константами):
_PLAYWRIGHT_AVAILABLE = bool(
    shutil.which('chromium') or
    shutil.which('chromium-browser') or
    shutil.which('chromium-browser-stable')
)

# Изменить fetch_url():
def fetch_url(url: str, use_playwright: bool = False) -> FetchedPage:
    if use_playwright:
        return _fetch_playwright(url)

    page = _fetch_trafilatura(url)
    if page.ok and len(page.content) >= 200:
        return page

    # Fallback: requests
    page2 = _fetch_requests_fallback(url)
    if page2.ok and len(page2.content) >= 200:
        return page2

    # Auto-playwright если контент слишком короткий
    if _PLAYWRIGHT_AVAILABLE and len(page2.content) < 200:
        pw_page = _fetch_playwright(url)
        if pw_page.ok:
            return pw_page

    return page2 if page2.ok else page
```

---

## TASK-4.7 — Нотификации

Если `sync.py` не существует — создать. Если существует — добавить в конец:

```python
def notify(title: str, message: str, timeout: int = 5) -> None:
    """Desktop-уведомление через plyer. Молча игнорирует если недоступно."""
    try:
        from plyer import notification
        notification.notify(title=title, message=message, timeout=timeout)
    except Exception:
        pass


class SyncNotifier:
    def on_pr_merged(self, pr_title: str, pr_number: int) -> None:
        notify("Atman Agent — PR Merged", f"PR #{pr_number}: {pr_title}")

    def on_ci_failed(self, pr_number: int, failed_check: str) -> None:
        notify("Atman Agent — CI Failed", f"PR #{pr_number}: {failed_check} failed")

    def on_telegram_message(self, from_user: str, preview: str) -> None:
        notify(f"Atman — Message from {from_user}", preview[:100])

    def on_executor_done(self, task_title: str) -> None:
        notify("Atman Agent — Task Done", f"Completed: {task_title}")
```

---

## TASK-4.8 — История поиска

**В `search.py` — добавить в конец файла:**

```python
from dataclasses import dataclass as _dataclass, asdict as _asdict
import json as _json
from datetime import datetime as _datetime
from pathlib import Path as _Path

SEARCH_HISTORY_PATH = _Path.home() / '.atman' / 'agent_memory' / 'search_history.jsonl'


@_dataclass
class SearchHistoryEntry:
    query: str
    timestamp: str      # ISO
    results_count: int
    session_id: str


class SearchHistory:
    def __init__(self, path=SEARCH_HISTORY_PATH):
        self.path = _Path(path)

    def record(self, query: str, results_count: int, session_id: str = '') -> None:
        entry = SearchHistoryEntry(
            query=query,
            timestamp=_datetime.utcnow().isoformat(),
            results_count=results_count,
            session_id=session_id,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('a', encoding='utf-8') as f:
            f.write(_json.dumps(_asdict(entry)) + '\n')

    def load_recent(self, n: int = 10) -> list[SearchHistoryEntry]:
        if not self.path.exists():
            return []
        lines = [l for l in self.path.read_text().splitlines() if l.strip()]
        return [SearchHistoryEntry(**_json.loads(l)) for l in lines[-n:]]

    def format_list(self, entries: list[SearchHistoryEntry]) -> str:
        if not entries:
            return "(no search history)"
        lines = ["Recent searches:"]
        for i, e in enumerate(entries, 1):
            date = e.timestamp[:10]
            lines.append(f"  {i}. [{date}] {e.query} ({e.results_count} results)")
        return '\n'.join(lines)
```

**CLI Integration Notes (для AGENT-7):**
> `/search` без аргументов → `SearchHistory().format_list(SearchHistory().load_recent(10))` → показать в чате.
> При каждом поиске → `SearchHistory().record(query, len(results), session_id)`.
