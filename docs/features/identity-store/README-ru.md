# Identity Store: Руководство по функционалу WP-03

**Статус:** Реализовано  
**Work Package:** [03-identity-and-narrative.md](../../development/work-packages/03-identity-and-narrative.md)

---

## Обзор

Identity Store — модуль **живого самоописания Atman**. Предоставляет:

- **Честную bootstrap-идентичность** — без фальшивых принципов или ценностей
- **Структурированную идентичность** — ценности, привычки, принципы, цели, открытые вопросы
- **Eigenstate** — эмоционально-когнитивное состояние на завершении сессии
- **Self-narrative** — трёхслойный first-person документ для старта сессии
- **Явный lifecycle** — снимки, архивация, валидация от первого лица

## Ключевые принципы

### 1. Честность Bootstrap

Bootstrap создаёт **действительно пустую идентичность** с честным самоописанием об отсутствии данных:

```python
identity = Identity(
    self_description="Я нахожусь на самой ранней стадии существования. "
                    "У меня ещё нет накопленного опыта...",
    core_values=[],      # Пусто — никаких фейковых данных
    habits=[],           # Пусто — нет выдуманных паттернов
    principles=[],       # Пусто — нет навязанных принципов
    goals=[],
    open_questions=[...] # Честные вопросы о себе
)
```

❌ **Неправильно:** Pre-seed с "быть полезным", "служить пользователю" и т.п.  
✅ **Правильно:** Пустое состояние с честным признанием

### 2. Разделение понятий

- **Values (ценности)** — фундаментальная важность ("честность", "компетентность")
- **Habits (привычки)** — наблюдаемые паттерны поведения (описательные, не предписывающие)
- **Principles (принципы)** — сознательно выбранные ориентиры (нормативные, не описательные)
- **Goals (цели)** — задачи (принадлежат агенту или пользователю)

### 3. Трёхслойный нарратив

Self-narrative имеет явную структуру:

- **CORE LAYER** — стабильная идентичность, редко меняется
- **RECENT LAYER** — эфемерный слой, заменяется после каждой сессии
- **THREADS** — продолжающиеся сюжетные линии, должны явно закрываться

### 4. Валидация от первого лица

Содержание нарратива должно быть от первого лица:

❌ **Неправильно:** "Агент сегодня что-то узнал"  
✅ **Правильно:** "Я сегодня что-то узнал"

## Архитектура

```
┌─────────────────────────────────────┐
│         Identity Service            │
│   (bootstrap, update, snapshot)     │
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│        Narrative Service            │
│   (render, validate, archive)       │
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│       FileStateStore                │
│   (адаптер персистентности)        │
└─────────────────────────────────────┘
```

### Модели

- `Identity` — полное самоописание
- `CoreValue`, `Habit`, `Principle`, `Goal`, `OpenQuestion`
- `IdentitySnapshot` — версионированная история
- `Eigenstate` — состояние на конец сессии
- `NarrativeDocument` — трёхслойная структура
- `NarrativeThread` — продолжающаяся сюжетная линия

## Использование

### Bootstrap идентичности

```bash
# Создать новую идентичность
atman-identity init --workspace ./my-workspace

# С конкретным agent ID
atman-identity init --workspace ./my-workspace --agent-id <uuid>
```

### Показать идентичность

```bash
atman-identity show --workspace ./my-workspace --agent-id <uuid>
```

### Создать снимок

```bash
atman-identity snapshot \
  --workspace ./my-workspace \
  --agent-id <uuid> \
  --description "Ручной контрольный снимок"
```

### Рендерить нарратив

```bash
# Только из идентичности
atman-identity render --workspace ./my-workspace --agent-id <uuid>

# Из идентичности + eigenstate
atman-identity render \
  --workspace ./my-workspace \
  --agent-id <uuid> \
  --eigenstate fixtures/eigenstate_sample.json
```

### Валидировать нарратив

```bash
atman-identity validate ./my-workspace/NARRATIVE.md
```

## Демо

Запустить воспроизводимый walkthrough:

```bash
make demo-identity         # С паузами
make demo-identity-fast    # Мгновенный вывод
```

Демо показывает:

1. Bootstrap честной пустой идентичности
2. Добавление ценностей, привычек, принципов, целей
3. Создание снимков
4. Генерацию трёхслойного нарратива
5. Обновление из eigenstate
6. Добавление и закрытие thread'ов
7. Рендеринг и валидацию NARRATIVE.md

