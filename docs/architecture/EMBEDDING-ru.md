# Архитектура Embedding

## Обзор

Система памяти Atman использует семантические эмбеддинги для поиска по схожести. Embedding Port предоставляет абстракцию над провайдерами эмбеддингов, позволяя подключать различные реализации при сохранении единого интерфейса для слоя памяти.

## Контракт Embedding Port

Абстрактный базовый класс `EmbeddingPort` (`src/atman/core/ports/embedding.py`) определяет контракт:

```python
class EmbeddingPort(ABC):
    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Генерация вектора эмбеддинга для текста."""
        pass

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Генерация эмбеддингов для нескольких текстов."""
        pass

    @abstractmethod
    def dimension(self) -> int:
        """Возвращает размерность эмбеддингов."""
        pass

    @abstractmethod
    def model_name(self) -> str:
        """Возвращает название модели эмбеддинга."""
        pass
```

### Ключевые архитектурные решения

1. **Согласованность размерности**: Все адаптеры возвращают векторы заданной размерности (768 для qwen3-embedding:1.5b)
2. **Детерминизм**: Mock-адаптер использует сид `hash(text) % 2^31` для воспроизводимых результатов
3. **Отслеживаемость**: `model_name()` позволяет отслеживать, какая модель сгенерировала каждый эмбеддинг

## Конфигурация

Конфигурация эмбеддингов управляется через переменные окружения:

| Переменная | Значение по умолчанию | Описание |
|------------|----------------------|----------|
| `EMBEDDING_BACKEND` | `mock` | Бэкенд: `ollama` или `mock` |
| `EMBEDDING_MODEL` | `qwen3-embedding:1.5b` | Название модели Ollama |
| `EMBEDDING_DIMENSION` | `768` | Ожидаемая размерность вектора |
| `EMBEDDING_OLLAMA_HOST` | `http://localhost:11434` | Эндпоинт API Ollama |
| `EMBEDDING_TIMEOUT` | `30.0` | Таймаут запроса в секундах |

Конфигурация загружается через Pydantic Settings (`src/atman/config.py`) с поддержкой `.env` файлов.

## Доступные адаптеры

### OllamaEmbeddingAdapter

Продакшен-адаптер, использующий эндпоинт `/api/embed` Ollama.

**Возможности:**
- Поддержка любой модели эмбеддингов Ollama
- Пакетная генерация эмбеддингов
- Проверка здоровья через метод `health_check()`
- Автоматическое определение размерности

**Использование:**
```python
from atman.adapters.memory.ollama_embedding import OllamaEmbeddingAdapter

adapter = OllamaEmbeddingAdapter(
    base_url="http://localhost:11434",
    model="qwen3-embedding:1.5b",
    timeout=30.0,
)

embedding = adapter.embed("семантический поисковый запрос")
assert len(embedding) == 768
assert adapter.model_name() == "qwen3-embedding:1.5b"
```

**Требования:**
- Запущенный экземпляр Ollama
- Загруженная модель: `ollama pull qwen3-embedding:1.5b`

### MockEmbeddingAdapter

Детерминированный тестовый адаптер без внешних зависимостей.

**Возможности:**
- Одинаковый текст всегда дает одинаковый эмбеддинг
- Разные тексты дают разные эмбеддинги
- 768-мерные единичные векторы
- Детерминированная генерация на основе LCG

**Использование:**
```python
from atman.adapters.memory.mock_embedding import MockEmbeddingAdapter

adapter = MockEmbeddingAdapter()

embedding1 = adapter.embed("привет мир")
embedding2 = adapter.embed("привет мир")
assert embedding1 == embedding2  # Детерминизм
assert adapter.dimension() == 768
assert adapter.model_name() == "mock-embedding:768d"
```

## Выбор модели: qwen3-embedding:1.5b

Модель по умолчанию — `qwen3-embedding:1.5b` по следующим причинам:

| Критерий | qwen3-embedding:1.5b |
|----------|---------------------|
| **Размерность** | 768 (соответствует схеме VECTOR(768)) |
| **Качество** | Хорошая производительность на бенчмарках MTEB |
| **Скорость** | ~50 мс на запрос на потребительском GPU |
| **Размер** | 1.5B параметров, ~600 МБ |
| **Лицензия** | Apache 2.0 (коммерческое использование OK) |
| **Мультиязычность** | Сильная поддержка CJK + английский |

## Схема базы данных

Таблицы, хранящие эмбеддинги, включают колонку `embed_model` для отслеживаемости:

