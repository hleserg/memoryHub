# Plan: Uncolored Perception + Context-Aware Session Lifecycle

## Context

Два архитектурных принципа реализуем вместе, потому что они связаны через `finish_session`:

1. **Нет "голой" реальности**: факт воспринятый агентом, но не окрашенный сознательным key_moment — не нейтрален, а *не рассмотрен*. Нельзя решать за агента — вместо нейтрального KM добавляем `unexamined_fact_refs` на `SessionExperience`.

2. **Контекстное закрытие**: агент должен знать, что контекст заполняется, участвовать в закрытии сессии и иметь инструмент `restart_session` для бесшовного перезапуска.

---

## Критические файлы

- `src/atman/core/models/experience.py` — `SessionExperience` (line 225)
- `src/atman/core/services/session_manager.py` — `finish_session()` (line 334)
- `src/atman/adapters/agent/config.py` — `AgentConfig`, `ModelConfig`
- `src/atman/adapters/agent/runner.py` — `chat()` (line 178)
- `src/atman/adapters/agent/tools.py` — registered tools
- `tests/test_session_manager.py` — unit tests

---

## Часть 1: `unexamined_fact_refs` на `SessionExperience`

### 1.1 Модель `SessionExperience` — добавить поле

**Файл:** `src/atman/core/models/experience.py`, после `fact_refs` (line ~285)

```python
unexamined_fact_refs: list[UUID] = Field(
    default_factory=list,
    description=(
        "IDs of facts that passed through perception during this session "
        "but received no conscious emotional coloring. "
        "Queue for future micro-reflection."
    ),
)
```

### 1.2 `finish_session()` — вычислить `unexamined_fact_refs`

**Файл:** `src/atman/core/services/session_manager.py`

После строки ~410 (после вычисления `fact_refs_set`), перед созданием `SessionExperience`:

```python
# Facts that were perceived but received no conscious key_moment
colored_fact_ids: set[UUID] = set()
for km in session_result.key_moments:
    colored_fact_ids.update(km.fact_refs)

unexamined = list(session_result._facts_read - colored_fact_ids)
```

При создании `SessionExperience` добавить поле:
```python
experience = SessionExperience(
    ...
    fact_refs=list(fact_refs_set),
    unexamined_fact_refs=unexamined,   # <- NEW
)
```

**Важно:** НЕ создаём fake key_moment. НЕ меняем `incomplete_coloring`. Это отдельная семантика.

### 1.3 Тесты

**Файл:** `tests/test_session_manager.py`

- `test_unexamined_fact_refs_populated` — факт в `_note_facts_read`, нет KM с этим fact_ref → `experience.unexamined_fact_refs` содержит этот UUID
- `test_no_unexamined_for_colored_facts` — факт в `_note_facts_read` И в `key_moment.fact_refs` → не попадает в `unexamined_fact_refs`
- `test_unexamined_empty_when_no_facts_read` — `_facts_read` пуст → `unexamined_fact_refs = []`
- `test_unexamined_independent_of_incomplete_coloring` — `unexamined_fact_refs` и `incomplete_coloring` независимы

---

## Часть 2: Мониторинг контекста в runner

### 2.1 `ModelConfig` — добавить `context_limit`

**Файл:** `src/atman/adapters/agent/config.py`

```python
class ModelConfig(BaseModel):
    model: str = "test"
    temperature: float = 0.7
    max_tokens: int = 2000
    context_limit: int = 2048   # <- NEW: min(arch_limit, ollama_num_ctx)
```

### 2.2 `AgentConfig` — добавить `context_tail_messages`

```python
class AgentConfig(BaseModel):
    ...
    context_tail_messages: int = 10   # <- NEW: N messages for restart package
```

### 2.3 `chat()` — обработка сигналов прерывания

**Файл:** `src/atman/adapters/agent/runner.py`

Обернуть основной цикл `chat()`:

