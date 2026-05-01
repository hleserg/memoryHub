# AGENTS.md

## Overview

Atman — проект психологического слоя для AI-агента, находящийся на стадии **прототипирования**. Содержит документацию (markdown-файлы, изображения, шаблоны) и первый реализованный компонент — **Factual Memory Adapter** (Python-пакет `atman`).

## Cursor Cloud specific instructions

### Структура репозитория

- `src/atman/` — Python-пакет (модели, порты, адаптеры, CLI)
- `tests/` — юнит-тесты (pytest)
- `src/demo.py` — демо-скрипт
- `pyproject.toml` — конфигурация проекта и зависимости
- `MANIFEST.md` — философский манифест проекта
- `docs/architecture/SYSTEM.md` — подробная архитектура системы (7 компонентов, режимы работы, протоколы)
- `docs/research/` — исследования (mem0, интеграции)
- `docs/ideas/` — идеи для будущих блоков
- `reports/sessions/` — шаблоны отчётов о сессиях
- `.github/` — шаблоны issue и PR

### Lint / Test / Build / Run

- **Python ≥ 3.12** required (see `pyproject.toml`)
- **Install**: `pip install -e ".[dev]"`
- **Tests**: `pytest tests/ -v` (49 tests, all passing)
- **CLI (REPL)**: `python3 -m atman.cli`
- **Demo**: `python3 src/demo.py`
- **Lint**: `ruff check src/ tests/` and `ruff format --check src/ tests/`
- No external services (databases, Docker, etc.) are required — storage is in-memory or file-based (JSONL)
- No CI/CD workflows yet

### Gotchas

- Python ≥ 3.12, менеджер пакетов `uv`, build-система Hatchling
- PydanticAI + Anthropic (Claude), mem0, APScheduler — планируемые зависимости, пока не подключены
- Ruff настроен в `pyproject.toml` (`[tool.ruff]`); кириллица допускается (RUF001-003 отключены)
- Детали см. в `docs/architecture/SYSTEM.md`

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

### Полезные заметки

- PR-шаблон находится в `.github/pull_request_template.md` — используйте его при создании PR.
- Нет pre-commit хуков, lint-staged, или CI workflows.
