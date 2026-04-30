# Development docs

Этот раздел содержит рабочие соглашения для реализации Atman.

## С чего начинать агентам

1. Прочитать [`DEVELOPMENT_STANDARD.md`](DEVELOPMENT_STANDARD.md).
2. Определить, задача относится к Core, Adapter или Infrastructure.
3. Проверить канонические термины, имена моделей и границы storage.
4. Перед реализацией ответить на checklist из раздела 24 стандарта.

## Обязательные правила

- Не привязывать Core напрямую к mem0, OpenClaw, конкретной LLM или scheduler.
- Любая persistable структура должна иметь `schema_version`.
- Любой пакет должен запускаться локально через fake/in-memory/file adapters.
- Work packages являются внутренними модулями одного Atman runtime, а не планом
  будущих микросервисов.
- Минимальный runtime path важнее расширенных фич: сначала session start/end,
  `PersonalitySnapshot`, narrative и micro reflection.

## Связанные документы

- [`../architecture/SYSTEM.md`](../architecture/SYSTEM.md) - архитектурная база.
- [`../ideas/project-blocks-after-manifest-and-system.md`](../ideas/project-blocks-after-manifest-and-system.md) - идеи следующих продуктовых и эксплуатационных блоков.