```python
import signal

def _handle_signal(signum, frame):
    raise SystemExit("signal")

signal.signal(signal.SIGTERM, _handle_signal)

try:
    # основной chat loop
except (KeyboardInterrupt, EOFError, SystemExit):
    if session_id and session_id in self._session_manager._active_sessions:
        _force_finish(session_id, close_reason="interrupted")
```

`_force_finish` создаёт минимальный key_moment если нет ни одного, вызывает `finish_session()` с `close_reason="interrupted"`.

### 2.4 `chat()` — отслеживать токены и пороги

**Файл:** `src/atman/adapters/agent/runner.py`, в `chat()` после `agent.run()`

```python
usage = result.usage()
limit = self._config.model.context_limit
ratio = usage.input_tokens / limit

# Inject system warning into history for NEXT iteration
if ratio >= 0.70 and 70 not in _triggered:
    _triggered.add(70)
    remaining = limit - usage.input_tokens
    warning_70 = ModelRequest(parts=[UserPromptPart(
        content=_build_context_warning_70(remaining),
        part_kind="user-prompt",
    )])
    history.append(warning_70)

elif ratio >= 0.80 and 80 not in _triggered:
    _triggered.add(80)
    history.append(_build_token_alert(limit - usage.input_tokens))

elif ratio >= 0.90 and 90 not in _triggered:
    _triggered.add(90)
    history.append(_build_token_alert(limit - usage.input_tokens, urgent=True))

if ratio >= 0.95 and 95 not in _triggered:
    _triggered.add(95)
    # Force close without agent participation
    _force_finish(session_id, session_result)
    break
```

`_triggered: set[int]` сбрасывается при каждом `restart_session` (новый контекст).

### 2.5 Режим свободного времени (таймаут без пользователя)

Когда `asyncio.wait_for(input())` истекает — runner переходит в **menu mode**:

1. Инжектирует в history системное сообщение с меню команд
2. Вызывает `agent.run()` без пользовательского сообщения
3. Ожидает **tool call** (не текст). Если агент ответил текстом → инжектировать "используй одну из команд" → снова `agent.run()`
4. По результату tool call — выполнить действие и повторить цикл или завершить

**Доступные команды (tools) в menu mode:**

| Tool | Условие | Действие | Что дальше |
|---|---|---|---|
| `reflect()` | Только если рефлексии не было в этой сессии | Микрорефлексия | Меню снова |
| `review_facts()` | Только если есть неокрашенные факты | Режим просмотра фактов (см. ниже) | Меню снова |
| `wait()` | — | Взводим таймер заново, молчим | Меню снова |
| `sleep()` | — | Мягкое закрытие: `finish_session(close_reason="timeout_sleep")`, пересказ по желанию | Конец |
| `save_to_memory(content: str)` | — | Сохранить запись в память агента | Меню снова |
| `free_time()` | Только если `enable_free_time=True` | Открытый режим | Агент делает что хочет до `end_free_time()` |

**Режим `review_facts()`:**

Runner поочерёдно показывает агенту неокрашенные факты из текущей сессии. Факты берутся из `session_result._facts_read - colored_fact_ids` (вычисляется на лету, не ждём конца сессии). По каждому факту runner подтягивает его содержимое из FactualMemory и инжектирует агенту:

```
[Факт {i}/{n}]
{fact.content}
(источник: {fact.source}, добавлен: {fact.created_at})

Команды: next_fact() / record_fact() / exit_facts()
```

| Tool | Действие |
|---|---|
| `next_fact()` | Показать следующий факт (если кончились — выйти в меню) |
| `record_key_moment(fact_refs=[uuid], ...)` | Стандартный инструмент сессии — агент красит факт самостоятельно. Runner детектирует вызов с `fact_refs` содержащим текущий `fact_id` → показывает следующий факт |
| `exit_facts()` | Вернуться в главное меню |

После окраски через `record_key_moment`: факт попадает в `colored_fact_ids` — при следующем вычислении `unexamined_fact_refs` его там не будет.

