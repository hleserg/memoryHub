# Atman Agent CLI — Planning & Spec Document

## Текущая реализация

### Структура файлов

```
src/atman/agent_cli/
├── __init__.py           — точка входа, pyproject.toml hints
├── config.py             — AgentConfig (пути, URLs, параметры)
├── secrets.py            — SecretsManager (файл/env/runtime, persist в ~/.atman/.secrets)
├── providers.py          — ProviderRouter (coder/planner/embedder/reranker, runtime switch)
├── memory.py             — AgentMemory + Plan + WorkSession + StepMeta
├── git.py                — BranchGuard + PRManager (GitHub API)
├── rag.py                — RAGIndex (BGE-M3 + bge-reranker-v2-m3, двухэтапный поиск)
├── sync.py               — MainSyncService (фоновый polling main) + WebhookServer
├── executor.py           — PlanExecutor (smart step loop, feasibility, retry, unblock)
├── context_manager.py    — ContextManager (token tracking, compression, 3-layer strategy)
├── web.py                — URL fetcher (trafilatura + requests fallback + playwright опц.)
├── search.py             — Web search (DuckDuckGo, dev-site priority, fallback general)
├── llm.py                — (legacy) Coder + Planner классы, заменены providers.py
├── cli.py                — AtmanApp (Textual TUI, все команды, воркеры)
```

### Провайдеры

| Роль | Дефолт | Альтернативы |
|------|--------|--------------|
| coder | llamacpp | claude-sonnet, claude-opus |
| planner | cohere | claude-sonnet, claude-opus, llamacpp |
| embedder | local (BGE-M3) | cohere |
| reranker | local (bge-reranker-v2-m3) | cohere |

Переключение в рантайме: `/config coder claude-sonnet`

### Режимы работы

- **plan** — обсуждение с Cohere/Claude, накопление контекста, `/finalize` → структурированный план
- **agent** — auto-plan → PlanExecutor (feasibility check → impl → self-assess → unblock retry)
- **babysit** — PR lifecycle: review comments → merge conflicts → CI failures → merge
- **review** — code review diff → post на GitHub

### Память

```
~/.atman/agent_memory/
├── plans.jsonl           — планы с StepMeta (state, blocked_reason, notes, attempts)
├── work_sessions.jsonl   — WorkSession (обсуждение + коммиты + PR + outcome)
├── facts.jsonl           — standalone факты (из compression и ручного remember)
├── changesets.jsonl      — изменения в main (SHA cursor, файлы, авторы)
├── commit_cursors.json   — last known SHA per branch
└── providers.json        — текущая конфигурация провайдеров

~/.atman/agent_index/
├── chunks.jsonl          — RAG чанки (path, content, start_line, file_hash)
└── embeddings.npy        — BGE-M3 векторы
```

### Plan execution loop (executor.py)

```
while steps remain:
  1. find next PENDING step
  2. assess_feasibility() → LLM: "можно сделать прямо сейчас?"
     └─ нет → mark_blocked(reason) → continue
  3. implement() → stream code
  4. assess_result() → LLM: "это сработало?"
     └─ нет → mark_blocked(reason) → continue
  5. ✅ done → check blocked steps BEFORE current index
     → reassess each: "стало ли возможным после завершения этого шага?"
     → если да → unblock → он подберётся как следующий (меньший индекс)
```

### Context compression (context_manager.py)

```
Порог warning (80%)  → предупреждение в чате + sidebar
Порог critical (90%) → автоматическое сжатие в фоновом потоке:

  [system: summary + key_facts + план (полностью)]
+ [последние 6 сообщений хвост]
= ~2000 токенов вместо ~8000

Ключевые факты → сохраняются в AgentMemory.facts.jsonl
План → переезжает ПОЛНОСТЬЮ без изменений
```

### Sync (sync.py)

- Daemon-поток, polling каждые 60 сек — `git fetch` + сравнение SHA cursor
- Webhook receiver на порту 9876 (опц.) — реагирует на `pull_request.closed + merged`
- При обнаружении новых коммитов → `save_changeset()` без LLM
- Если текущая ветка смерджена → `pull_main()` молча в фоне

### TUI (cli.py — Textual)

```
┌─ atman-agent ─── feat/bge-m3 ─── ⚡ agent ─── coder:llamacpp ─┐
├─[Chat]──[Plans]──[Config]──[Changes]──────────────────────────┤
│  chat log (RichLog, streaming)        │ sidebar: mode, plan,  │
│                                       │ providers, RAG stats, │
│  > input_______________________       │ token bar             │
├───────────────────────────────────────────────────────────────┤
│ ^P Plan  ^A Agent  ^B Babysit  ^R Review  ^K Config  ^Q Quit  │
└───────────────────────────────────────────────────────────────┘
```

