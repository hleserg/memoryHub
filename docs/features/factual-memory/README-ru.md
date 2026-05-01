# Atman — Factual Memory Adapter

> **English:** [README.md](README.md)

Минимальный, запускаемый слой factual memory для AI-агента. Предоставляет единый порт для записи, чтения и поиска проверяемых фактов без интерпретаций.

## Демо одной командой

Из корня репозитория (после `pip install -e ".[dev]"`):

```bash
make demo-factual
```

Эквивалент: `python3 src/demo.py` — демонстрация InMemory и FileBackend на файле `/tmp/atman_demo_facts.jsonl` (файл удаляется в конце).

Интерактивный CLI (по умолчанию `~/.atman/facts.jsonl`): `python3 -m atman.cli` или установленная команда `atman`.

## Обзор

Factual Memory Adapter - это фундамент системы памяти Atman. Он:

- Хранит **только факты и связи** (без эмоциональной окраски)
- Явно отделяет `fact.content` от любых выводов
- Обеспечивает валидацию (запрещает пустой content/source)
- Расширяем под embeddings/graph memory (но не требует их)

## Установка

Требования: Python ≥ 3.12

```bash
# Клонировать репозиторий
git clone https://github.com/hleserg/atman.git
cd atman

# Рекомендуется uv: окружение и установка
uv venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
uv pip install -e ".[dev]"

# Запуск без активации venv: uv run pytest tests/ -v, uv run python src/demo.py
# Fallback: pip install -e ".[dev]"
```

Подробнее про **uv** (`uv run`, `uv pip` и т.д.) — в корневом **`AGENTS.md`**, раздел *uv — рекомендуемый workflow*.

## Быстрый старт

### CLI (интерактивный режим)

```bash
atman
```

Примеры команд:

```
atman> add "Пользователь попросил реализовать память" session_1 task request
✓ Факт добавлен

atman> search "пользователь" --tags task
✓ Найдено фактов: 1

atman> recent 5
✓ Последние 5 фактов

atman> help
# Полная справка по командам
```

### Использование в коде

#### In-Memory Backend (для тестов)

```python
from atman.adapters.memory import InMemoryBackend
from atman.core.models import FactRecord

# Создать backend
memory = InMemoryBackend()

# Добавить факт
fact = FactRecord(
    content="Пользователь попросил реализовать factual memory",
    source="session_2024_01_15",
    tags=["task", "request"]
)
added = memory.add_fact(fact)

# Получить факт
retrieved = memory.get_fact(added.id)
print(retrieved.content)

# Искать по тексту
results = memory.search(query="пользователь")

# Искать по тегам
results = memory.search(tags=["task"])

# Создать связь
fact2 = memory.add_fact(FactRecord(
    content="Задача выполнена",
    source="session_2024_01_15"
))
memory.link(added.id, fact2.id, "led_to")

# Получить последние факты
recent = memory.list_recent(limit=10)
```

#### File Backend (персистентное хранилище)

```python
from atman.adapters.memory import FileBackend
from pathlib import Path

# Создать file backend
storage_path = Path.home() / '.atman' / 'facts.jsonl'
memory = FileBackend(storage_path)

# Использование аналогично InMemoryBackend
fact = FactRecord(content="Факт", source="test")
memory.add_fact(fact)

# Данные сохраняются автоматически
# При следующем запуске они будут загружены
```

## Архитектура

### Модели данных

#### FactRecord

Проверяемый факт без интерпретаций.

```python
class FactRecord:
    id: UUID                    # Уникальный идентификатор
    content: str                # Содержание факта (не пустое)
    source: str                 # Источник факта (не пустой)
    tags: list[str]             # Теги для категоризации
    relations: list[Relation]   # Связи с другими фактами
    created_at: datetime        # Время создания
    metadata: dict[str, Any]    # Дополнительные метаданные
```

#### Relation

Связь между двумя фактами.

```python
class Relation:
    target_id: UUID       # ID связанного факта
    relation_type: str    # Тип связи (caused_by, related_to, etc.)
    created_at: datetime
    metadata: dict[str, Any]
```

### Порт FactualMemory

Единый интерфейс для всех реализаций:

