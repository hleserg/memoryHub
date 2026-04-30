# WP-09: Background Agent, Personality Loader и scheduler shell

Источник: `docs/architecture/SYSTEM.md`, разделы "Фоновый агент", "Дифференцированная рефлексия", "Self-Narrative".

## Цель

Собрать запускаемый фоновой контур Atman: загрузка актуальной личности из workspace/memory, запуск micro/daily/deep задач по явной команде и минимальный scheduler shell. Этот пакет не обязан реализовывать глубокую логику рефлексии - он должен уметь безопасно запускать уже существующие/моковые задачи.

## Независимость

Можно делать без готового Reflection Engine:

- task handlers являются портами/интерфейсами;
- workspace представлен локальной директорией с `NARRATIVE.md`, `SOUL.md`, `AGENTS.md`, `USER.md`;
- memory представлен in-memory/file adapter;
- scheduler можно тестировать через ручной tick/CLI, без daemon.

## Обязательный результат

1. `PersonalityLoader`, который читает источники в правильном порядке:
   - `NARRATIVE.md`;
   - `SOUL.md`;
   - `AGENTS.md`;
   - `USER.md`;
   - recent memories;
   - eigenstate;
   - uncertainty;
   - checkpoints.
2. `PersonalityContext` с методом сборки prompt/context preview, где narrative идет первым.
3. CLI:
   - `load-personality --workspace <dir>` - печатает summary загрузки;
   - `run-micro --workspace <dir> --session-log <path>` - запускает micro handler;
   - `run-daily --workspace <dir>`;
   - `run-deep --workspace <dir>`;
   - `scan-markers --marker-dir <dir>` - находит marker-файлы завершенных сессий и запускает micro.
4. Маркерный протокол:
   - файл `atman_session_done_<ts>.marker` содержит путь к session log или пустую строку;
   - после успешной обработки marker переименовывается/перемещается в done;
   - при ошибке marker не теряется.
5. Scheduler shell:
   - конфиг расписания micro/daily/deep;
   - возможность ручного dry-run без бесконечного процесса.

## Минимальные модели

```text
PersonalityContext {
  narrative: string
  soul: string
  agents: string
  user: string
  recent_memories: MemoryRecord[]
  eigenstate?: MemoryRecord
  uncertainty: MemoryRecord[]
  last_checkpoint?: MemoryRecord
  loaded_at: timestamp
}

TaskHandler {
  run(context, input) -> TaskResult
}
```

## Acceptance criteria

- Narrative всегда первый в prompt/context preview.
- Loader не падает при отсутствующих workspace-файлах, а явно сообщает missing files.
- CLI-команды работают на fixture workspace без внешних сервисов.
- `scan-markers` обрабатывает несколько marker-файлов и не запускает один и тот же marker повторно после success.
- Ошибка handler не удаляет marker и возвращает ненулевой exit code.

## Тесты

Обязательные:

- unit: порядок загрузки workspace-файлов;
- unit: отсутствующий `NARRATIVE.md`;
- unit: выбор latest eigenstate/checkpoint из memory fixture;
- unit: prompt preview начинается с narrative content;
- integration: `scan-markers` обрабатывает marker и вызывает fake micro handler;
- integration: ошибка fake handler оставляет marker необработанным;
- CLI smoke tests для `load-personality`, `run-micro`, `scan-markers`.

## Ручная проверка

1. Создать временный workspace с четырьмя файлами.
2. Создать session log и marker.
3. Запустить `scan-markers`.
4. Убедиться, что:
   - micro handler получил session log;
   - marker перемещен в done;
   - в выводе виден loaded_at и порядок источников.

## Что не входит

- Реальная установка launchd/systemd.
- Реальный APScheduler daemon как обязательная зависимость.
- Реальные LLM-вызовы.
- Детальная логика micro/daily/deep reflection - это WP-04.

## Готовый промпт для агента

```text
Реализуй WP-09: Background Agent, Personality Loader и scheduler shell.

Архитектурный источник: docs/architecture/SYSTEM.md.
Нужно сделать запускаемый фоновой контур: PersonalityLoader, PersonalityContext, CLI для load-personality/run-micro/run-daily/run-deep/scan-markers, marker protocol и тесты. Работай автономно, не жди готовности Reflection Engine: task handlers сделай портами и fake/default реализациями для тестов.

Результат должен запускаться локально без mem0, OpenClaw и внешних LLM. Добавь команды запуска и тестов в документацию/PR.
```