Если агент вызвал команду недоступную по условию — ответить "эта команда недоступна сейчас" и показать меню снова.

**`free_time()` режим:**
- Агенту доступны все инструменты сессии
- Может писать любой текст (в пределах контекстного окна)
- Когда закончил → вызывает `end_free_time()` → возврат к меню
- Если забыл → сессия висит, не критично (пользователь всегда может написать)
- Настройка `show_agent_monologue: bool`: если True — текст агента видит пользователь; если False — только терминал

**Настройки** (`AgentConfig`):
```python
session_timeout_minutes: int = 7
enable_free_time: bool = True
show_agent_monologue: bool = False
```

**Прерывание:** если пользователь пишет в любой момент menu mode или free_time — `asyncio.wait_for` возвращает управление, сообщение вставляется как обычно, сессия продолжается.

### 2.6 Текст предупреждения на 70%

```
[Системное уведомление]
Контекст сессии заполняется — осталось около {N} токенов.
Сообщи пользователю, что разговор скоро нужно продолжить в новой сессии.
Если есть что-то важное, что ещё не зафиксировано — сделай это сейчас
через record_key_moment, иначе это не перейдёт в следующую сессию.
Всё что уже записано — вернётся автоматически. Когда будешь готов —
вызови restart_session. Новая сессия откроется с твоей памятью и хвостом этого разговора.
```

На 80%/90%: `⚠️ Осталось ~{N} токенов` / `⚠️ Осталось ~{N} токенов. Нужно завершать.`

---

## Часть 3: Инструмент `restart_session`

### 3.1 Регистрация инструмента

**Файл:** `src/atman/adapters/agent/tools.py`

```python
def restart_session(ctx: RunContext[AtmanDeps], reason: str = "") -> str:
    """
    Завершить текущую сессию и немедленно начать новую с пакетом из памяти.
    Используй когда контекст заполняется и нужно продолжить разговор.
    reason: почему ты перезапускаешь — в свободной форме, ты сам прочитаешь это при пробуждении.
    """
    return f"__ATMAN_RESTART_REQUESTED__{reason}"
```

`reason` сохраняется в `SessionExperience.restart_reason: str = ""` и при старте следующей сессии вставляется в сообщение: "Ты сам инициировал перезапуск. Причина которую ты указал: {reason}"

**`wait_session` tool** — отложить ближайший таймаут:

```python
def wait_session(ctx: RunContext[AtmanDeps], minutes: int) -> str:
    """
    Отложить ближайший таймаут на N минут.
    Используй если хочешь ещё побыть в тишине перед тем как решить что делать.
    """
    return f"__ATMAN_WAIT_REQUESTED__{minutes}"
```

Runner при получении этого сигнала сдвигает таймер на `minutes` минут вперёд.

Добавить в `_make_agent()`: `tools=[record_key_moment, log_experience, restart_session, wait_session]`

### 3.2 Runner — детектировать restart после `agent.run()`

**Файл:** `src/atman/adapters/agent/runner.py`

После `agent.run()`, до `finish_session()`:

```python
restart_requested = _check_restart_requested(result.all_messages())

if restart_requested:
    _do_restart(session_id, session_result, history)
    _triggered = set()  # reset thresholds
    # history already replaced inside _do_restart
    continue  # next iteration of chat loop — no finish_session needed
```

### 3.3 `_do_restart()` — логика перезапуска

