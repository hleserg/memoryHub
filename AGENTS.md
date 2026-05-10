# AGENTS.md

## Overview

Atman — проект психологического слоя для AI-агента, находящийся на стадии **прототипирования**. Содержит документацию (markdown-файлы, изображения, шаблоны) и реализованные компоненты Python-пакета `atman`: **Factual Memory Adapter**, **Experience Store** (WP-02), **Identity Store** (WP-03), **Reflection Engine** (WP-04), **Session Manager** (WP-05).

## Cursor Cloud specific instructions

### Структура репозитория

- `src/atman/` — Python-пакет (модели, порты, адаптеры, CLI)
- `tests/` — юнит-тесты (pytest)
- `src/demo.py` — демо Factual Memory (`make demo-factual`; см. `docs/features/factual-memory/README.md`)
- `src/demo_experience_store.py` — воспроизводимый walkthrough Experience Store (временный JSONL; см. `docs/features/experience-store/README.md`)
- `src/demo_identity.py` — walkthrough Identity Store / narrative (`make demo-identity`; см. `docs/features/identity-store/README.md`)
- `src/demo_reflection.py` — walkthrough Reflection Engine (`make demo-reflection`; см. `docs/features/reflection-engine/README.md`)
- `src/demo_session_manager.py` — walkthrough Session Manager / first-hand experience coloring (`make demo-session`; см. `docs/features/session-manager/README.md`)
- `src/demo_full_corpus.py` — полный прогон E2E-фикстур сессий через Session Manager + reflection (`make demo-full-corpus`; см. `docs/features/full-corpus-demo/README.md`; нужен `PYTHONPATH=.` при запуске не через Makefile)
- `src/demo_web_dashboard.py` — краткая подсказка по Web UI в терминале (`make demo-webui`; см. `docs/features/web-dashboard/README.md`)
- `pyproject.toml` — конфигурация проекта и зависимости
- `MANIFEST.md` — философский манифест проекта
- `docs/architecture/SYSTEM.md` — подробная архитектура системы (7 компонентов, режимы работы, протоколы)
- `docs/development/DEVELOPMENT_STANDARD.md` — стандарт разработки (терминология, границы, DoD)
- `docs/research/` — исследования (mem0, интеграции)
- `docs/ideas/` — идеи для будущих блоков
- `reports/sessions/` — шаблоны отчётов о сессиях
- `.github/` — шаблоны issue/PR, GitHub Actions workflows и Dependabot; полезные автоматизации описаны в `docs/development/GITHUB_AUTOMATIONS.md` (сайт — статика из `docs/` в Pages)
- `.cursor/` — инструкции для локальных агентов
- `src/atman/term.py` — общий слой **Rich** для CLI и демо (панели, таблицы, стилизованные сообщения)

### Пользовательский вывод в терминале (Rich)

**Облачные агенты и любые правки репозитория:** весь **пользовательский** вывод в консоль (то, что видит человек при запуске скриптов) оформляйте через **Rich**.

- **Обязательно Rich** для: интерактивных CLI (`src/atman/cli.py`, `src/atman/cli_experience.py`, `src/atman/cli_identity.py`, `src/atman/cli_reflection.py`), воспроизводимых демо (`src/demo.py`, `src/demo_experience_store.py`, `src/demo_identity.py`, `src/demo_reflection.py`, `src/demo_session_manager.py`, `src/demo_web_dashboard.py`, новые `src/demo_*.py`, цели `make demo-*`), любых новых entrypoint’ов с пошаговым или табличным выводом.
- **Расширяйте `atman.term`**, а не размножайте сырые `print()` там, где уже есть хелперы (`print_banner`, `print_ok` / `print_err`, `print_fact`, `print_experience_record`, `print_salience_table`, `print_help_text`). Справка с символами `<...>` должна идти через **`print_help_text`** (без интерпретации разметки Rich).
- **Не подключайте Rich в ядре и в адаптерах хранения** ради доменной логики: граница presentation — CLI и демо. Диагностика при чтении файлов — `warnings` / логирование, не обязательный Rich.
- Зависимость **`rich`** указана в `pyproject.toml` (`dependencies`); новые сценарии с консольным UX должны на неё опираться.
- **Пошаговое раскрытие демо:** цели **`make demo-factual`**, **`make demo-experience`**, **`make demo-identity`**, **`make demo-reflection`**, **`make demo-session`**, **`make demo-full-corpus`**, **`make demo-webui`** по умолчанию задают **`ATMAN_DEMO_PACE=1`** (для **`demo-full-corpus`** Makefile также выставляет **`PYTHONPATH=.`** для импорта пакета **`e2e`**) (~0.45 с между крупными блоками). Для **мгновенного** вывода: **`make demo-*-fast`** или `ATMAN_DEMO_PACE=off python3 src/demo….py`. Иначе env **`ATMAN_DEMO_PACE`** можно выставить вручную (`0.6`, максимум 3 с). В коде демо вызывайте **`atman.term.demo_pace()`** после баннеров/секций/больших таблиц. Цели **`demo-*-paced`** — синонимы обычных `demo-*`.

