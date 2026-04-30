# AGENTS.md

## Overview

Atman — проект психологического слоя для AI-агента. Репозиторий находится на стадии **прототипирования**. 

**Текущее состояние:**
- ✅ Factual Memory Adapter реализован (v0.1.0)
- ✅ 49 unit тестов, все проходят
- ✅ Два бэкенда: InMemory и File (JSONL)
- ⏳ Experience Store, Identity Store, Reflection Engine — в очереди

## Cursor Cloud specific instructions

### Структура репозитория

- `MANIFEST.md` — философский манифест проекта
- `docs/architecture/SYSTEM.md` — подробная архитектура системы (7 компонентов, режимы работы, протоколы)
- `docs/research/` — исследования (mem0, интеграции)
- `docs/ideas/` — идеи для будущих блоков
- `reports/sessions/` — шаблоны отчётов о сессиях
- `.github/` — шаблоны issue и PR

### Lint / Test / Build / Run

**Установка и проверка:**

```bash
# Установить проект в dev режиме
pip install -e .

# Запустить все тесты (49 тестов)
pytest tests/ -v

# Запустить CLI в интерактивном режиме
python3 -m atman.cli

# Проверить импорты
python3 -c "from atman.factual_memory import FactualMemory, InMemoryBackend, FileBackend"
```

**Текущие требования:**
- Python ≥ 3.12 ✅
- pip (для установки) ✅
- pytest (для тестов) ✅

**Планируемые требования:**
- Менеджер пакетов `uv` (пока не требуется, но рекомендуется для будущего)
- PydanticAI, mem0, APScheduler (будут добавлены по мере реализации компонентов)

**Линтеры и форматтеры:**
- Пока не настроены
- CI/CD workflows отсутствуют

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
- **Настройка окружения для Cloud Agents:** См. `docs/development/CLOUD_AGENT_ENVIRONMENT.md` для рекомендаций по предустановке инструментов и зависимостей.
