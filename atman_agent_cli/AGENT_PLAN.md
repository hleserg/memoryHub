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
├── telegram.py           — (planned) TelegramBot + FileReceiver + OCR pipeline
├── queue.py              — (planned) TaskQueue + QueueScreen (Textual full-screen)
├── file_access.py        — (planned) SafeFileExplorer (read-only outside repo)
```

### Провайдеры

| Роль | Дефолт | Альтернативы |
|------|--------|--------------|
| coder | llamacpp | claude-sonnet, claude-opus |
| planner | cohere | claude-sonnet, claude-opus, llamacpp |
| embedder | local (BGE-M3) | cohere |
| reranker | local (bge-reranker-v2-m3) | cohere (rerank-v3.5), cohere (rerank-multilingual-v3.0) |

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
├── providers.json        — текущая конфигурация провайдеров
└── session_summaries.jsonl — (planned) межсессионные структурированные сводки

~/.atman/agent_index/
├── chunks.jsonl          — RAG чанки (path, content, start_line, file_hash)
├── embeddings.npy        — BGE-M3 dense векторы
├── sparse_weights.jsonl  — (planned) BGE-M3 sparse веса (lexical)
└── symbol_index.json     — (planned) символьный индекс (имена функций/классов/переменных)

~/.atman/telegram/
└── media/                — (planned) полученные файлы и скрины, в .gitignore
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
├─[Chat]──[Plans]──[Queue]──[Config]──[Changes]─────────────────┤
│  chat log (RichLog, streaming)        │ sidebar: mode, plan,  │
│                                       │ providers, RAG stats, │
│  > input_______________________       │ token bar             │
├───────────────────────────────────────────────────────────────┤
│ ● Executing step 3/7: implement auth  ░░░░░░░░░░░░░░░ 42%     │
│ ^P Plan  ^A Agent  ^B Babysit  ^R Review  ^K Config  ^Q Quit  │
└───────────────────────────────────────────────────────────────┘
```

Slash-команды: `/mode /status /plans /resume /index /diff /memory /babysit /review /finalize /sync /changes /config /search /sites /commit /ask /export /help`

---

## Вопросы к Sergey (открытые)

1. **Контекстный лимит llama.cpp** — дефолт 8192 токенов (`ATMAN_CONTEXT_LIMIT=8192`). Для Gemma4 9B / Qwen3 14B GGUF зависит от квантизации. Если модель поддерживает 32K+ — стоит поднять, compression будет срабатывать реже.

2. **Babysit — автомерж без апрува?** — сейчас babysit ждёт CI green + approved. Для соло-PR нужен флаг `--no-review-required`.

3. **Webhook для CI reviewer** — нужен входящий трафик: публичный IP или `cloudflared tunnel` / `ngrok`.

4. **`llm.py`** — устаревший файл, дублирует providers.py. Удалить?

5. **`main_watcher.py` и `webhook.py`** — артефакты из предыдущих сессий. Включать в архив?

6. **Telegram bot token** — нужен bot token от @BotFather. Хранится в SecretsManager (`telegram_token`).

7. **OCR движок** — предпочтение: `easyocr` (лучше для фото, поддерживает RU), `pytesseract` (быстрее для чистых скринов), или оба с автовыбором?

---

## Задания

> Все задания ниже описаны как инструкция для Cursor cloud agent.
> Порядок блоков — рекомендуемый порядок работы. Внутри блока задания независимы если не указано иное.

---

### БЛОК 1 — Критические CLI-фиксы

---

#### TASK-1.1 — Реализовать `/commit` slash-команду

**Файлы:** `cli.py`, `git.py`

Команда упоминается в выводе агента ("Type /commit to commit") но не реализована.

**Поведение:**
1. Показать diff (`git diff --staged` + `git status`) в RichLog.
2. Спросить commit message (или предложить авто-генерацию через LLM по diff).
3. `git add -A` → `git commit -m "..."` → `git push`.
4. Предложить создать PR: "Create PR? [y/N]". Если y — вызвать `PRManager.create_pr()`.
5. Вывести ссылку на PR в чат.

**Ограничение:** `BranchGuard` должен блокировать если текущая ветка — `main`. В этом случае агент обязан создать новую ветку перед коммитом. Коммитить в `main` напрямую — **запрещено всегда**.

**Валидация:** `/commit` в тестовом репо → коммит создан, ветка не main, PR создан через GitHub API.

---

#### TASK-1.2 — Починить streaming в executor (Textual RichLog)

**Файлы:** `executor.py`, `cli.py`

Сейчас `_run_executor` вызывается из `@work` воркера и пытается стримить через `call_from_thread`. RichLog не всегда обновляется чанк-за-чанком — зависит от того как буферизует Textual.