### Lint / Test / Build / Run

- **Python ≥ 3.12** required (see `pyproject.toml`)
- **Install (pip)**: `pip install -e ".[dev]"`
- **Install (uv, preferred when available)**: `uv venv` → activate `.venv` → `uv pip install -e ".[dev]"` (or `uv pip install --system -e ".[dev]"` without a venv)
- **Tests**: `pytest tests/ -v --cov=atman --cov-fail-under=90` (coverage ≥90%; см. `pytest tests/ --collect-only`)
- **Tests (parallel)**: `pytest tests/ -n auto` (pytest-xdist)
- **CLI (REPL)**: `python3 -m atman.cli`
- **Demo (facts)**: `make demo-factual` (с паузами по умолчанию) or `python3 src/demo.py` (без пауз, если не задан `ATMAN_DEMO_PACE`); мгновенно: `make demo-factual-fast`
- **Demo (Experience Store)**: `make demo-experience`; мгновенно: `make demo-experience-fast`
- **Demo (Identity Store)**: `make demo-identity`; мгновенно: `make demo-identity-fast`
- **Demo (Reflection Engine)**: `make demo-reflection`; мгновенно: `make demo-reflection-fast`
- **Demo (Session Manager)**: `make demo-session` or `python3 src/demo_session_manager.py`; мгновенно: `make demo-session-fast`
- **Demo (full E2E session corpus)**: `make demo-full-corpus` (`PYTHONPATH=.`); мгновенно: `make demo-full-corpus-fast`; опции: `--locale en|ru`, `--limit N`
- **Demo (Web Dashboard hint)**: `make demo-webui`; мгновенно: `make demo-webui-fast`
- **Lint**: `ruff check src/ tests/` and `ruff format --check src/ tests/`
- **Type check**: `pyright src/ tests/` (standard mode, 0 errors)
- **Security**: `bandit -c pyproject.toml -r src/atman/`
- **Dependency audit**: `pip-audit`
- **All checks at once**: `make check` (lint + format + typecheck + security + tests)
- **Pre-commit**: configured in `.pre-commit-config.yaml` (ruff, pyright, bandit)
- No external services (databases, Docker, etc.) are required — storage is in-memory or file-based (JSONL)

### uv — рекомендуемый workflow

Если **`uv`** установлен, агентам и разработчикам **удобно использовать его не только для `uv pip install`**, но и для остального цикла: одна утилита закрывает venv, установку зависимостей и запуск инструментов без ручной активации (через `uv run`).

**Рекомендуется:**

1. Создать окружение: `uv venv` (каталог `.venv`), активировать его **или** дальше вызывать команды через `uv run`.
2. Установка пакета: `uv pip install -e ".[dev]"` (внутри активированного venv) либо `uv run` после установки.
3. Запуск без активации venv: `uv run python src/demo.py`, `uv run pytest tests/ -v`, `uv run ruff check src/ tests/`, `uv run pyright src/ tests/`, `uv run python -m atman.cli` и т.д.

**Полезно:** `uv pip tree`, синхронизация с lock-файлом в других проектах — здесь lock не обязателен; достаточно `pyproject.toml`.

`pip` / `python3 -m pip` остаются допустимым **fallback**, если `uv` недоступен.