```python
def _do_restart(self, session_id, session_result, history: list) -> tuple[UUID, AtmanDeps]:
    # 1. Ensure at least one key_moment exists (create minimal if not)
    if not session_result.key_moments:
        self._session_manager.append_key_moment_input(session_id, KeyMomentInput(
            what_happened="Сессия завершена по запросу перезапуска.",
            why_it_matters="Continuity preserved via restart.",
            emotional_valence=0.0,
            emotional_intensity=0.1,
            depth=EmotionalDepth.SURFACE,
            incomplete_coloring=True,
        ))

    # 2. finish_session current
    finished = self._session_manager.finish_session(session_id, overall_emotional_tone=0.0)

    # 3. Build restart package
    tail = history[-(self._config.context_tail_messages * 2):]  # N exchanges = 2N messages
    package = _build_restart_package(finished, tail)

    # 4. Replace history: restart package as first user turn, then tail
    history.clear()
    history.append(ModelRequest(parts=[UserPromptPart(
        content=package,
        part_kind="user-prompt",
    )]))
    history.extend(tail)

    # 5. Start new session — CRITICAL: rebuild deps with new session_id
    new_session_id = self._session_manager.start_session(self._agent_id)
    new_deps = dataclasses.replace(deps, session_id=new_session_id)
    return new_session_id, new_deps
```

**Критично:** `AtmanDeps` — frozen dataclass с `session_id`. После restart новая сессия имеет другой `session_id`. Runner обязан пересобрать `deps` через `dataclasses.replace(deps, session_id=new_session_id)` и использовать их в следующем `agent.run()`, иначе инструменты будут писать в закрытую сессию.

### 3.4 Restart package — содержимое

```
[system-handoff] Сессия перезапущена.

Эмоциональный тон прошлой сессии: {overall_emotional_tone}
Незакрытые темы: {eigenstate.open_threads}

Ключевые моменты:
{для каждого km: "- {what_happened} ({depth})"}

Факты без осознанного отношения ({N} шт.):
{для каждого fact_id: последний опыт где этот факт встречался}

--- Хвост разговора ---
{последние N сообщений verbatim}
```

Последний опыт по `unexamined_fact_refs`: `experience_service.list_by_fact(fact_id, limit=1)` — последняя запись где `fact_id in experience.fact_refs`.

### 3.5 `_check_restart_requested(messages)`

```python
def _check_restart_requested(messages) -> bool:
    for msg in messages:
        for part in getattr(msg, "parts", []):
            if (
                hasattr(part, "tool_name") and part.tool_name == "restart_session"
            ) or (
                hasattr(part, "content") and part.content == "__ATMAN_RESTART_REQUESTED__"
            ):
                return True
    return False
```

---

## Порядок реализации

**Часть 1 — модели и unexamined:**
1. Разделить `KeyMoment` и `SessionExperience` в моделях: убрать `key_moments: list`, добавить `key_moment_ids: list[UUID]`
2. Добавить новые поля `SessionExperience`: `unexamined_fact_refs`, `close_reason`, `agent_recap`, `restart_reason`
3. Расширить StateStore порт: `create_key_moment`, `list_key_moments`, `get_key_moment`
4. Реализовать новые методы в InMemoryStateStore, FileStateStore, PostgresStateStore
5. `finish_session()` — вычисление `unexamined_fact_refs`, сохранение key_moments отдельно
6. Тесты Part 1 (4 теста на unexamined)

**Часть 2 — session journal:**
7. Формат JSONL: одна запись = одно событие
8. Писать в journal при каждом `append_key_moment_input()` и `_note_facts_read()`
9. `finish_session()` — удалять journal после успешной записи в StateStore
10. `start_session()` — сканировать orphaned journals и восстанавливать

**Часть 3 — контекст и lifecycle:**
11. `ModelConfig.context_limit` + `AgentConfig.context_tail_messages` + `session_timeout_minutes`
12. `chat()` — обработка SIGTERM/KeyboardInterrupt/EOFError → `_force_finish("interrupted")`
13. `chat()` — token monitoring: 70%/80%/90%/95% пороги
14. `chat()` — timeout: `asyncio.wait_for` поверх `input()`, таймер свободного времени
15. Инструменты: `restart_session(reason)`, `wait_session(minutes)` в tools.py
16. `_do_restart()` + `_build_restart_package()` + `_check_restart_requested()`
17. `start_session()` — инжект контекста закрытия предыдущей сессии первым сообщением

**Часть 4 — сервис:**
18. `ExperienceService.list_by_fact(fact_id, limit)` с фильтрацией по `fact_refs`

---