**Решение:**
- Использовать `app.call_from_thread(self.query_one(RichLog).write, chunk)` с явным `markup=False`.
- Добавить `await asyncio.sleep(0)` между чанками чтобы дать event loop шанс отрисовать.
- Проверить что воркер объявлен как `@work(thread=True)`.

**Валидация:** Запустить `agent` режим с длинной задачей — текст появляется в RichLog посимвольно/чанками, не одним блоком после завершения.

---

#### TASK-1.3 — Interrupt/cancel текущего воркера (Ctrl+C)

**Файлы:** `cli.py`, `executor.py`

**Реализация:**
```python
# В executor.py:
class PlanExecutor:
    _stop_event: threading.Event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def _should_stop(self) -> bool:
        return self._stop_event.is_set()
```

- В каждом цикле шага executor'а проверять `_should_stop()` — если True, бросать `ExecutorInterrupted`.
- В `cli.py` добавить binding: `BINDING("ctrl+c", "interrupt_executor", "Stop")`.
- При interrupt'е показать в чате: "⏹ Stopped. Step N was in progress. Resume with /resume."
- Текущий прогресс (выполненные шаги) сохраняется — resume подхватывает с места остановки.

**Валидация:** Запустить многошаговый план, нажать Ctrl+C — воркер останавливается за ≤2 сек, статус в sidebar обновляется.

---

#### TASK-1.4 — `/config set llm_url <url>`

**Файлы:** `config.py`, `cli.py`, `providers.py`

URL llama.cpp сервера сейчас захардкожен в `AgentConfig`. Нужно сделать его изменяемым в рантайме.

**Реализация:**
- Добавить `llm_url` в `AgentConfig` с дефолтом из env `ATMAN_LLM_URL` (fallback: `http://localhost:8080`).
- Команда: `/config set llm_url http://...` → обновить `AgentConfig.llm_url` + сохранить в `providers.json`.
- При изменении — пересоздать клиент в `ProviderRouter` (без рестарта).
- Показать в sidebar: `coder: llamacpp @ localhost:8080`.

**Валидация:** `/config set llm_url http://127.0.0.1:9090` → sidebar обновился → следующий запрос идёт на новый URL.

---

#### TASK-1.5 — Plan tab: кликабельные строки

**Файлы:** `cli.py`

В Plans tab таблица показывает данные но клик на строку не обрабатывается. Нужно: клик → загрузить план как `current_plan` + переключить режим в `agent`.

**Реализация:**
- Добавить `on_data_table_row_selected` handler.
- Загрузить план по ID из `AgentMemory`.
- Обновить sidebar: показать выбранный план + прогресс.
- Спросить в чате: "Resume plan '<title>'? [/agent to start]".

---

#### TASK-1.6 — RAG поиск всегда активен в plan mode

**Файлы:** `cli.py`, `rag.py`

Сейчас RAG вызывается только если явно есть "search intent" в сообщении. В plan mode стоит всегда делать RAG по кодовой базе и прокидывать релевантные чанки в `discuss()`.

**Реализация:**
- В plan mode: перед каждым вызовом planner → `rag.search(user_message, top_k=5)`.
- Добавить чанки как `documents` в Cohere chat API (см. TASK-2.7).
- В sidebar показывать: "RAG: 5 chunks injected".
- Если RAG вернул 0 результатов — не вставлять (не захламлять контекст пустым блоком).

---

### БЛОК 2 — RAG / Embedding прокачка

---

#### TASK-2.1 — Гибридный поиск BGE-M3 (dense + sparse + ColBERT)

**Файлы:** `rag.py`

Сейчас BGE-M3 используется только в dense режиме (cosine similarity по векторам). Модель поддерживает три режима — включить все.

**Реализация:**
```python
from FlagEmbedding import BGEM3FlagModel

model = BGEM3FlagModel('BAAI/bge-m3', use_fp16=True)

output = model.encode(
    queries,
    return_dense=True,
    return_sparse=True,       # lexical — точные совпадения по токенам
    return_colbert_vecs=True  # multi-vector — токен-по-токену matching
)

# Финальный score (эмпирические веса, можно тюнить):
score = 0.4 * dense_score + 0.2 * sparse_score + 0.4 * colbert_score
```

**Зачем:** Sparse критичен для кода — если спрашивать "где используется `BranchGuard`", dense найдёт «похожие концепции», sparse найдёт буквально имя.

**Хранение:** `sparse_weights.jsonl` рядом с `embeddings.npy`. При инкрементальном обновлении (TASK-2.5) обновлять оба файла.