### Gotchas

- Python ≥ 3.12; для зависимостей и команд в dev **предпочтительно `uv`** (см. выше); сборка пакета — Hatchling (`pyproject.toml`)
- PydanticAI + Anthropic (Claude), mem0, APScheduler — планируемые зависимости, пока не подключены
- Ruff настроен в `pyproject.toml` (`[tool.ruff]`); кириллица допускается (RUF001-003 отключены)
- Pyright настроен в `pyproject.toml` (`[tool.pyright]`), режим `standard`; все функции должны иметь аннотации типов
- Детали см. в `docs/architecture/SYSTEM.md`
- `pyproject.toml` specifies `ruff>=0.11.0`; the codebase has pre-existing lint/format/type-check issues on `main` (W293 whitespace, import sorting, pyright `reportArgumentType`). These are not regressions — do not block your work on fixing them unless your task explicitly requires it
- `cli.py` and `cli_experience.py` are excluded from coverage (`omit` in `pyproject.toml`); if coverage drops below 90%, check whether untested CLI code is the cause

### Язык документации

**Основной язык документации — английский.**

При работе с текстовыми файлами:

- Основная версия документов ведётся на английском языке
- Для ключевых файлов (`README.md`, `SYSTEM.md`) поддерживаются русские версии с суффиксом `-ru.md`
- При изменении английской версии необходимо синхронизировать соответствующую русскую версию
- Комментарии в коде — на английском
- Commit-сообщения — на английском

**Файлы с двуязычной поддержкой:**

- `README.md` / `README-ru.md`
- `docs/architecture/SYSTEM.md` / `docs/architecture/SYSTEM-ru.md`
- `docs/architecture/SYSTEM_MAP.md` / `docs/architecture/SYSTEM_MAP-ru.md`
- `MANIFEST.md` / `MANIFEST-ru.md`
- Feature walkthroughs: `docs/features/<feature-slug>/README.md` / `README-ru.md` — e.g. [`docs/features/factual-memory/README.md`](docs/features/factual-memory/README.md), [`docs/features/experience-store/README.md`](docs/features/experience-store/README.md), [`docs/features/identity-store/README.md`](docs/features/identity-store/README.md), [`docs/features/reflection-engine/README.md`](docs/features/reflection-engine/README.md)

**Feature instructions (demo, usage):** always create under **`docs/features/<feature-slug>/`** as the **English + Russian pair above** — not in the repository root. Edit English first, then sync Russian (same rule as root README).

### Обязательные проверки перед завершением задачи

Любая задача программирования считается завершённой только если **все проверки** пройдены с нулём ошибок:

```bash
ruff check src/ tests/                                    # lint
ruff format --check src/ tests/                           # format
pyright src/ tests/                                       # type check
bandit -c pyproject.toml -r src/atman/                    # security
pytest tests/ -v --cov=atman --cov-fail-under=90          # tests + coverage ≥90%
```

**Правила:**

- Не коммитить код с ошибками линтера, type checker или security linter
- Новые функции и методы должны иметь аннотации типов
- При обращении к результату, который может быть `None` (например `get_fact()` → `FactRecord | None`), сначала проверить `assert ... is not None` или `if ... is not None`
- Если инструмент выдаёт ложное срабатывание на существующем паттерне — добавить исключение в конфигурацию `pyproject.toml`, а не игнорировать ошибку
- Все проверки запускаются одной командой: `make check`

### Definition of Demo (substantive features)

For any change that introduces a **new user-visible behavior**, **CLI surface**, or **work-package-sized feature**, the same PR must include a **reproducible demo path** (see `docs/development/DEVELOPMENT_STANDARD.md`, *Definition of Demo*):

1. **Feature narrative** — work package under `docs/development/work-packages/` and/or paired guides under `docs/features/<slug>/` (e.g. [`docs/features/factual-memory/README.md`](docs/features/factual-memory/README.md), [`docs/features/experience-store/README.md`](docs/features/experience-store/README.md), [`docs/features/reflection-engine/README.md`](docs/features/reflection-engine/README.md), [`docs/features/session-manager/README.md`](docs/features/session-manager/README.md) + `README-ru.md`).
2. **Runnable scenario** — e.g. `make demo-factual`, `make demo-experience`, `make demo-reflection`, `make demo-session`, or `python3 src/demo*.py`, documented here and in the PR template. Console output for demos must use **Rich** via **`atman.term`** (see *Пользовательский вывод в терминале (Rich)* above).
3. **Fixtures** — at least one minimal valid input under `fixtures/` when the flow needs sample data.
4. **Tests** — invariants illustrated by the demo must be covered by `pytest`.

