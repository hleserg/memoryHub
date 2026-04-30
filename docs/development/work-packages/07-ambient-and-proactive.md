# Work package 07: Ambient Memory Layer + Proactive Engine

## Цель

Сделать слой проактивного прайминга памяти и генерации внутренних инициатив. Результат должен работать без полноценного Session Manager: на вход получает текущий текст/событие, на выходе дает короткую first-person memory injection и список candidate initiatives.

## Архитектурный источник

- `SYSTEM.md`: Proactive Engine, spontaneous memories, reflective access.
- `SYSTEM.md`: Ambient Memory Layer.

## Независимость

Пакет использует порт `MemorySearchPort` и может работать с in-memory набором воспоминаний. Не зависит от реального mem0, Experience Store или Reflection Engine.

## Scope

### Включить

- `AmbientMemoryService`:
  - снимает semantic snapshot входящего контекста;
  - ищет 3-5 близких эмоционально значимых воспоминаний;
  - применяет пороги релевантности, salience и emotional intensity;
  - генерирует короткую first-person injection.
- `MemorySignalService`:
  - отмечает обращение к воспоминанию;
  - увеличивает `access_count`;
  - обновляет `last_accessed_at`.
- `ProactiveEngine`:
  - источники инициативы: unfinished task, spontaneous memory, agent need, scheduled reflection;
  - скоринг инициатив;
  - решение `ignore | reflect | suggest | external_action_required`.
- CLI:
  - `atman ambient prime --input "..."`;
  - `atman proactive scan --fixtures ...`.

### Не включать

- Отправку сообщений пользователю.
- Реальный scheduler.
- Полный Agora/internal council.

## Минимальные модели

```text
AmbientCandidate
- memory_id
- text
- relevance
- salience
- emotional_intensity
- first_person_shadow

Initiative
- id
- source
- title
- reason
- urgency
- action_type
- requires_user_attention
```

## Проверяемый результат

- CLI принимает текст текущей ситуации и возвращает JSON:
  - `injection`;
  - `candidates`;
  - `signals_written`.
- CLI proactive scan на фикстурах возвращает список инициатив с объяснимым скорингом.

## Тесты

- Нерелевантные воспоминания не попадают в injection.
- Из нескольких релевантных выбираются самые яркие/значимые.
- Injection не выглядит как инструкция, а как тень воспоминания от первого лица.
- Повторное обращение обновляет access metadata.
- Proactive Engine корректно различает внутреннюю рефлексию и внешнее действие.

## Definition of Done

- Есть unit tests для scoring и formatting.
- Есть фикстуры воспоминаний и инициатив.
- Есть README с командами запуска.
- Пакет можно проверить без внешних сервисов.