**Коэффициенты** вынести в `AgentConfig` (`rag_dense_weight`, `rag_sparse_weight`, `rag_colbert_weight`) — пользователь может менять без перестройки индекса.

**Валидация:** Поиск по точному имени класса из кодовой базы → sparse должен выдать точный файл в top-1. Поиск по смыслу ("место где обрабатываются PR") → dense должен выдать правильный модуль в top-3.

---

#### TASK-2.2 — Two-stage retrieve → rerank pipeline

**Файлы:** `rag.py`, `providers.py`

**Pipeline:**
```
1. Hybrid search (TASK-2.1) → top 30–50 кандидатов
2. bge-reranker-v2-m3 (cross-encoder) → top 5–8
3. Inject в контекст LLM
```

Разница между bi-encoder (текущий) и cross-encoder (reranker): bi-encoder смотрит на query и chunk по отдельности, cross-encoder смотрит на пару целиком — принципиально точнее для финального отбора.

**Реализация:**
```python
from FlagEmbedding import FlagReranker

reranker = FlagReranker('BAAI/bge-reranker-v2-m3', use_fp16=True)

# Подаём пары (query, chunk_text):
pairs = [(query, chunk.content) for chunk in candidates]
scores = reranker.compute_score(pairs, normalize=True)
```

**Runtime switch** (уже есть в providers.py — просто подключить):
- `local` → `FlagReranker('BAAI/bge-reranker-v2-m3')`
- `cohere` → Cohere Rerank API (`rerank-v3.5` для EN, `rerank-multilingual-v3.0` для RU/mixed)

**Параметры** в `AgentConfig`: `rag_candidates_k=40`, `rag_final_k=6` — вынести чтобы можно было тюнить.

---

#### TASK-2.3 — QueryFusionRetriever (multi-query expansion)

**Файлы:** `rag.py`

Одна формулировка запроса не всегда находит то что нужно. QueryFusion генерирует несколько перефразировок, ищет по каждой, объединяет через Reciprocal Rank Fusion.

**Реализация:**
```python
def _expand_query(self, query: str, n: int = 4) -> list[str]:
    """LLM генерирует N альтернативных формулировок запроса."""
    prompt = f"""Generate {n} different search queries for a code search engine
    to find relevant code for this question. Return only queries, one per line.
    Original: {query}"""
    return self.planner.complete(prompt).split('\n')

def search_fusion(self, query: str, top_k: int = 6) -> list[Chunk]:
    queries = [query] + self._expand_query(query, n=3)
    all_results = {}
    for i, q in enumerate(queries):
        for rank, chunk in enumerate(self._dense_search(q, top_k=20)):
            # Reciprocal Rank Fusion score:
            rrf_score = 1 / (60 + rank)
            all_results[chunk.id] = all_results.get(chunk.id, 0) + rrf_score
    top = sorted(all_results, key=all_results.get, reverse=True)[:top_k]
    return [self._get_chunk(cid) for cid in top]
```

**Когда применять:** В plan mode и при `/ask`. Не в agent mode (слишком дорого по времени на каждый шаг).

---

#### TASK-2.4 — Sentence Window + контекстное расширение чанков

**Файлы:** `rag.py`

Сейчас чанки нарезаются по размеру. Проблема: нашли строку с функцией, но в чанк не влезло начало определения.

**Решение — Sentence Window:**
- Индексировать мелкие чанки (10–15 строк) для точного поиска.
- При извлечении — автоматически расширять до окна ±N строк вокруг матча.

```python
@dataclass
class Chunk:
    path: str
    content: str        # мелкий чанк для поиска
    window_content: str # расширенное окно для инъекции в LLM
    start_line: int
    window_start: int
    window_end: int
    file_hash: str
```

**Параметр** в `AgentConfig`: `rag_window_lines=10` (±10 строк). Для больших файлов — меньше. Для конфигов — больше.

**Иерархический (Auto-Merging) вариант:** Если ≥3 чанка из одного файла попали в top-K — заменить их на чанк уровня выше (весь класс / вся функция). Предотвращает фрагментарный контекст.

---

#### TASK-2.5 — RAG auto-update после sync (trivial but critical)

**Файлы:** `sync.py`, `rag.py`

Метод `rag.update(files)` написан, но не вызывается после `save_changeset()`. Агент кодит по устаревшему индексу собственных изменений.

**Реализация (одна строчка в sync.py):**
```python
def save_changeset(self, commits: list[Commit]) -> None:
    # ... существующий код ...
    changed_files = [f for c in commits for f in c.files]
    self.rag_index.update(changed_files)  # ← добавить это
```