Cloud agents only see repo files: put demo instructions in **this file**, the **PR template**, and **Makefile** / scripts — not only in local Cursor rules.

### System Map — поддержание карты системы

`docs/architecture/SYSTEM_MAP.md` (+ парный `SYSTEM_MAP-ru.md`) — структурированный
инвентарь кодовой базы: модули, интеграции, пользовательские сценарии, edge cases,
известные регрессии. Карта используется для планирования покрытия тестами и для
быстрой навигации по системе.

**Карта обязана обновляться вместе с кодом — в том же PR**, если изменение:

- добавляет, удаляет или переименовывает модуль (файл под `src/atman/`);
- добавляет или меняет публичный класс/функцию модуля;
- добавляет, удаляет или меняет порт (`core/ports/`) или адаптер (`adapters/`);
- меняет проводку сервиса (`core/services/`) — какой порт/адаптер используется;
- добавляет точку входа: CLI-команду, вкладку TUI, страницу веб-дашборда, демо;
- меняет или добавляет e2e-сценарий (запуск CLI, демо, прогон рефлексии и т.п.);
- добавляет валидацию входа, защиту от дублей, обработчик парсинга JSON/JSONL,
  governance-проверку или поведение при конкуренции (закрывает «GAP» из §4 карты);
- чинит регрессию или известный баг (запись в §5 + regression-тест в `tests/`).

**Тесты — по карте.** Новые тесты должны быть привязаны к соответствующему разделу:

- **§1 Модули** → unit-тесты на нормальный путь, граничные случаи и ошибки;
- **§2 Интеграции** → integration-тесты на каждую связку (сервис↔порт, CLI↔сервис,
  demo↔реальные объекты, цепочка рефлексии);
- **§3 Сценарии** → system/e2e-тесты на A–G (или новый сценарий, если добавили);
- **§4 Edge cases** → закрыть GAP'ы из §4.5;
- **§5 Регрессии** → закрепить тестом каждую найденную регрессию.

В описании PR явно укажите, какие пункты карты затронуты и какими тестами они
покрыты (см. шаблон `.github/pull_request_template.md`).

**Тесты-страховки агентной разработки.** Семь файлов в `tests/` фиксируют
ключевые контракты системы и обязаны обновляться в том же PR при следующих
изменениях:

| Изменение в коде | Какой тест расширить |
|------------------|----------------------|
| Новый метод в порту `core/ports/state_store.py` | `test_state_store_contract.py` — добавить тест |
| Новый адаптер `StateStore` (например, in-memory) | `test_state_store_contract.py` — добавить параметр в `@pytest.fixture(params=[...])` |
| Переименовано/удалено поле в Pydantic-модели (`Identity`, `ExperienceRecord`, `NarrativeDocument`, `Eigenstate`, `FactRecord`) | `test_serialization_roundtrip.py` + `test_golden_schema.py` — обновить inline-фикстуру |
| Новая CLI-команда (`cli_*.py`) | `test_cli_all_commands.py` — добавить тест успеха + ошибки |
| Изменение пути или формата файла стораджа | `test_cli_roundtrip.py` — обновить ассерт на путь/структуру |
| Новый бизнес-инвариант (например, новое правило для salience, идемпотентности) | `test_domain_invariants.py` — добавить тест |
| Изменение цепочки сценариев §3 A–G | `test_e2e_full_cli.py` — обновить шаги |

**Двуязычная синхронизация:** правки сначала в `SYSTEM_MAP.md` (английский —
канонический), затем синхронизация в `SYSTEM_MAP-ru.md`. То же правило, что и
для пар README / MANIFEST / SYSTEM.

### Полезные заметки