Slash-команды: `/mode /status /plans /resume /index /diff /memory /babysit /review /finalize /sync /changes /config /search /sites /help`

---

## Вопросы и gap-анализ

### Вопросы к Sergey

1. **Какой контекстный лимит у Gemma4 GGUF который будешь запускать?**
   Сейчас дефолт 8192 токенов (`ATMAN_CONTEXT_LIMIT=8192`). Для Gemma4 9B это зависит от квантизации и сборки llama.cpp. Если модель поддерживает больше — стоит поднять, compression будет срабатывать реже.

2. **Babysit — автомерж без апрува?**
   Сейчас babysit ждёт и CI green, и approved перед мержем. Если ты хочешь мёрджить без ревью апрува (например для своих соло-PR) — нужно добавить флаг `--no-review-required`.

3. **CI reviewer через self-hosted runner — у тебя есть публичный IP или тоннель (ngrok/cloudflare)?**
   GitHub Actions self-hosted runner требует чтобы машина могла подключаться к GitHub. Для webhook'а нужен входящий трафик — либо публичный IP, либо `cloudflared tunnel`.

4. **llm.py** — устаревший файл, дублирует providers.py. Удалить или оставить как fallback?

5. **`main_watcher.py` и `webhook.py`** — в outputs есть файлы которые я не писал в этом разговоре. Это что-то из предыдущих сессий? Надо ли их включать в архив?

### Known gaps / что не реализовано

#### Высокий приоритет

- [ ] **`/commit` slash-команда** — упоминается в выводе агента ("Type /commit to commit") но не реализована. Нужно: git add -A → commit с сообщением → push → offer PR.
- [ ] **Streaming в executor** — сейчас `_run_executor` вызывается из `@work` воркера и стримит через `call_from_thread`. Нужно проверить что стриминг реально работает в Textual (RichLog не всегда обновляется чанк за чанком).
- [ ] **Interrupt/cancel** — Ctrl+C в TUI должен останавливать текущий воркер (`executor.stop()`). Сейчас binding на Ctrl+C не добавлен.
- [ ] **`/config` для llm_url** — можно менять провайдера, но URL llama.cpp сервера захардкожен в AgentConfig. Нужно `/config set llm_url http://...`.

#### Средний приоритет

- [ ] **Автоиндекс при старте** — если индекс старше N часов → предлагать перестроить. Сейчас только ручной `/index`.
- [ ] **RAG incremental update** — метод `rag.update()` написан, но не вызывается автоматически после `sync_service` обнаруживает новые файлы в main.
- [ ] **Executor → memory integration** — после каждого выполненного шага стоит сохранять `WorkSession.files_changed` (какие файлы реально изменились). Сейчас это делается только при коммите.
- [ ] **Plan tab interactive** — в Plans tab можно кликать на строку чтобы загрузить план как `current_plan`. Сейчас таблица показывает данные но клик не обрабатывается.
- [ ] **Поиск в plan mode** — когда в plan mode и нет search intent, всё равно стоит делать RAG поиск по кодовой базе и прокидывать в discuss().

#### Низкий приоритет / nice-to-have

- [ ] **`/export` план в markdown** — выгрузить текущий план как epic-файл в формате bulk_create_issues.py (замкнуть круг с основным pipeline).
- [ ] **Нотификации** — при мёрдже PR или падении CI пока агент не в фокусе → системное уведомление (libnotify на Linux).
- [ ] **История поиска** — `/search` без аргументов → показать последние N запросов.
- [ ] **Playwright автодетект** — сейчас playwright только если явно указать `use_playwright=True`. Стоит автоматически пробовать если trafilatura вернул мало контента.

### Зависимости (что нужно поставить)

```toml
# pyproject.toml [project.optional-dependencies]
agent = [
    "textual>=0.60",
    "requests>=2.31",
    "cohere>=5.0",
    "anthropic>=0.25",
    "FlagEmbedding>=1.2",
    "numpy>=1.24",
    "trafilatura>=1.6",
    "duckduckgo-search>=6.0",
    "tiktoken>=0.7",          # точный подсчёт токенов
]
```

```bash
# Опционально для JS-страниц:
pip install playwright && playwright install chromium

# Для GitHub CI reviewer:
# Настроить self-hosted runner + webhook URL
```

### Изоляция от прода

Соблюдена по паттерну eval:
- Код живёт в `src/atman/agent_cli/`
- Зависимости в `[project.optional-dependencies] agent`
- import-linter запрещает `atman.core` импортировать из `atman.agent_cli`
- В релиз не входит

---

## Место для новых хотелок

<!-- Sergey: дописывай сюда что хочешь добавить/изменить -->