Дополнительно — при старте агента: если `chunks.jsonl` старше `rag_stale_hours` (дефолт: 4 часа) → показать предупреждение в чате и предложить `/index`.

---

#### TASK-2.6 — Tree-sitter chunking (AST-aware)

**Файлы:** `rag.py` (новый метод `_chunk_by_ast`)

**Зависимость:** `tree-sitter>=0.21`, `tree-sitter-python`, `tree-sitter-javascript`, etc.

Текущая нарезка по размеру режет функции пополам. Tree-sitter парсит AST и режет по семантическим границам.

**Реализация:**
```python
def _chunk_by_ast(self, path: Path, content: str) -> list[Chunk]:
    lang = detect_language(path)  # по расширению
    if lang not in SUPPORTED_LANGS:
        return self._chunk_by_size(content, path)  # fallback

    parser = get_parser(lang)
    tree = parser.parse(content.encode())

    chunks = []
    for node in tree.root_node.children:
        if node.type in ('function_definition', 'class_definition',
                         'decorated_definition', 'function_declaration'):
            chunks.append(Chunk(
                path=str(path),
                content=content[node.start_byte:node.end_byte],
                start_line=node.start_point[0],
                metadata={
                    'type': node.type,
                    'name': _extract_name(node),
                    'language': lang,
                }
            ))
    return chunks
```

**Метаданные в chunks** (добавить во всех случаях):
- `language` — python / js / ts / go / etc.
- `type` — function / class / import / config / markdown
- `name` — имя функции или класса если есть
- `dependencies` — импорты из файла (для понимания контекста)

**Приоритет:** Сначала AST, fallback на size-based для неподдерживаемых форматов.

---

#### TASK-2.7 — Символьный индекс (grep-level поиск без embedding)

**Файлы:** `rag.py` (новый метод), `symbol_index.json`

Быстрый O(1) поиск по именам — дополняет семантический поиск.

**Реализация:**
```python
# symbol_index.json:
{
  "BranchGuard": [{"path": "git.py", "line": 12, "type": "class"}],
  "assess_feasibility": [{"path": "executor.py", "line": 87, "type": "function"}],
  ...
}

def symbol_search(self, name: str) -> list[Chunk]:
    entries = self.symbol_index.get(name, [])
    return [self._load_chunk_at(e['path'], e['line']) for e in entries]
```

Строится при `/index` из AST (если tree-sitter есть) или regex-эвристикой (`def `, `class `, etc.). Обновляется инкрементально при `rag.update()`.

**Использование:** В поиске — сначала символьный индекс (мгновенно), потом гибридный (медленнее). Объединить результаты перед rerank.

---

#### TASK-2.8 — Cohere grounded citations в planner

**Файлы:** `providers.py`, `cli.py`

Cohere Command A поддерживает нативный RAG с grounded citations — модель сама ссылается на источники из переданных документов. Текущая реализация передаёт чанки просто в сообщении.

**Реализация:**
```python
# В providers.py, метод ProviderRouter.plan():
if self.planner_provider == 'cohere':
    response = co.chat(
        model="command-a-03-2025",
        message=user_message,
        documents=[
            {
                "id": chunk.id,
                "data": {
                    "text": chunk.window_content,
                    "source": f"{chunk.path}:{chunk.start_line}",
                    "type": chunk.metadata.get('type', 'code'),
                }
            }
            for chunk in rag_chunks
        ]
    )
    # response.citations содержит точные ссылки на источники
    citations = response.citations  # list of Citation(start, end, document_ids)
```

**В TUI:** После ответа planner'а показывать источники в отдельном блоке:
```
📎 Sources: git.py:12 (BranchGuard), executor.py:87 (assess_feasibility)
```

Это даёт: план генерируется со ссылками на конкретные файлы. Вместо "изменить executor" — "изменить `executor.py:87`, функция `assess_feasibility`".

---

#### TASK-2.9 — Cohere Rerank как runtime provider (wire-up)

**Файлы:** `providers.py`, `rag.py`

Переключение reranker в рантайме уже объявлено в providers.py, но не подключено к rag.py.

**Реализация:**
```python
# В rag.py:
def _rerank(self, query: str, candidates: list[Chunk]) -> list[Chunk]:
    provider = self.router.reranker_provider

    if provider == 'local':
        pairs = [(query, c.content) for c in candidates]
        scores = self.flag_reranker.compute_score(pairs, normalize=True)
    elif provider == 'cohere':
        result = self.co.rerank(
            model=self.config.cohere_rerank_model,  # rerank-v3.5 / rerank-multilingual-v3.0
            query=query,
            documents=[c.content for c in candidates],
            top_n=self.config.rag_final_k,
        )
        scores = {r.index: r.relevance_score for r in result.results}

    return sorted(candidates, key=lambda c: scores[candidates.index(c)], reverse=True)
```

