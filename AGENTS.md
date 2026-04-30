# AGENTS.md

## Overview

Atman — документационный проект, описывающий архитектуру психологического слоя для AI-агента. Репозиторий находится на стадии **прототипирования** и содержит только документацию (markdown-файлы, изображения, шаблоны).

Исполняемого кода, зависимостей, тестов и сборочных конфигураций пока нет.

## Cursor Cloud specific instructions

### Структура репозитория

- `MANIFEST.md` — философский манифест проекта
- `docs/architecture/SYSTEM.md` — подробная архитектура системы (7 компонентов, режимы работы, протоколы)
- `docs/research/` — исследования (mem0, интеграции)
- `docs/ideas/` — идеи для будущих блоков
- `reports/sessions/` — шаблоны отчётов о сессиях
- `.github/` — шаблоны issue и PR

### Lint / Test / Build / Run

На текущем этапе в репозитории нет:
- исполняемого кода (Python, JS, и т.д.)
- файлов зависимостей (`pyproject.toml`, `package.json`, `requirements.txt`)
- тестов или линтеров
- CI/CD workflows

Работа с репозиторием ограничена редактированием markdown-документации.

### Планируемый стек (из архитектурных документов)

Когда код появится, проект будет использовать:
- Python ≥ 3.12, менеджер пакетов `uv`, build-система Hatchling
- PydanticAI + Anthropic (Claude), mem0, APScheduler
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
