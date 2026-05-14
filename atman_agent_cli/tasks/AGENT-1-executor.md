# AGENT-1 — Executor: streaming + interrupt + unblock

## Контекст

Файл уже написан: `atman_agent_cli/src/atman/agent_cli/executor.py` (~397 строк).
Класс `PlanExecutor` существует, метод `stop()` есть (устанавливает `self._stop = True`).

**Только добавить/изменить — не переписывать файл:**

---

## TASK-1.2 — Починить streaming (Textual RichLog)

**Проблема:** `stop()` использует `self._stop = False` (plain bool), `@work` не указан как `thread=True`.

**Изменить в `PlanExecutor.__init__`:** `output` параметр уже есть — убедиться что он принимается как `stream_callback` с `markup=False` режимом. Добавить явный `markup: bool = False` параметр к колбеку.

**CLI Integration Notes (для AGENT-7):**
> В `cli.py` воркер должен быть объявлен `@work(thread=True)`.
> Callback для стриминга: `app.call_from_thread(self.query_one(RichLog).write, chunk, markup=False)`.
> Между чанками: `await asyncio.sleep(0)` в async обёртке.

---

## TASK-1.3 — Interrupt/cancel

**Изменить `PlanExecutor`:** заменить `self._stop = False` на `threading.Event`:

```python
import threading

class ExecutorInterrupted(Exception):
    def __init__(self, step_index: int):
        self.step_index = step_index
        super().__init__(f"Executor interrupted at step {step_index}")


class PlanExecutor:
    def __init__(self, plan, router, rag, memory, output=_noop):
        # ... существующий код ...
        self._stop_event = threading.Event()   # заменяет self._stop = False

    def stop(self) -> None:
        self._stop_event.set()

    def reset_stop(self) -> None:
        self._stop_event.clear()

    def _should_stop(self) -> bool:
        return self._stop_event.is_set()
```

**Изменить `run()`:** заменить `while not self._stop` на `while not self._should_stop()`.

**Изменить `_execute_step()`:** добавить проверку в начало каждой фазы:
```python
if self._should_stop():
    self.reset_stop()
    raise ExecutorInterrupted(idx)
```

Прогресс (выполненные шаги) остаётся в `plan` — resume с нужного места через `plan.next_pending_index()`.

**CLI Integration Notes (для AGENT-7):**
> Binding: `Binding("ctrl+c", "interrupt_executor", "Stop")`.
> `action_interrupt_executor`: `self.executor.stop()`.
> В чате: `"⏹ Stopped at step N. Resume with /resume."`.

---

## TASK-4.4 — Умное восстановление из blocked

**Добавить в `PlanExecutor`** (после существующего `_reassess_blocked`):

```python
from enum import Enum

class RecoveryAction(Enum):
    MISSING_DEPENDENCY = "missing_dependency"
    AMBIGUOUS_REQUIREMENT = "ambiguous_requirement"
    EXTERNAL_UNAVAILABLE = "external_service_unavailable"
    INSUFFICIENT_CONTEXT = "insufficient_context"
    UNKNOWN = "unknown"


BLOCK_ANALYSIS_PROMPT = """Analyze why this plan step is blocked and categorize the reason.

Step: {step}
Blocked reason: {reason}
Recent context:
{recent}

Return JSON only:
{{"category": "missing_dependency|ambiguous_requirement|external_service_unavailable|insufficient_context|unknown",
  "detail": "specific explanation",
  "suggestion": "what to do next"}}"""


class PlanExecutor:
    # ... добавить метод ...

    def _handle_blocked(self, idx: int, reason: str) -> str:
        """Analyse block reason, return human-readable recovery message."""
        step = self.plan.steps[idx]
        # Recent output from last N steps
        recent_lines = []
        for i in range(max(0, idx - 3), idx):
            if self.plan.get_state(i) == STEP_DONE:
                recent_lines.append(f"{i+1}. {self.plan.steps[i]}: {self.plan.get_notes(i) or ''}")
        recent = "\n".join(recent_lines) or "(none)"

        prompt = BLOCK_ANALYSIS_PROMPT.format(step=step, reason=reason, recent=recent)
        raw = self.router.analyze(prompt)
        data = _parse_json(raw)

        category = data.get("category", "unknown")
        detail = data.get("detail", reason)
        suggestion = data.get("suggestion", "")

        messages = {
            "missing_dependency": f"Missing: {detail}. Suggest: {suggestion}",
            "ambiguous_requirement": f"Need clarification: {detail}",
            "external_service_unavailable": f"Service unavailable: {detail}. Check connection.",
            "insufficient_context": f"Need more context: {detail}. Try /ask or provide details.",
            "unknown": f"Blocked: {detail}",
        }
        return "⚠ " + messages.get(category, f"Blocked: {detail}")
```

**Интегрировать в `_execute_step`:** в месте где шаг маркируется blocked после failed assessment — вызвать `_handle_blocked` и передать результат в `stream_callback`:
```python
recovery_msg = self._handle_blocked(idx, reason)
self.out(f"  [yellow]{recovery_msg}[/yellow]")
```
