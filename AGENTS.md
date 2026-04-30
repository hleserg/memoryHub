# AGENTS.md

## Overview

Atman — проект психологического слоя для AI-агента. Репозиторий находится на стадии **прототипирования**. Реализован первый компонент — **Factual Memory Adapter** (Python-пакет с CLI, моделями, адаптерами и тестами). Остальная часть репозитория — архитектурная документация.

## Cursor Cloud specific instructions

### Структура репозитория

- `src/atman/` — исходный код Python-пакета (Factual Memory Adapter)
- `tests/` — unit-тесты (pytest, 49 тестов)
- `pyproject.toml` — конфигурация пакета и зависимостей
- `src/demo.py` — демо-скрипт для проверки работы адаптера
- `MANIFEST.md` — философский манифест проекта
- `docs/architecture/SYSTEM.md` — подробная архитектура системы (7 компонентов, режимы работы, протоколы)
- `docs/research/` — исследования (mem0, интеграции)
- `docs/ideas/` — идеи для будущих блоков
- `reports/sessions/` — шаблоны отчётов о сессиях
- `.github/` — шаблоны issue и PR

### Lint / Test / Build / Run

- **Установка**: `pip install -e ".[dev]"` (editable mode с dev-зависимостями)
- **Тесты**: `pytest tests/ -v` (49 тестов, ~0.3s)
- **Демо**: `python3 src/demo.py` (InMemoryBackend + FileBackend)
- **CLI REPL**: `python3 -m atman.cli` (интерактивный режим — add/get/search/link/recent)
- **Линтер**: на данный момент не настроен (нет ruff/flake8/mypy в зависимостях)
- **CI/CD**: GitHub Actions — Pages deploy + Cursor issue intake (не влияют на локальную разработку)

### Стек

- Python ≥ 3.12, build-система Hatchling, src-layout
- Зависимости: `pydantic>=2.0.0`
- Dev-зависимости: `pytest>=7.0.0`, `pytest-asyncio>=0.21.0`
- Планируемые (ещё не реализованы): PydanticAI + Anthropic, mem0, APScheduler
- Детали архитектуры см. в `docs/architecture/SYSTEM.md`

### Gotchas

- CLI парсит аргументы через `split()` — строки с пробелами в кавычках разбиваются на отдельные слова (content и source обрабатываются как отдельные args)
- FileBackend хранит данные в `~/.atman/facts.jsonl` — файл создаётся автоматически
- Внешних сервисов (БД, API) нет — всё локальное (in-memory или JSONL)

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
