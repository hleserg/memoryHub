# Experience Store — рабочий пакет 02

> **English:** [README.md](README.md)

Experience Store — архив пережитого опыта **от первого лица** для агента Atman. Здесь хранятся не факты и не анализ, а *то, что агент реально пережил*.

## Демо одной командой

После `pip install -e ".[dev]"` или `uv pip install -e ".[dev]"` (см. **`AGENTS.md`**, *uv — рекомендуемый workflow*) из корня репозитория:

```bash
make demo-experience
```

Эквивалент: `python3 src/demo_experience_store.py` или `uv run python src/demo_experience_store.py`. Используется **временный** JSONL-файл и [`fixtures/experience1_competence_challenge.json`](../../../fixtures/experience1_competence_challenge.json); каталог `~/.atman` не изменяется.

Интерактивный CLI (по умолчанию пишет в `~/.atman/experiences.jsonl`): `atman-experience`.

## Обзор

Experience Store включает такие части архитектуры:

- **Доменные модели** (`atman/core/models/experience.py`): сущности опыта
- **Порт StateStore** (`atman/core/ports/state_store.py`): интерфейс хранилищ
- **Адаптер JSONL** (`atman/adapters/storage/jsonl_experience_store.py`): файловая персистентность
- **In-memory адаптер** (`atman/adapters/storage/in_memory_experience_store.py`): для тестов
- **Сервис опыта** (`atman/core/services/experience_service.py`): бизнес-логика
- **CLI** (`atman/cli_experience.py`): интерфейс командной строки

## Ключевые принципы

### 1. Только опыт первого лица

Окраска опыта задаётся **в реальном времени** в сессии, а не задним числом. Если эмоциональную окраску в моменте зафиксировать нельзя, честный вариант — `incomplete_coloring: true`.

**Запрещено:** ретроспективно «угадывать» эмоциональную окраску.

### 2. Неизменяемость исходного опыта

Исходные `key_moments` после записи **не меняются**. Они отражают, что произошло и как это ощущалось *тогда*.

**Разрешено:** добавлять `reframing_notes` — новые ракурсы без переписывания оригинала.

### 3. Затухание salience

Без обращения к воспоминанию яркость падает. `salience` отражает текущую «яркость» и со временем убывает с учётом:

- дней с последнего доступа;
- эмоциональной интенсивности;
- глубины (profound затухает медленнее).

**Важно:** расчёт salience **не** перезаписывает сохранённое значение в записи.

## Доменные модели

### EmotionalDepth

```python
class EmotionalDepth(str, Enum):
    SURFACE = "surface"      # Noticed but didn't affect deeply
    MEANINGFUL = "meaningful" # Touched values or principles
    PROFOUND = "profound"     # Changed something fundamental
```

### FeltSense

Эмоциональная окраска момента:

```python
FeltSense(
    emotional_valence=0.3,      # -1.0 (negative) to +1.0 (positive)
    emotional_intensity=0.7,    # 0.0 (barely noticed) to 1.0 (overwhelming)
    depth=EmotionalDepth.MEANINGFUL
)
```

### KeyMoment

Значимый момент внутри сессии:

```python
KeyMoment(
    what_happened="User asked a challenging question",
    when=datetime.now(timezone.utc),
    how_i_felt=felt_sense,
    why_it_matters="Tests my competence",
    values_touched=["honesty", "competence"],
    principles_confirmed=["admit_uncertainty"],
    principles_questioned=[],
    what_changed="Became more aware of my limitations"
)
```

### SessionExperience

Полный опыт одной сессии:

```python
SessionExperience(
    session_id=uuid4(),
    key_moments=[moment1, moment2],
    importance=0.7,
    salience=0.8,
    incomplete_coloring=False,
    reframing_notes=[]
)
```

## Установка

```bash
# Install in development mode
pip install -e .

# Or install with dev dependencies
pip install -e ".[dev]"
```

## Использование

### Команды CLI

Запуск CLI:

```bash
python -m atman.cli_experience
```

Или модуль напрямую:

```bash
python src/atman/cli_experience.py
```

#### Добавить опыт

```bash
atman> experience add fixtures/experience1_competence_challenge.json
```

#### Получить опыт

```bash
atman> experience get <experience_id>
```

#### Добавить reframing note

```bash
atman> experience reflect <experience_id> "Looking back, this was a growth moment" growth
```

#### Поиск опытов

```bash
# По сессии
atman> experience search session <session_id>

# По задетым ценностям
atman> experience search values honesty,competence

# По глубине
atman> experience search depth profound

# Недавние
atman> experience search recent 10
```

#### Превью затухания salience

```bash
atman> experience decay-preview <experience_id> 30
```

### Программный доступ

```python
from atman.adapters.storage import JsonlExperienceStore
from atman.core.services import ExperienceService
from atman.core.models import SessionExperience, KeyMoment, FeltSense

# Initialize
store = JsonlExperienceStore(".atman/experiences.jsonl")
service = ExperienceService(store)

# Create experience
felt = FeltSense(
    emotional_valence=0.3,
    emotional_intensity=0.7,
    depth="meaningful"
)
moment = KeyMoment(
    what_happened="Something significant happened",
    how_i_felt=felt,
    why_it_matters="It touched my values"
)
experience = SessionExperience(
    session_id=uuid4(),
    key_moments=[moment]
)

# Store it
record = service.create_experience(experience)

# Retrieve it
retrieved = service.get_experience(record.experience.id)

# Add reframing note
service.add_reframing_note(
    experience_id=record.experience.id,
    reflection="New perspective gained",
    reflection_type="growth"
)

# Search by values
results = service.search_by_values(["honesty", "competence"])

# Calculate current salience
current_salience = service.calculate_current_salience(record.experience.id)
```

