# WP-04: Reflection Engine

## Цель

Сделать фоновый движок рефлексии, который работает только с уже окрашенным опытом, добавляет `reframing_notes`, находит паттерны, обновляет открытые вопросы и формирует события для Identity/Narrative. Без scheduler и без привязки к реальному LLM.

## Почему пакет независим

Reflection Engine можно тестировать на фикстурах Experience Store и Identity Store. Если соседние пакеты еще не реализованы, создать локальные in-memory репозитории и JSON fixtures с теми же полями.

## Scope

### Входит

- Модели:
  - `ReflectionEvent`
  - `ReframingNote`
  - `PatternCandidate`
  - `HealthAssessment` по 6 критериям Яходы
  - `ReflectionLevel`: `micro`, `daily`, `deep`
- Сервисы:
  - `MicroReflectionService`
  - `DailyReflectionService`
  - `DeepReflectionService`
  - `NarrativeRevisionService` как минимальная часть deep reflection
  - `PrincipleRevisionAdvisor`
- Порты:
  - `ExperienceRepository`
  - `IdentityRepository`
  - `NarrativeRepository`
  - `ReflectionModel` или `TextGenerator`
- Deterministic/mock generator для тестов.
- CLI:
  - `atman reflect micro --session-log fixtures/session.md`
  - `atman reflect daily --date YYYY-MM-DD`
  - `atman reflect deep --since YYYY-MM-DD --until YYYY-MM-DD`

### Не входит

- Реальный scheduler.
- Реальное подключение к mem0.
- Реальное обновление управляющих файлов OpenClaw за пределами repository port.
- Сессионный сбор опыта.

## Контракты

```text
Reflection Engine читает:
- окрашенный SessionExperience
- Identity snapshot/current Identity
- Self-Narrative
- Uncertainty entries

Reflection Engine пишет:
- reframing_notes к существующим experience
- ReflectionEvent
- PatternCandidate/confirmed pattern
- новые или обновленные uncertainty
- draft изменений Identity/Narrative
```

Важно: движок не придумывает эмоции для старых событий. Он может интерпретировать только то, где уже есть first-person coloring.

## Минимальный runnable-результат

Команда `atman reflect deep --fixtures` должна:

1. загрузить несколько окрашенных воспоминаний;
2. найти 1-2 повторяющихся паттерна;
3. добавить `reframing_note` к одному воспоминанию;
4. сформировать `ReflectionEvent`;
5. вывести JSON/Markdown отчет;
6. сохранить обновленное состояние в тестовый каталог.

## Тесты

- Unit:
  - micro reflection обновляет только recent/narrative draft и checkpoint;
  - daily reflection не меняет Identity без оснований;
  - deep reflection добавляет reframing note, не переписывая оригинальный experience;
  - PrincipleRevisionAdvisor различает привычку и принцип;
  - health assessment содержит все 6 критериев Яходы.
- Integration:
  - полный deep прогон на fixtures дает стабильный snapshot.

## Критерии приемки

- Есть CLI для трех уровней рефлексии.
- Все внешние зависимости заменяемы портами.
- Оригинальные поля опыта не мутируются, кроме append-only `reframing_notes` и access metadata.
- В README описано, как запустить reflection на fixtures.
- Тесты проходят без внешних сервисов.

## Риски

- Главный риск - смешать анализ опыта с созданием опыта. В коде и тестах зафиксировать запрет на ретроактивное заполнение `how_i_felt`.
- Deep reflection может стать слишком широкой. Сначала реализовать deterministic pipeline, LLM подключать через порт.
