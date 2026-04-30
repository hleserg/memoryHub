# Work packages по SYSTEM.md

Источник: `docs/architecture/SYSTEM.md`.

Цель этого каталога - разбить разработку Atman на самостоятельные вертикальные куски, которые можно отдавать отдельным агентам. Каждый work package должен давать запускаемый результат с тестами и не ждать завершения соседних пакетов.

## Общие правила для всех пакетов

- Делать вертикальный срез: модель данных, минимальная реализация, CLI/API для ручного запуска, тесты, документация запуска.
- Если общий модуль или контракт еще не существует, создать локальный минимальный контракт внутри своего среза и явно описать его в README пакета.
- Не блокироваться на mem0, OpenClaw, внешних LLM или scheduler: для тестов использовать in-memory/file adapters и моковые провайдеры.
- Поддерживать будущую интеграцию через явные порты: storage, memory, model, workspace, clock.
- Результат считается готовым только если его можно запустить из чистого checkout по описанной команде.

## Карта пакетов

| Пакет | Результат | Основной режим |
| --- | --- | --- |
| [01-factual-memory-adapter](01-factual-memory-adapter.md) | Абстракция factual memory поверх mem0/in-memory | общий фундамент |
| [02-experience-store](02-experience-store.md) | Хранилище окрашенного опыта первых рук | сессионный + фоновый |
| [03-identity-and-narrative](03-identity-and-narrative.md) | Identity Store, Eigenstate, Self-Narrative, bootstrap | старт/конец сессии |
| [04-reflection-engine](04-reflection-engine.md) | Micro/Daily/Deep reflection без scheduler | фоновый |
| [05-session-manager](05-session-manager.md) | Сессионный runtime: старт, key moments, завершение | сессионный |
| [06-reality-and-affect](06-reality-and-affect.md) | Reality Anchor + Affective Regulation level 1 | сессионный |
| [07-ambient-and-proactive](07-ambient-and-proactive.md) | Ambient Memory Layer + Proactive Engine | оба режима |
| [08-skill-manager](08-skill-manager.md) | Skill Library, установка, версии, garbage collection | оба режима |
| [09-background-agent](09-background-agent.md) | Personality Loader + background runner + scheduler shell | фоновый |

## Как выдавать пакет агенту

1. Скопировать агенту один файл пакета целиком.
2. Добавить ссылку на `docs/architecture/SYSTEM.md` как архитектурный источник.
3. Попросить не менять соседние пакеты без необходимости.
4. Требовать PR с командами запуска и тестов в описании.

## Интеграционные ожидания

Пакеты независимы на этапе разработки, но должны сходиться через простые контракты:

- факты - проверяемые записи без интерпретации;
- опыт - неизменяемые first-person события с эмоциональной окраской;
- идентичность - версионируемое самоописание, ценности, принципы, открытые вопросы;
- нарратив - first-person синтез текущего состояния;
- рефлексия - интерпретация уже окрашенного опыта, без ретроактивного выдумывания чувств.