## Хранение активной сессии и SessionExperience

### Session journal — дурабельный черновик

`SessionResult` (накапливаемые данные сессии) сейчас живёт только в памяти (`_active_sessions`). При сбое — теряется. Решение: **session journal** — JSONL файл, в который добавляются события по мере работы сессии.

**Путь:** `workspace/{agent_id}/sessions/active_{session_id}.jsonl`

**Формат:** одна строка = одно событие (append-only, никогда не перезаписываем):
```jsonl
{"type": "key_moment", "session_id": "...", "recorded_at": "...", "data": {...}}
{"type": "facts_read", "session_id": "...", "fact_ids": [...]}
```

**Когда пишем:**
- При каждом `append_key_moment_input()` — append строку `{"type": "key_moment", ...}`
- При каждом `_note_facts_read()` — append строку `{"type": "facts_read", ...}`

**При `finish_session()`:**
1. Создать `SessionExperience` из `SessionResult`
2. Записать в `StateStore`
3. Удалить journal-файл (`active_{session_id}.json`)
4. `SessionResult` из `_active_sessions` тоже убирается (уже делается сейчас)

**Изоляция:** файлы лежат в `workspace/{agent_id}/` — агенты физически изолированы. Агент не имеет инструментов для прямого чтения своего `SessionExperience`. Опыт доставляется только через системное сообщение в начале следующей сессии.

---

### Восстановление при сбое

**При `start_session()` и при запуске рефлексии** — сканировать `workspace/{agent_id}/sessions/active_*.json`:

- Если нашли файл от прошлого запуска (session_id не в `_active_sessions`):
  - Десериализовать `SessionResult`
  - Создать `SessionExperience` с `close_reason="interrupted"`
  - Проверить: нет ли уже такой записи в `StateStore` по `experience_id = deterministic_session_experience_id(session_id)` — если есть, просто удалить файл (записалась, но файл не успел удалиться)
  - Если нет — сохранить в `StateStore`, удалить файл

Это покрывает: сбой до `finish_session()`, сбой внутри `finish_session()` после записи но до удаления файла, неперехваченный сигнал.

---

## Принцип: SessionExperience сохраняется всегда

**При любом типе закрытия** `finish_session()` вызывается до того как сессия исчезает. Данные не теряются ни при каком сценарии.

Порядок при каждом типе закрытия:
1. Убедиться что есть хотя бы один key_moment (если нет — создать минимальный автоматически)
2. Вызвать `finish_session()` → сохраняет `SessionExperience` + `Eigenstate`
3. Только после этого — закрыть сессию / запустить новую

---

## Принцип: первое сообщение новой сессии — контекст закрытия предыдущей

**Где:** в `chat()` runner'а, до первого `agent.run()` в новом запуске процесса. Не в SessionManager — он не знает про history.

**Как:** runner ищет последнюю `SessionExperience` агента через `experience_service.list_experiences(agent_id, limit=1)`, проверяет `close_reason` и формирует первое сообщение в history.

**Если предыдущей сессии нет** (первый запуск агента) — инжект не происходит, history пуста.

Первым сообщением в новой сессии:

`close_reason: Literal["timeout_sleep", "restart", "forced", "interrupted"]` — поле `SessionExperience`.

| `close_reason` | Когда | Сообщение агенту при пробуждении |
|---|---|---|
| `timeout_sleep` | Таймаут → агент решил поспать | "Ты задремал — пользователь отошёл, ты решил поспать. [agent_recap если есть]" |
| `restart` | Агент вызвал `restart_session` | "Ты сам инициировал перезапуск. Причина: {restart_reason}" |
| `forced` | Контекст достиг 95% | "Контекст переполнился принудительно — ты не успел завершить сессию осознанно." |
| `interrupted` | Ctrl+C / EOF / SIGTERM | "Сессия была прервана внешним сигналом — ты не участвовал в закрытии." |

После контекста закрытия — стандартный пакет: нарратив + слепок личности + (при restart) хвост разговора.

