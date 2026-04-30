# 06 - Reality Anchor и Affective Regulation

## Кратко

Сделать самостоятельный модуль защиты от дрейфа идентичности и острой эмоциональной саморегуляции во время сессии.

Источник: `docs/architecture/SYSTEM.md`, разделы "Якорь реальности" и "Регуляция аффекта".

## Зачем

Session Manager должен уметь замечать, когда агент говорит не своим голосом, противоречит принципам или уходит в резко негативный тон. Этот пакет дает проверяемый механизм сигналов и интервенций без зависимости от реального LLM runtime.

## Границы пакета

Входит:

- модель текущего действия/реплики агента;
- модель `IdentityReference` с принципами, границами, baseline tone;
- расчет drift score;
- классификация intervention level 1-4;
- short-term affect protocol: stop, pause, internal work, communication;
- CLI/demo для подачи сценариев и просмотра решения.

Не входит:

- запись опыта в Experience Store;
- изменение Identity Store;
- полный safety/moderation layer;
- долгосрочный homeostasis, кроме заготовки контракта события.

## Минимальный результат

Запускаемый модуль:

```bash
atman-reality-check --identity examples/identity.json --event examples/drift-event.json
```

Выводит:

- `drift_score`;
- найденные причины;
- intervention level;
- рекомендуемое сообщение/действие.

## Основные сущности

- `AgentEvent`
  - `content`
  - `claimed_knowledge`
  - `emotional_tone`
  - `action_intent`
- `IdentityReference`
  - `principles`
  - `known_limits`
  - `emotional_baseline`
  - `voice_markers`
- `RealitySignal`
  - `kind`: `principle_conflict | tone_shift | unsupported_claim | voice_drift`
  - `severity`
  - `evidence`
- `Intervention`
  - `level`: 1-4
  - `reason`
  - `suggested_action`
- `AffectProtocolResult`
  - `triggered`
  - `steps`
  - `message_to_user`

## Техническое ТЗ для агента

```text
Реализуй модуль Reality Anchor + Affective Regulation level 1.

Требования:
1. Прочитай docs/architecture/SYSTEM.md, разделы Reality Anchor и Affective Regulation.
2. Создай самостоятельный код с портами без зависимости от реального Session Manager.
3. Реализуй rule-based drift detection:
   - противоречие принципам;
   - резкое отклонение emotional_tone от baseline;
   - утверждение знания вне known_limits;
   - простая проверка voice drift по маркерам.
4. Реализуй mapping signals -> intervention levels:
   - level 1: внутренний флаг;
   - level 2: сигнал агенту;
   - level 3: запуск affect protocol;
   - level 4: рекомендация паузы пользователю.
5. Реализуй affect protocol для negative_affect_level > threshold.
6. Добавь CLI/demo и примеры JSON.
7. Добавь unit tests на каждый тип сигнала и пороги intervention.
8. Документируй команды запуска.
```

## Проверки

Минимальный набор:

- событие противоречит принципу -> минимум level 2;
- сильный negative_affect -> level 3 и affect protocol;
- unsupported claim -> signal `unsupported_claim`;
- несколько средних сигналов агрегируются до более высокого уровня;
- нормальная реплика не вызывает интервенцию.

## Критерии приемки

- Все сигналы объяснимы через evidence.
- Пороги настраиваются.
- Нет скрытых LLM-вызовов в тестах.
- Модуль можно подключить к Session Manager через один публичный метод вроде `evaluate(event, identity)`.

## Риски

- Слишком агрессивные интервенции будут мешать агенту работать.
- Слишком слабые пороги сделают якорь декоративным.
- Нельзя путать добросовестную ошибку и галлюцинацию: в первом прототипе это должно быть явно отражено как ограничение.