**Когда какой модель:**
- `rerank-v3.5` — для English-dominant кода и документации
- `rerank-multilingual-v3.0` — для RU комментариев, README, planning conversations
- `local (bge-reranker-v2-m3)` — оффлайн, приватный код, GPU есть

---

### БЛОК 3 — Новые возможности (формализованные хотелки)

---

#### TASK-3.1 — /commit безопасность: git safety net

**Файлы:** `git.py`, системный промпт

Жёсткие правила которые должны быть закодированы в `BranchGuard` и системном промпте, не обходятся никакими командами:

1. **Никогда не коммитить напрямую в `main`.** Если текущая ветка — `main` → автоматически создать новую ветку `agent/<task-slug>` перед любыми изменениями.
2. **Никогда не пушить в `main`.** `BranchGuard.push()` проверяет branch → если `main` → `raise BranchGuardError`.
3. **Все изменения только через PR.** `PRManager.create_pr()` обязателен перед merge.
4. **Системный промпт содержит:** "You MUST NOT commit or push directly to `main`. Always work on a separate branch and create a PR."

> Примечание: это правило уже частично реализовано в BranchGuard — здесь нужно убедиться что оно покрывает все пути и добавить в системный промпт явно.

---

#### TASK-3.2 — Чтение файлов из рабочей директории

**Файлы:** `file_access.py` (новый), `cli.py`, системный промпт

Агент должен уметь читать файлы из папки где запущен, и ходить по вложенным папкам.

**SafeFileExplorer — контракты:**
```python
class SafeFileExplorer:
    def __init__(self, repo_root: Path, work_dir: Path):
        self.repo_root = repo_root.resolve()
        self.work_dir = work_dir.resolve()

    def read(self, path: str | Path) -> str:
        """Читать любой файл. Вне репо — только read."""
        ...

    def search(self, pattern: str, root: Path = None, recursive: bool = True) -> list[Path]:
        """Рекурсивный поиск файлов по имени или glob."""
        ...

    def list_dir(self, path: Path) -> list[Path]:
        """Листинг директории (любая глубина)."""
        ...

    def write(self, path: Path, content: str) -> None:
        """Запись ТОЛЬКО внутри repo_root. Вне — raise PermissionError."""
        if not path.resolve().is_relative_to(self.repo_root):
            raise PermissionError(f"Write outside repo is forbidden: {path}")
        ...

    def delete(self, path: Path) -> None:
        """Удаление ТОЛЬКО внутри repo_root. Вне — raise PermissionError."""
        ...

    def execute(self, cmd: str) -> None:
        """Запуск исполняемых файлов — ТОЛЬКО с явного подтверждения пользователя."""
        ...
```

**Системный промпт:**
```
Outside the repository directory you can only READ files. 
You MUST NOT write, delete, or modify files outside the repo without explicit user confirmation.
You MUST NOT execute any scripts or binaries without explicit user confirmation.
When the user asks to "look at" a path — read and report. Never modify.
```

**В TUI:** Если агент пытается писать вне репо → показать предупреждение + запросить подтверждение `[y/N]` перед выполнением.

---

#### TASK-3.3 — Доступ к файлам по пути из любой директории

**Файлы:** `cli.py`, `config.py`

Агент должен запускаться из любой папки, понимать где находится, и уметь работать с файлами вне репо.

**Реализация:**
- При старте: определить `work_dir = Path.cwd()`, `repo_root = git_root(work_dir)` (или `work_dir` если не git repo).
- Показывать в header TUI: `atman-agent — ~/projects/myapp — main`.
- Команда `/pwd` — показать текущую директорию и git root.
- Если пользователь присылает путь (`/home/sergey/docs/spec.pdf`) → `SafeFileExplorer.read()` → показать содержимое в чате.
- OCR автодетект: если файл — изображение (jpg/png/webp/gif) → автоматически применить OCR (TASK-3.5).

---

#### TASK-3.4 — GitHub Issue → автоматический приём в работу

**Файлы:** `cli.py`, `git.py`

Если пользователь присылает ссылку на GitHub issue (`https://github.com/owner/repo/issues/123`) — агент:
1. Загружает issue через GitHub API (`GET /repos/{owner}/{repo}/issues/{number}`).
2. Показывает title + body в чате.
3. Если в сообщении нет "просто посмотри" / "не выполняй" — спрашивает: "Take this issue as task? [Y/n]".
4. Если да — создаёт план из описания issue + добавляет в Queue (TASK-3.6).
5. Если issue содержит чеклист (`- [ ] ...`) — импортирует как шаги плана напрямую.