```python
class FactualMemory(ABC):
    def add_fact(record: FactRecord) -> FactRecord
    def get_fact(fact_id: UUID) -> FactRecord | None
    def search(query: str | None, tags: list[str] | None, limit: int) -> list[FactRecord]
    def link(source_id: UUID, target_id: UUID, relation_type: str) -> bool
    def list_recent(limit: int) -> list[FactRecord]
```

### Адаптеры

#### InMemoryBackend

- Хранит факты в памяти (словарь)
- Не персистентен
- Идеален для unit-тестов и прототипирования
- Методы: `clear()`, `count()`

#### FileBackend

- Использует JSONL формат (JSON Lines)
- Персистентное хранилище
- Автоматическая загрузка при старте
- Автоматическое сохранение при изменениях
- Подходит для локального запуска без внешних сервисов

## Примеры использования

### Пример 1: Базовая работа с фактами

```python
from atman.adapters.memory import InMemoryBackend
from atman.core.models import FactRecord

memory = InMemoryBackend()

# Добавить несколько фактов
fact1 = memory.add_fact(FactRecord(
    content="Пользователь попросил добавить функцию X",
    source="session_001",
    tags=["request", "feature"]
))

fact2 = memory.add_fact(FactRecord(
    content="Функция X была реализована",
    source="session_002",
    tags=["done", "feature"]
))

fact3 = memory.add_fact(FactRecord(
    content="Пользователь подтвердил работу функции X",
    source="session_003",
    tags=["confirmation", "feature"]
))

# Создать связи
memory.link(fact1.id, fact2.id, "led_to")
memory.link(fact2.id, fact3.id, "led_to")

# Найти все факты о feature
feature_facts = memory.search(tags=["feature"])
print(f"Найдено фактов о фиче: {len(feature_facts)}")

# Получить последние события
recent = memory.list_recent(limit=5)
for fact in recent:
    print(f"[{fact.created_at}] {fact.content}")
```

### Пример 2: Отслеживание принятых решений

```python
from atman.adapters.memory import FileBackend
from atman.core.models import FactRecord
from pathlib import Path

memory = FileBackend(Path("decisions.jsonl"))

# Записать решение
decision = memory.add_fact(FactRecord(
    content="Решено использовать JSONL для хранения фактов",
    source="architecture_discussion_2024_01_15",
    tags=["decision", "architecture", "storage"],
    metadata={
        "rationale": "Простота, читаемость, не требует внешних зависимостей",
        "alternatives": ["SQLite", "mem0", "in-memory only"]
    }
))

# Позже найти все архитектурные решения
arch_decisions = memory.search(tags=["decision", "architecture"])
```

### Пример 3: Построение цепочки причинно-следственных связей

```python
from atman.adapters.memory import InMemoryBackend
from atman.core.models import FactRecord

memory = InMemoryBackend()

# Цепочка событий
cause = memory.add_fact(FactRecord(
    content="Пользователь сообщил об ошибке в модуле X",
    source="issue_123",
    tags=["bug", "report"]
))

investigation = memory.add_fact(FactRecord(
    content="Найдена причина: некорректная валидация входных данных",
    source="debugging_session",
    tags=["bug", "analysis"]
))

fix = memory.add_fact(FactRecord(
    content="Реализована правильная валидация",
    source="commit_abc123",
    tags=["bug", "fix"]
))

verification = memory.add_fact(FactRecord(
    content="Пользователь подтвердил исправление",
    source="issue_123",
    tags=["bug", "verification"]
))

# Построить цепочку
memory.link(cause.id, investigation.id, "led_to")
memory.link(investigation.id, fix.id, "led_to")
memory.link(fix.id, verification.id, "led_to")

# Проверить связи
fact = memory.get_fact(cause.id)
print(f"Факт имеет {len(fact.relations)} связей")
```

## Тестирование

```bash
# Запустить все тесты
pytest

# Запустить с выводом
pytest -v

# Запустить конкретный тест
pytest tests/test_models.py::test_fact_record_creation

# Запустить тесты с покрытием
pytest --cov=atman --cov-report=html
```

### Структура тестов

- `tests/test_models.py` - тесты моделей данных
- `tests/test_in_memory_backend.py` - тесты InMemoryBackend
- `tests/test_file_backend.py` - тесты FileBackend
- `tests/test_backend_interface.py` - общие тесты для всех backend'ов

Все тесты проверяют:

