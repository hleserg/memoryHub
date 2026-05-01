# AGENTS.md

## Overview

Atman — проект психологического слоя для AI-агента, находящийся на стадии **прототипирования**. Содержит документацию (markdown-файлы, изображения, шаблоны) и реализованные компоненты Python-пакета `atman`: **Factual Memory Adapter** и **Experience Store** (work package 02).

## Cursor Cloud specific instructions

### Структура репозитория

- `src/atman/` — Python-пакет (модели, порты, адаптеры, CLI)
- `tests/` — юнит-тесты (pytest)
- `src/demo.py` — демо Factual Memory (`make demo-factual`; см. `docs/features/factual-memory/README.md`)
- `src/demo_experience_store.py` — воспроизводимый walkthrough Experience Store (временный JSONL; см. `docs/features/experience-store/README.md`)
- `pyproject.toml` — конфигурация проекта и зависимости
- `MANIFEST.md` — философский манифест проекта
- `docs/architecture/SYSTEM.md` — подробная архитектура системы (7 компонентов, режимы работы, протоколы)
- `docs/development/DEVELOPMENT_STANDARD.md` — стандарт разработки (терминология, границы, DoD)
- `docs/research/` — исследования (mem0, интеграции)
- `docs/ideas/` — идеи для будущих блоков
- `reports/sessions/` — шаблоны отчётов о сессиях
- `.github/` — шаблоны issue и PR (GitHub Actions не подключены; сайт — статика из `docs/` в Pages)
- `.cursor/` — инструкции для локальных агентов

### Lint / Test / Build / Run

- **Python ≥ 3.12** required (see `pyproject.toml`)
- **Install**: `pip install -e ".[dev]"`
- **Tests**: `pytest tests/ -v --cov=atman --cov-fail-under=90` (coverage ≥90%; см. `pytest tests/ --collect-only`)
- **Tests (parallel)**: `pytest tests/ -n auto` (pytest-xdist)
- **CLI (REPL)**: `python3 -m atman.cli`
- **Demo (facts)**: `make demo-factual` or `python3 src/demo.py`
- **Demo (Experience Store)**: `make demo-experience` or `python3 src/demo_experience_store.py`
- **Lint**: `ruff check src/ tests/` and `ruff format --check src/ tests/`
- **Type check**: `pyright src/ tests/` (standard mode, 0 errors)
- **Security**: `bandit -c pyproject.toml -r src/atman/`
- **Dependency audit**: `pip-audit`
- **All checks at once**: `make check` (lint + format + typecheck + security + tests)
- **Pre-commit**: configured in `.pre-commit-config.yaml` (ruff, pyright, bandit)
- No external services (databases, Docker, etc.) are required — storage is in-memory or file-based (JSONL)

### Gotchas

- Python ≥ 3.12, менеджер пакетов `uv`, build-система Hatchling
- PydanticAI + Anthropic (Claude), mem0, APScheduler — планируемые зависимости, пока не подключены
- Ruff настроен в `pyproject.toml` (`[tool.ruff]`); кириллица допускается (RUF001-003 отключены)
- Pyright настроен в `pyproject.toml` (`[tool.pyright]`), режим `standard`; все функции должны иметь аннотации типов
- Детали см. в `docs/architecture/SYSTEM.md`
- `pyproject.toml` specifies `ruff>=0.11.0`; the codebase has pre-existing lint/format/type-check issues on `main` (W293 whitespace, import sorting, pyright `reportArgumentType`). These are not regressions — do not block your work on fixing them unless your task explicitly requires it
- `cli_experience.py` is excluded from coverage (`omit` in `pyproject.toml` covers only `cli.py`); if coverage drops below 90%, check whether untested CLI code is the cause

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
- `MANIFEST.md` / `MANIFEST-ru.md`
- Feature walkthroughs: `docs/features/<feature-slug>/README.md` / `README-ru.md` — e.g. [`docs/features/factual-memory/README.md`](docs/features/factual-memory/README.md), [`docs/features/experience-store/README.md`](docs/features/experience-store/README.md)

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

1. **Feature narrative** — work package under `docs/development/work-packages/` and/or paired guides under `docs/features/<slug>/` (e.g. [`docs/features/factual-memory/README.md`](docs/features/factual-memory/README.md), [`docs/features/experience-store/README.md`](docs/features/experience-store/README.md) + `README-ru.md`).
2. **Runnable scenario** — e.g. `make demo-factual`, `make demo-experience`, or `python3 src/demo*.py`, documented here and in the PR template.
3. **Fixtures** — at least one minimal valid input under `fixtures/` when the flow needs sample data.
4. **Tests** — invariants illustrated by the demo must be covered by `pytest`.

Cloud agents only see repo files: put demo instructions in **this file**, the **PR template**, and **Makefile** / scripts — not only in local Cursor rules.

### Полезные заметки

- Изменили **`README.md`** → сначала обновите **`README-ru.md`**, затем **`make sync-site-content`** (копии `README.md` и `README-ru.md` в **`docs/content/`** перезаписываются). Аналогично держите пары в актуальном виде для **`MANIFEST*`** и **`SYSTEM*`**, затем тот же `make sync-site-content`.
- PR-шаблон находится в `.github/pull_request_template.md` — используйте его при создании PR.
- Pre-commit хуки настроены в `.pre-commit-config.yaml` (ruff, pyright, bandit).
- `Makefile` содержит все проверки: `make check` запускает полный набор, `make test-fast` — параллельные тесты.

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
