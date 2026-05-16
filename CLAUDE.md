# Atman — инструкции для Claude / Cowork

## Что такое этот проект

Atman — психологический runtime-слой для AI-агентов (`C:\projects\atman`). Цель: дать агенту непрерывную идентичность, memory из первых рук и рефлексию. Не замена LLM — слой поверх него.

**Нижний агент действует. Atman существует.**

## Перед любой работой с кодом

Прочитай в таком порядке:
1. `AGENTS.md` — структура репо, стек, статус
2. `docs/development/DEVELOPMENT_STANDARD.md` — канонические термины, архитектурные границы
3. `docs/content/SYSTEM.md` — 7 компонентов системы
4. `MANIFEST.md` — философское основание

## Канонические термины (только они)

`Fact`, `Experience`, `Reflection`, `Identity`, `Narrative`, `Eigenstate`, `Uncertainty`, `Skill`, `Session`, `PersonalitySnapshot`

❌ Запрещено: `memory_item`, `note`, `profile`, `persona`, `soul_state`  
❌ Запрещено смешивать: Fact ≠ Experience ≠ Reflection ≠ Identity ≠ Skill ≠ Narrative

## Архитектурные границы

- **Core** (`src/atman/core/`) — доменная логика, без зависимостей от mem0/LLM/файлов напрямую
- **Adapters** (`src/atman/adapters/`) — translation layer между Core и внешними системами
- **Eval** (`src/atman/eval/`) — только eval-код, optional dependency `pip install atman[eval]`
- Core зависит от **портов** (interfaces), не от конкретных реализаций
- `datetime.now()` в domain logic → заменить на Clock port

## Запрещено

- Создавать domain terms без добавления в `DEVELOPMENT_STANDARD.md`
- Добавлять внешние сервисы без ADR
- Редактировать русские доки без обновления английских оригиналов
- Хранить identity/principles в `.env`
- Реализовывать сложные фичи пока не работает minimal runtime path
- Raw `print()` в демо/CLI коде — использовать Rich через `atman.term`

## Текущий статус (май 2026)

**Реализовано:** Factual Memory, Experience Store, Identity Store, Reflection Engine (micro/daily/deep), Session Manager (базовый), Affective Regulation, Web Dashboard, TUI, CLI

**Не реализовано:** Reality Anchor, Proactive Engine, Skill Manager, Background Scheduler

**Открытые issues:** E2E-01/02, MODEL-01/02/03, ANCHOR-01/02/03, SCHED-01/02/03  
→ см. `docs/development/work-packages/ISSUE_BACKLOG.md`

## Priority order реализации

1. Core models + ports + fake adapters
2. PersonalitySnapshot builder
3. Minimal session start/end
4. Narrative recent layer
5. File/local StateStore со schema versions
6. MemoryBackend adapter → mem0
7. CLI doctor/health/export/import
8. OpenClaw IntegrationAdapter
9. Micro reflection → Daily/Deep reflection
10. Reality Anchor + Affective Regulation
11. Skill Manager → Ambient/Proactive → Admin Panel

## Definition of Done

- [ ] Canonical terminology
- [ ] Core не зависит от mem0/LLM напрямую
- [ ] Запускается локально без внешних сервисов
- [ ] Тесты для core invariants
- [ ] Schema version у persistent структур
- [ ] Описан degraded mode
- [ ] Обновлены оба языка (EN + RU) для билингвальных файлов

## Epic файлы

Epics E-1, E0, E1..E20 уже существуют. Следующий: **E21**.  
Перед написанием — проверить актуальный номер через GitHub issues.  
Формат: `E<NUM>_<kebab-name>.md`, em-dash `—` в заголовке (не дефис!).

## Полезные команды

```bash
# Установка
uv venv && source .venv/bin/activate && uv pip install -e ".[dev]"

# Тесты
uv run pytest tests/ -v

# Демо
make demo-factual
make demo-experience

# Проверка
make check
```

## Notion

Issues page: `https://www.notion.so/issues-35d0c905e62680f49766f8d313905abf`  
Сохранять epic issues туда после генерации.