- Изменили **`README.md`** → сначала обновите **`README-ru.md`**, затем **`make sync-site-content`** (копии `README.md` и `README-ru.md` в **`docs/content/`** перезаписываются). Аналогично держите пары в актуальном виде для **`MANIFEST*`** и **`SYSTEM*`**, затем тот же `make sync-site-content`.
- Изменили **`docs/architecture/SYSTEM_MAP.md`** → синхронизируйте **`SYSTEM_MAP-ru.md`** (правило то же, что и для пары `README`/`README-ru`); `make sync-site-content` карту не копирует.
- PR-шаблон находится в `.github/pull_request_template.md` — используйте его при создании PR.
- Pre-commit хуки настроены в `.pre-commit-config.yaml` (ruff, pyright, bandit).
- `Makefile` содержит все проверки: `make check` запускает полный набор, `make test-fast` — параллельные тесты.

## PLAYBOOK markers — when and how to add

When you implement code or write documentation that introduces a
**generalizable engineering pattern** — a solution applicable beyond
this project — you MUST add a PLAYBOOK marker.

### How to recognize a generalizable pattern

Apply the substitution test: rewrite your description without project-specific
terms ("reflection engine", "session manager", "atman", "experience store").
If the description still makes sense as a general engineering practice —
it's generalizable. Add a marker.

If the description becomes meaningless without project terms — it's
project-specific. Don't add a marker.

### Examples that DESERVE a marker

- "Idempotent long-running async operations via deterministic run keys computed from input parameters"
- "Append-only data structures with annotation layers instead of mutation for preserving authenticity of original records"
- "Optimistic concurrency for text documents using last-seen-revision tokens"
- "Port + adapter + deterministic mock as testable abstraction over LLM-dependent logic"
- "Outcome-coded events (`outcome=foo_ok` / `outcome=foo_failed reason=bar`) for control flow that needs offline analysis"
- "Two-tier affective regulation (acute level 1 + homeostasis level 2) for stateful systems"

### Examples that DON'T deserve a marker

- "Service uses asyncio" (standard library, not a pattern)
- "Tests use pytest fixtures" (framework usage, not a pattern)
- "Function returns Pydantic model" (idiomatic, not a pattern)
- "`ReflectionEvent` has `identity_snapshot_id` field" (project-specific data model)

### Marker format

See `docs/development/PLAYBOOK_MARKERS.md` for the syntax.

### Where to put markers

PUT THE MARKER NEXT TO THE CODE OR DOCUMENT THAT ILLUSTRATES THE PATTERN.
Not in a separate file. The marker should sit in the file where the
pattern is actually applied.

For Python: as a `# PLAYBOOK-START` / `# PLAYBOOK-END` comment block
immediately above the function, class, or module-level code that
implements the pattern.

For Markdown docs: as an HTML comment immediately before the section
that describes the pattern.

### When in doubt

If you're not sure whether something is generalizable — write a marker
with `status: draft`. The author will review and either promote to
`status: refined` or remove. Erring on the side of MORE markers is
preferred over missing real patterns.

DO NOT add markers for changes that are pure refactoring without
introducing new conceptual structure.

### Reference: known patterns awaiting markers

If you're working on a component listed in `reports/playbook-candidates.md`,
check whether the pattern is already marked at the relevant code location.
If not — add the marker.

---

## Local Agent Instructions

**For local Cursor agents** (not cloud agents), read the master prompt before starting any work:

📋 **Master Prompt**: [`.cursor/local-agent-master-prompt.md`](.cursor/local-agent-master-prompt.md)

The master prompt provides:

- Complete workflow and standards
- Links to all essential documentation
- Terminology discipline rules
- Architecture boundaries (Core vs Adapters)
- Definition of Done checklist
- Forbidden actions and common pitfalls

**Why separate from cloud instructions?**

- Cloud agents get `AGENTS.md` injected automatically
- Local agents need explicit guidance to follow the same standards
- Master prompt ensures local agents don't "go rogue" and follow project rules

**Before starting work, always**:

1. Read `.cursor/local-agent-master-prompt.md`
2. Review `docs/development/DEVELOPMENT_STANDARD.md`
3. Check relevant sections in `docs/architecture/SYSTEM.md`