## Тесты

Все тесты:

```bash
pytest tests/
```

Отдельные файлы:

```bash
pytest tests/test_experience_models.py
pytest tests/test_experience_service.py
pytest tests/test_experience_stores.py
```

С покрытием:

```bash
pytest --cov=atman.core.models.experience --cov=atman.core.services.experience_service
```

## Архитектура

### Core и Adapter

**Core** (`atman/core/`):
- доменные модели (FeltSense, KeyMoment, SessionExperience и др.);
- порты (интерфейс StateStore);
- сервисы (ExperienceService);
- **без** прямых зависимостей от конкретного хранилища, LLM и внешних сервисов.

**Adapters** (`atman/adapters/`):
- реализация JSONL;
- in-memory для тестов;
- **реализуют** порт StateStore из Core.

Так доменная логика остаётся тестируемой и переносимой.

### Граница хранилища

Порт `StateStore` задаёт контракт:

```python
class StateStore(ABC):
    @abstractmethod
    def create_experience(self, record: ExperienceRecord) -> ExperienceRecord: ...

    @abstractmethod
    def get_experience(self, experience_id: UUID) -> ExperienceRecord | None: ...

    @abstractmethod
    def add_reframing_note(self, experience_id: UUID, note: ReframingNote) -> ExperienceRecord | None: ...

    # ... more methods
```

Core видит **только этот интерфейс**, не детали реализации.

## Инварианты, закрытые тестами

1. ✅ **Валентность** в диапазоне -1.0 … 1.0
2. ✅ **Интенсивность** в диапазоне 0.0 … 1.0
3. ✅ **Глубина** — одна из: surface, meaningful, profound
4. ✅ **Исходные key_moments неизменяемы** — нет методов перезаписи
5. ✅ **Reframing только дополнение** — оригинал не подменяется
6. ✅ **Расчёт salience не меняет сохранённое значение**
7. ✅ **Доступ обновляет last_accessed_at и access_count**
8. ✅ **Profound / высокая интенсивность — медленнее decay**
9. ✅ **Поиск по session_id, values_touched, depth, диапазону дат**
10. ✅ **incomplete_coloring — явный флаг, не значение по умолчанию**

## Без внешних сервисов

Experience Store **не требует** внешних сервисов:

- **JSONL** — локальный файл;
- **In-memory** — для тестов;
- **без вызовов LLM** — данные задаются явно;
- **без mem0 и векторного поиска** — файл или память.

Путь хранилища по умолчанию: `~/.atman/experiences.jsonl`

## Персистентные данные

### Что создаётся

- **experiences.jsonl**: одна JSON-строка на опыт
- **schema_version**: в каждой записи

### Пример записи

```json
{
  "schema_version": "1.0.0",
  "experience": {
    "id": "123e4567-e89b-12d3-a456-426614174000",
    "session_id": "a1b2c3d4-e5f6-4a5b-8c9d-0e1f2a3b4c5d",
    "timestamp": "2026-04-30T10:30:00Z",
    "key_moments": [...],
    "importance": 0.7,
    "salience": 0.8,
    "incomplete_coloring": false,
    "reframing_notes": []
  }
}
```

## Стратегия миграций

При смене схемы:

1. Увеличить `schema_version` у новых записей
2. Скрипт миграции:
   - читает все опыты;
   - преобразует старый формат;
   - пишет с новым schema_version
3. По возможности сохранять обратную совместимость

Пример (при необходимости):

```python
def migrate_1_0_to_2_0(storage_path):
    """Migrate from schema 1.0.0 to 2.0.0."""
    old_records = read_jsonl(storage_path)
    new_records = []

    for record in old_records:
        if record.schema_version == "1.0.0":
            # Transform record
            new_record = transform(record)
            new_record.schema_version = "2.0.0"
            new_records.append(new_record)
        else:
            new_records.append(record)

    write_jsonl(storage_path, new_records)
```

## Примеры

Каталог `fixtures/`:

- `experience1_competence_challenge.json` — meaningful, вызов компетентности
- `experience2_value_conflict.json` — profound, конфликт ценностей
- `experience3_surface_technical.json` — surface, рутинная помощь

## Что не входит в scope

По границам work package **не реализовано**:

- ❌ генерация FeltSense из сырых логов (вход задаётся явно)
- ❌ Reflection Engine в runtime
- ❌ Session Manager в runtime
- ❌ векторный поиск
- ❌ LLM для анализа
- ❌ автоматическая эмоциональная окраска

Это относится к другим пакетам.

## Связанные документы

- Техзадание: [`../../development/work-packages/02-experience-store.md`](../../development/work-packages/02-experience-store.md)
- Архитектура: [`../../architecture/SYSTEM.md`](../../architecture/SYSTEM.md) (разделы про Experience Store)
- Стандарт разработки: [`../../development/DEVELOPMENT_STANDARD.md`](../../development/DEVELOPMENT_STANDARD.md)

## Лицензия

См. корень репозитория.