**Определение "не выполняй":** Простая эвристика — наличие в сообщении слов "посмотри", "прочитай", "покажи", "not now", "just look", "don't start".

---

#### TASK-3.5 — OCR для изображений

**Файлы:** `ocr.py` (новый), `cli.py`, `file_access.py`

**Зависимости:** `easyocr>=1.7` (основной, поддерживает RU+EN), `pillow>=10.0`.
`pytesseract` — опциональный fallback (требует системный tesseract).

**Реализация:**
```python
class OCRProcessor:
    def __init__(self, languages: list[str] = ['ru', 'en']):
        import easyocr
        self.reader = easyocr.Reader(languages, gpu=True)  # gpu=False если нет

    def extract_text(self, image_path: Path) -> str:
        results = self.reader.readtext(str(image_path), detail=0)
        return '\n'.join(results)
```

**Автодетект:** В `SafeFileExplorer.read()` — если `path.suffix in ['.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp']` → вызвать `OCRProcessor.extract_text()`.

**Хранение:** `~/.atman/telegram/media/` — все полученные файлы (скрины, фото). Папка добавляется в `.gitignore` проекта автоматически при первом использовании.

---

#### TASK-3.6 — Task Queue: очередь задач

**Файлы:** `queue.py` (новый), `cli.py` (новый таб Queue)

**Модель данных:**
```python
@dataclass
class QueueTask:
    id: str           # uuid
    title: str
    description: str  # полный текст задачи
    priority: Literal['now', 'later']  # "в работу" / "на будущее"
    status: Literal['pending', 'in_progress', 'done', 'blocked']
    created_at: datetime
    order: int        # для drag-to-reorder

# Хранится в ~/.atman/agent_memory/task_queue.jsonl
```

**QueueScreen (Textual full-screen):**
```
┌─ Task Queue ─────────────────────────────────────────────────────────────┐
│  ┌─ Queue ──────────────────┐  ┌─ Description ──────────────────────────┐ │
│  │ ⚡ [now] Implement auth  │  │                                        │ │
│  │ ⚡ [now] Fix streaming   │  │  Implement OAuth2 login flow with      │ │
│  │ ── [now] Add /commit cmd │  │  GitHub provider. See issue #42.       │ │
│  │ ░░ [later] Telegram bot  │  │                                        │ │
│  │ ░░ [later] OCR support   │  │                                        │ │
│  └──────────────────────────┘  └────────────────────────────────────────┘ │
│  [Add] [Delete] [↑ Up] [↓ Down] [Toggle now/later] [→ Start]              │
└──────────────────────────────────────────────────────────────────────────┘
```

**Поведение:**
- `[now]` задачи — жёлтый. `[later]` — серый.
- Клик на задачу → описание в правой панели.
- `[Add]` → открыть TextArea для описания → `[OK]` → задача уходит в очередь с `priority='now'` по умолчанию.
- `[Delete]` → подтверждение: "Delete task '<title>'? [y/N]".
- `[↑][↓]` → изменить порядок (поле `order`).
- `[Toggle]` → переключить now/later.
- `[→ Start]` → загрузить задачу как `current_plan` + переключить в agent mode.

**Автоматический pick-up:** Когда executor завершает текущую задачу → проверить Queue → взять первую `priority='now'` с `status='pending'` → начать.

---

#### TASK-3.7 — Status bar во всех интерфейсах

**Файлы:** `cli.py`, `queue.py` (и все будущие Textual-экраны)

Строка состояния снизу любого экрана:

```
● Busy  │  Executing: "Implement auth"  │  Plan: 3/7 steps  │  Branch: feat/auth  │  RAG: 247 chunks
○ Idle  │  Last: "Implement auth" (done)│  ─────────────────│  Branch: main        │  Tokens: 4.2k/8k
```

**Реализация:** Выделить `AgentStatusBar` как отдельный Textual widget, подключать через `compose()` в каждом Screen. Обновляется через реактивные переменные (`reactive` в Textual).

**Поля:**
- Иконка состояния (● занят / ○ свободен)
- Текущая задача (или последняя завершённая)
- Прогресс плана (N/M шагов) если есть активный план
- Текущая git ветка
- Размер RAG индекса (чанков)
- Использование токенов (current/limit)

---

#### TASK-3.8 — Telegram бот: интерфейс и файлы

**Файлы:** `telegram.py` (новый), `cli.py`

**Зависимости:** `python-telegram-bot>=21.0` (async).