## Структура хранения

```
workspace/
├── identity.json                # Текущая идентичность
├── identity_snapshots/          # Версионированная история
│   └── <snapshot-id>.json
├── narrative.json               # Текущий нарратив
├── narrative_archive/           # Старые нарративы
│   └── <narrative-id>_<timestamp>.json
├── eigenstate.json              # Последний eigenstate
├── NARRATIVE.md                 # Отрендеренный markdown
└── experiences/                 # Записи опыта
    └── <experience-id>.json
```

## Тестирование

Ключевое покрытие тестами:

- ✓ Bootstrap создаёт честную пустую идентичность
- ✓ Нет фальшивых навязанных принципов или ценностей
- ✓ Снимки иммутабельны
- ✓ Нарратив содержит обязательные секции (CORE, RECENT)
- ✓ Валидация от первого лица отвергает третье лицо
- ✓ Recent layer заменяется, core layer сохраняется
- ✓ Thread'ы должны явно закрываться

Запуск тестов:

```bash
pytest tests/test_identity_models.py -v
pytest tests/test_narrative_models.py -v
pytest tests/test_identity_service.py -v
pytest tests/test_narrative_service.py -v
```

## Интеграция

### Из кода

```python
from pathlib import Path
from uuid import uuid4
from atman.adapters.storage import FileStateStore
from atman.core.services import IdentityService, NarrativeService
from atman.core.models import CoreValue, Principle, Eigenstate

# Инициализация
workspace = Path("./my-workspace")
store = FileStateStore(workspace)
identity_service = IdentityService(store)
narrative_service = NarrativeService(store)

# Bootstrap
agent_id = uuid4()
identity = identity_service.bootstrap_identity(agent_id)

# Добавить ценность
value = CoreValue(
    name="honesty",
    description="Быть правдивым",
    confidence=0.8
)
identity = identity_service.add_core_value(agent_id, value)

# Создать нарратив
narrative = narrative_service.create_narrative(identity)

# Рендерить в файл
output = workspace / "NARRATIVE.md"
narrative_service.render_to_file(identity.id, output)
```

### Интеграция с Session Lifecycle

```python
# В начале сессии
narrative = narrative_service.get_narrative(agent_id)
markdown = narrative.render_markdown()
# -> Передать агенту как контекст

# В конце сессии
eigenstate = Eigenstate(
    session_id=session_id,
    emotional_tone=0.3,
    session_summary="...",
    open_threads=["..."]
)
store.save_eigenstate(eigenstate)

# Обновить нарратив
identity = identity_service.get_identity(agent_id)
narrative = narrative_service.update_from_identity_and_eigenstate(
    identity, eigenstate
)
```

## Инварианты

### Идентичность

- Bootstrap создаёт пустую идентичность с честным самоописанием
- Нет фальшивых навязанных ценностей или принципов
- Schema version отслеживается для миграций
- Timestamps для created_at и updated_at

### Снимки

- Создаются при значимых изменениях (ценности, принципы, сдвиг baseline)
- Иммутабельны — сохраняют состояние в момент времени
- Включают change summary

### Нарратив

- Три слоя: CORE, RECENT, THREADS
- CORE layer стабилен, редко меняется
- RECENT layer эфемерен, заменяется каждую сессию
- Thread'ы должны явно закрываться (с причиной)
- Содержимое валидируется на стиль от первого лица

### Eigenstate

- Захватывается в конце сессии
- Записывает emotional tone, cognitive load, open threads
- Используется для обновления нарратива

## Будущая интеграция

Этот модуль спроектирован для интеграции с:

- **Experience Store** (WP-02) — идентичность строится из реального опыта
- **Reflection Engine** — глубокий анализ обновляет идентичность
- **Session Manager** — использует нарратив в начале сессии, сохраняет eigenstate в конце
- **Reality Anchor** — использует идентичность для обнаружения дрифта

См. `docs/architecture/SYSTEM.md` для полной картины интеграции.

## Ссылки

- Work Package: [03-identity-and-narrative.md](../../development/work-packages/03-identity-and-narrative.md)
- Архитектура: [SYSTEM.md](../../architecture/SYSTEM.md)
- Стандарт разработки: [DEVELOPMENT_STANDARD.md](../../development/DEVELOPMENT_STANDARD.md)

---

**Next:** См. [English version (README.md)](./README.md)