- ✅ CRUD операции с фактами
- ✅ Поиск по тексту и тегам
- ✅ Создание связей между фактами
- ✅ Получение последних фактов
- ✅ Валидацию входных данных
- ✅ Неизменяемость возвращаемых данных (immutability)
- ✅ Персистентность (для FileBackend)

## Границы реализации

### Что делает этот пакет

✅ Хранит только факты и связи  
✅ Отделяет `fact.content` от выводов  
✅ Валидирует пустой content/source  
✅ Поддерживает теги и метаданные  
✅ Создает связи между фактами  
✅ Работает локально без внешних сервисов  

### Что НЕ делает этот пакет

❌ Не добавляет эмоциональную окраску  
❌ Не выводит привычки, принципы, навыки  
❌ Не строит идентичность  
❌ Не делает рефлексию  
❌ Не требует mem0 или другие внешние сервисы  

Эти функции реализуются в других компонентах Atman поверх этого фундамента.

## Расширяемость

Пакет спроектирован с учетом будущего расширения:

### Embeddings и семантический поиск

Можно добавить адаптер с векторным поиском:

```python
class VectorBackend(FactualMemory):
    def __init__(self, embedding_model):
        self.embeddings = {}
        self.model = embedding_model
    
    def search(self, query, tags=None, limit=10):
        # Семантический поиск через embeddings
        query_vector = self.model.embed(query)
        # ... поиск по косинусной близости
```

### Graph Memory

Можно добавить адаптер с графовой БД:

```python
class Neo4jBackend(FactualMemory):
    def link(self, source_id, target_id, relation_type):
        # Создать ребро в графе
        self.graph.create_edge(source_id, target_id, relation_type)
    
    def find_path(self, from_id, to_id):
        # Поиск пути между фактами
        return self.graph.shortest_path(from_id, to_id)
```

### Интеграция с mem0

```python
from mem0 import Memory

class Mem0Backend(FactualMemory):
    def __init__(self, user_id):
        self.memory = Memory()
        self.user_id = user_id
    
    def add_fact(self, record):
        # Добавить в mem0
        self.memory.add(record.content, user_id=self.user_id)
```

## Зависимость от других пакетов

Следующие work packages будут использовать Factual Memory Adapter:

- **02. Experience Store** - строит опыт поверх фактов
- **03. Identity Store** - опирается на factual memory для устойчивости
- **04. Reflection Engine** - анализирует уже записанные факты
- **05. Session Manager** - записывает факты в процессе сессии

## Философия дизайна

1. **Простота** - минимальный API, понятные концепции
2. **Изоляция** - нет зависимостей от других компонентов Atman
3. **Расширяемость** - легко добавить новые backend'ы
4. **Тестируемость** - все можно протестировать без внешних сервисов
5. **Честность** - не смешивает факты и интерпретации

## Структура проекта

```
atman/
├── src/atman/
│   ├── __init__.py
│   ├── cli.py                          # CLI для ручной проверки
│   ├── core/
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   └── fact.py                 # FactRecord, Relation
│   │   └── ports/
│   │       ├── __init__.py
│   │       └── memory_backend.py       # FactualMemory интерфейс
│   └── adapters/
│       └── memory/
│           ├── __init__.py
│           ├── in_memory_backend.py    # In-memory реализация
│           └── file_backend.py         # File-based реализация
├── tests/
│   ├── __init__.py
│   ├── test_models.py
│   ├── test_in_memory_backend.py
│   ├── test_file_backend.py
│   └── test_backend_interface.py
├── pyproject.toml
└── docs/features/factual-memory/   # README.md + README-ru.md (это руководство)
```

## Связанные документы

- Техзадание: [`../../development/work-packages/01-factual-memory-adapter.md`](../../development/work-packages/01-factual-memory-adapter.md)
- Архитектура: [`../../architecture/SYSTEM-ru.md`](../../architecture/SYSTEM-ru.md)
- Стандарт разработки: [`../../development/DEVELOPMENT_STANDARD.md`](../../development/DEVELOPMENT_STANDARD.md)

## Лицензия

См. LICENSE в корне репозитория.

## Вклад в разработку

См. [`../../development/DEVELOPMENT_STANDARD.md`](../../development/DEVELOPMENT_STANDARD.md).

---

**Статус**: ✅ MVP готов  
**Версия**: 0.1.0  
**Последнее обновление**: 2026-05-01