**Возможности:**
- Приём текстовых сообщений → пересылка в `AgentMemory` / executor как задача.
- Приём файлов (документы, фото) → сохранить в `~/.atman/telegram/media/` → уведомить в TUI.
- Фото → автоматически OCR (TASK-3.5) → текст в чат.
- PDF → извлечь текст (pdfminer.six) → добавить в RAG как временный документ.
- Команды бота: `/status`, `/plans`, `/queue`, `/stop`.
- Ответы агента → отправляются в Telegram (polling mode, не webhook, для простоты).

**Изоляция:**
- `~/.atman/telegram/media/` добавляется в `.gitignore` автоматически.
- Бот работает параллельно с TUI (отдельный asyncio task).
- Token хранится в `SecretsManager` как `telegram_token`.

**Безопасность:** Принимать сообщения только от авторизованных chat_id (список в `AgentConfig.telegram_allowed_ids`). Все остальные игнорировать молча.

---

### БЛОК 4 — Дополнительные улучшения

---

#### TASK-4.1 — Межсессионная память: structured session summaries

**Файлы:** `memory.py`, `context_manager.py`

Сейчас между сессиями сохраняются только `facts.jsonl` (разрозненные факты). Нет структурированного понимания "что делали в прошлый раз".

**Реализация:**
```python
@dataclass
class SessionSummary:
    session_id: str
    started_at: datetime
    ended_at: datetime
    task_description: str      # что делали
    files_changed: list[str]   # какие файлы трогали
    decisions_made: list[str]  # ключевые решения ("выбрали postgres вместо sqlite")
    open_questions: list[str]  # что осталось неясным
    next_suggested_step: str   # что делать в следующий раз
    outcome: Literal['completed', 'blocked', 'abandoned']
```

При завершении сессии (`/quit` или timeout) → LLM генерирует `SessionSummary` по истории → сохраняется в `session_summaries.jsonl`.

При старте новой сессии → загружается последняя `SessionSummary` → вставляется в system prompt как "previous session context".

---

#### TASK-4.2 — Diff preview перед коммитом

**Файлы:** `cli.py`, `git.py`

Перед любым коммитом (ручным `/commit` или авто) — показать компактный diff в RichLog с подсветкой синтаксиса. Спросить подтверждение.

**Реализация:**
- `git diff --staged --stat` → показать список изменённых файлов + числа.
- По запросу (нажать `d`) → развернуть полный unified diff с Rich Syntax.
- Подтверждение: `[Commit] [Edit message] [Cancel]`.

Это предотвращает случайные коммиты с debugging кодом / credentials.

---

#### TASK-4.3 — `/ask` команда: read-only запрос к кодовой базе

**Файлы:** `cli.py`, `rag.py`

Лёгкая команда для вопросов о коде без перехода в agent mode:

```
/ask где обрабатывается merge conflict?
/ask что делает BranchGuard?
/ask как устроен context compression?
```

**Поведение:** QueryFusion (TASK-2.3) → rerank → LLM отвечает на основе чанков + citations. Не изменяет план, не переключает режим. Быстро (3–5 сек).

---

#### TASK-4.4 — Умное восстановление из blocked (executor improvements)

**Файлы:** `executor.py`

Сейчас при `assess_result() = fail` → `mark_blocked(reason)` и двигаться дальше. Агент не пытается понять причину и предложить решение.

**Улучшение:**
```python
async def _handle_blocked(self, step: Step, reason: str) -> RecoveryAction:
    # LLM анализирует причину блокировки:
    analysis = await self.planner.analyze_block(
        step=step,
        reason=reason,
        recent_context=self.recent_messages(n=10),
        rag_chunks=self.rag.search(reason, top_k=3),
    )
    # Варианты:
    # - "missing_dependency" → предложить установить / реализовать
    # - "ambiguous_requirement" → задать уточняющий вопрос
    # - "external_service_unavailable" → предупредить пользователя
    # - "insufficient_context" → запросить /ask или уточнение
```

После анализа — сообщение в чат с объяснением и предложением действия, не просто "blocked".

---

#### TASK-4.5 — Playwright автодетект

**Файлы:** `web.py`

Сейчас playwright только если `use_playwright=True`. Если trafilatura вернула меньше 200 символов — автоматически попробовать playwright.

```python
async def fetch_url(self, url: str) -> str:
    content = trafilatura.fetch_url(url)
    text = trafilatura.extract(content) or ""

    if len(text) < 200 and self.playwright_available:
        text = await self._fetch_with_playwright(url)

    return text or f"[Could not extract content from {url}]"
```

Playwright `available` = проверяется при старте через `shutil.which("chromium")`.

---

#### TASK-4.6 — `/export` план в epic-формат