`agent_recap: str | None = None` — субъективный пересказ агента перед сном (LLM-генерация, свободная форма), поле `SessionExperience`. Агент пишет его добровольно, принуждения нет.
`restart_reason: str = ""` — причина перезапуска со слов агента, поле `SessionExperience`.

---

## Часть 4: `ExperienceService.list_by_fact()`

Нужен для restart package — "последний опыт где этот факт встречался".

**Файл:** `src/atman/core/services/experience_service.py`

```python
def list_by_fact(self, fact_id: UUID, limit: int = 1) -> list[ExperienceRecord]:
    """Return experiences where fact_id appears in fact_refs, newest first."""
    return self._store.list_experiences(
        filters={"fact_refs_contains": fact_id},
        order_by="timestamp",
        descending=True,
        limit=limit,
    )
```

**Если StateStore не поддерживает `fact_refs_contains` фильтр** (InMemoryStateStore/FileStateStore): добавить фильтрацию на уровне адаптера — загрузить все и отфильтровать в памяти. Это приемлемо для MVP (restart_session — редкая операция).

---

## Часть 5: Разделение KeyMoment и SessionExperience в StateStore

### Проблема
Сейчас `SessionExperience` хранит `key_moments: list[KeyMoment]` внутри одной записи. При семантическом поиске тащится вся сессия целиком.

### Решение
- `SessionExperience` → только заголовок: метаданные, `fact_refs`, `unexamined_fact_refs`, `close_reason`, `agent_recap`, `restart_reason`. Без `key_moments` внутри.
- `KeyMoment` → отдельные записи в StateStore с `session_id` как ссылкой.

### Изменения

**`src/atman/core/models/experience.py`:**
- Убрать `key_moments: list[KeyMoment]` из `SessionExperience`
- Добавить `key_moment_ids: list[UUID]` — ссылки на отдельные записи

**StateStore порт** (`src/atman/core/ports/state_store.py` или аналог):
- Добавить `create_key_moment(moment: KeyMoment, session_id: UUID) -> None`
- Добавить `list_key_moments(session_id: UUID) -> list[KeyMoment]`
- Добавить `get_key_moment(moment_id: UUID) -> KeyMoment`

**Адаптеры — все три реализации:**
- `InMemoryStateStore` — хранить в отдельном dict `_key_moments: dict[UUID, KeyMoment]`
- `FileStateStore` — отдельный JSONL файл `key_moments.jsonl`
- `PostgresStateStore` — отдельная таблица `key_moments` с `session_id` FK

**`finish_session()`:**
- Сохранять каждый key_moment отдельно через `create_key_moment()`
- В `SessionExperience` писать только `key_moment_ids`

**Session journal (JSONL):**
- Каждая строка `{"type": "key_moment", ...}` уже является отдельной записью — при восстановлении создаём отдельные `KeyMoment` записи, не embedded список.

---

## Часть 6: Микрорефлексия в свободное время

Агент сам решает запустить её по таймауту (мы упоминаем как один из вариантов, не принуждаем). Если запустил — результат сохраняется в StateStore с привязкой к `session_id` текущей сессии. Если не запустил — ничего не теряем, это необязательно.

Триггер: агент вызывает существующие инструменты рефлексии в ходе "свободного времени". Runner не запускает рефлексию автоматически — только агент.

---

## Что НЕ входит в этот план

- PassiveFactExtractor / PassiveMemoryInjector (отдельная задача)
- PostgresExperienceStore полная реализация (отдельная задача — но порт меняем здесь)

---

## Верификация

```bash
# Unit тесты — unexamined_fact_refs
pytest tests/test_session_manager.py -v -k "unexamined"

# Все unit тесты — убедиться что ничего не сломали
pytest tests/ -x -q --ignore=tests/integration

# Ручной тест токен-мониторинга — поставить context_limit=500 в конфиге
# и запустить chat() — должно сработать предупреждение на 70%
python -m atman chat --context-limit 500
```