```sql
ALTER TABLE public.facts
ADD COLUMN embed_model TEXT;

ALTER TABLE public.key_moments
ADD COLUMN embed_model TEXT;

ALTER TABLE public.identity_snapshots
ADD COLUMN embed_model TEXT;
```

Это обеспечивает:
- **Отслеживание миграции моделей**: Знание, какая модель сгенерировала каждый вектор
- **Решения о пере-эмбеддинге**: Идентификация записей, требующих переработки при смене моделей
- **Аудит**: Сохранение происхождения данных для соответствия требованиям

## Проверка здоровья

Проверка статуса эмбеддера:

```python
from atman.adapters.memory.ollama_embedding import OllamaEmbeddingAdapter

adapter = OllamaEmbeddingAdapter()
if adapter.health_check():
    print(f"Ollama готова с {adapter.model_name()}")
    sample = adapter.embed("__warmup__")
    assert len(sample) == adapter.dimension()
```

## Как добавить новый адаптер

Для добавления поддержки нового провайдера эмбеддингов (например, OpenAI, Hugging Face):

### Шаг 1: Создать файл адаптера

Создать `src/atman/adapters/memory/openai_embedding.py`:

```python
"""OpenAIEmbeddingAdapter - эмбеддинги через OpenAI API."""

import math
from typing import override

from atman.core.ports.embedding import EmbeddingPort


class OpenAIEmbeddingAdapter(EmbeddingPort):
    """Адаптер эмбеддингов, использующий OpenAI API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "text-embedding-3-small",
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.model = model
        self.timeout = timeout
        self._dimension = 1536  # размерность text-embedding-3-small

    @override
    def embed(self, text: str) -> list[float]:
        """Генерация эмбеддинга через OpenAI API."""
        # Реализация: вызов эндпоинта /embeddings
        # Возврат list[float] правильной размерности
        pass

    @override
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Генерация эмбеддингов для нескольких текстов."""
        return [self.embed(text) for text in texts]

    @override
    def dimension(self) -> int:
        """Возвращает размерность эмбеддинга."""
        return self._dimension

    @override
    def model_name(self) -> str:
        """Возвращает название модели OpenAI."""
        return self.model

    def health_check(self) -> bool:
        """Проверка API-ключа и подключения."""
        try:
            self.embed("test")
            return True
        except Exception:
            return False
```

### Шаг 2: Обновить конфигурацию

Добавить в `src/atman/config.py`:

```python
class EmbeddingSettings(BaseSettings):
    backend: str = "mock"  # Добавить опцию "openai"
    openai_api_key: str | None = None
    openai_model: str = "text-embedding-3-small"
```

### Шаг 3: Зарегистрировать в `__init__.py`

Обновить `src/atman/adapters/memory/__init__.py` для экспорта нового адаптера.

### Шаг 4: Добавить тесты

Создать `tests/memory/test_embedding_openai.py` с ≥15 тестами, покрывающими:
- Успешную генерацию эмбеддингов
- Проверку размерности
- Отчет о названии модели
- Поведение health check
- Обработку ошибок (невалидный API ключ, сетевая ошибка)
- Консистентность пакетной генерации

### Шаг 5: Обновить документацию

Добавить в этот файл:
- Описание нового адаптера
- Опции конфигурации
- Таблицу сравнения моделей

## Тестирование

Запуск тестов эмбеддингов:

```bash
# Все тесты эмбеддингов
pytest tests/memory/test_embedding_*.py -v

# Только mock-адаптер (без внешних сервисов)
pytest tests/memory/test_embedding_mock.py -v

# Ollama-адаптер (требует запущенной Ollama)
pytest tests/memory/test_embedding_ollama.py -v --requires-ollama
```

## Решение проблем

### Нет подключения к Ollama

```
RuntimeError: Failed to connect to Ollama: <urlopen error [Errno 111] Connection refused>
```

**Решение:** Запустить Ollama:
```bash
docker-compose up -d ollama
# или
ollama serve
```

### Модель не найдена

```
RuntimeError: Empty embedding received from Ollama
```

**Решение:** Загрузить модель:
```bash
ollama pull qwen3-embedding:1.5b
```

### Несоответствие размерности

```
ValueError: Vectors must have same dimension
```

**Решение:** Проверить, что `EMBEDDING_DIMENSION` соответствует выводу модели.

## Ссылки

- Issue: [#391](https://github.com/hleserg/atman/issues/391) - Epic E25
- Модель: [qwen3-embedding:1.5b](https://ollama.com/library/qwen3-embedding)
- Ollama API: [embed endpoint](https://github.com/ollama/ollama/blob/main/docs/api.md#generate-embeddings)