**Файлы:** `cli.py`, `memory.py`

Выгрузить текущий план как epic-файл совместимый с `bulk_create_issues.py`.

```
/export → выбрать план → ввести epic номер → сохранить E21_<slug>.md
```

Формат автоматически подбирается под шаблон с em-dash заголовком, subtask-блоками, labels и т.д. Замыкает круг с основным pipeline.

---

#### TASK-4.7 — Нотификации при событиях в фоне

**Файлы:** `sync.py`, `cli.py`

При событиях пока TUI не в фокусе → системное desktop-уведомление.

**Зависимость:** `plyer>=2.1` (кроссплатформенные нотификации: Linux libnotify, macOS NSNotification, Windows toast).

**События:**
- PR смерджен в main
- CI упал на PR агента
- Telegram-сообщение получено (если бот активен)
- Executor завершил задачу

```python
from plyer import notification

notification.notify(
    title="Atman Agent",
    message="PR #42 merged to main",
    timeout=5,
)
```

---

#### TASK-4.8 — История поиска и `/search` без аргументов

**Файлы:** `search.py`, `memory.py`, `cli.py`

Сохранять историю web-поисков в `~/.atman/agent_memory/search_history.jsonl`:
```python
@dataclass
class SearchEntry:
    query: str
    timestamp: datetime
    results_count: int
    used_in_session: str  # session_id
```

`/search` без аргументов → показать последние 10 запросов в виде кликабельного списка → выбрать → повторить поиск.

---

### БЛОК 5 — Зависимости и конфигурация

---

#### Обновлённый pyproject.toml

```toml
[project.optional-dependencies]
agent = [
    # TUI
    "textual>=0.60",
    # HTTP / web
    "requests>=2.31",
    "trafilatura>=1.6",
    "duckduckgo-search>=6.0",
    # LLM providers
    "cohere>=5.0",
    "anthropic>=0.25",
    # RAG / embeddings
    "FlagEmbedding>=1.2",        # BGE-M3 + bge-reranker-v2-m3
    "numpy>=1.24",
    "tree-sitter>=0.21",         # AST-aware chunking (TASK-2.6)
    "tree-sitter-python",
    "tree-sitter-javascript",
    "tree-sitter-typescript",
    # Token counting
    "tiktoken>=0.7",
    # OCR
    "easyocr>=1.7",              # RU+EN OCR (TASK-3.5)
    "pillow>=10.0",
    # Telegram
    "python-telegram-bot>=21.0", # (TASK-3.8)
    # Notifications
    "plyer>=2.1",                # (TASK-4.7)
    # Utilities
    "pdfminer.six>=20221105",    # PDF text extraction
]
```

#### Опциональные (не в toml, ручная установка)

```bash
# JS-страницы в web.py:
pip install playwright && playwright install chromium

# Tesseract OCR (fallback для easyocr):
sudo apt install tesseract-ocr tesseract-ocr-rus

# self-hosted GitHub runner + webhook:
# Настроить cloudflared tunnel или публичный IP
```

#### Переменные окружения

```bash
ATMAN_LLM_URL=http://localhost:8080    # llama.cpp server
ATMAN_CONTEXT_LIMIT=8192               # токены (поднять для Gemma4/Qwen3 если поддерживают)
ATMAN_RAG_CANDIDATES_K=40              # кандидатов до rerank
ATMAN_RAG_FINAL_K=6                    # после rerank, в контекст
ATMAN_RAG_WINDOW_LINES=10              # контекстное окно (±N строк)
ATMAN_RAG_STALE_HOURS=4               # автопредупреждение об устаревшем индексе
ATMAN_RAG_DENSE_WEIGHT=0.4             # веса hybrid score
ATMAN_RAG_SPARSE_WEIGHT=0.2
ATMAN_RAG_COLBERT_WEIGHT=0.4
ATMAN_TELEGRAM_ALLOWED_IDS=12345678   # comma-separated chat IDs
COHERE_API_KEY=...
ANTHROPIC_API_KEY=...
GITHUB_TOKEN=...
```

---

## Открытые вопросы (ждут ответа Sergey)

- [ ] Контекстный лимит llama.cpp: Gemma4 9B / Qwen3 14B GGUF — сколько реально поддерживает при твоей квантизации?
- [ ] Babysit: автомерж без апрува или всегда ждать reviewer?
- [ ] OCR движок: easyocr (лучше качество) или pytesseract (быстрее)?
- [ ] Telegram: токен готов? Какие chat_id разрешены?
- [ ] `llm.py` (legacy): удалить или оставить как fallback?
- [ ] GPU для easyocr и bge-reranker: есть CUDA на машине где будет работать агент?
