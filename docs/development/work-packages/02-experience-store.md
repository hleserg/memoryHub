# Work package 02: Experience Store

## Цель

Сделать запускаемое хранилище пережитого опыта первых рук: `SessionExperience`, `KeyMoment`, неизменяемый оригинал, `salience` decay, доступ к воспоминаниям и добавление `reframing_notes` без перезаписи исходного опыта.

Источник: `docs/architecture/SYSTEM.md`, раздел "Хранилище опыта" и "Эпизодическая память с контекстуальным ореолом".

## Почему пакет независим

Experience Store может работать поверх локального file/in-memory storage и не требует готового Session Manager, Reflection Engine или mem0. Все входы можно подавать через CLI/тестовые фикстуры.

## Scope

Включить:

- доменные модели:
  - `SessionExperience`;
  - `KeyMoment`;
  - `FeltSense` / эмоциональная окраска;
  - `ReframingNote`;
  - `ContextHalo`;
- API/сервис:
  - создать опыт;
  - получить опыт по id;
  - добавить `reframing_note`;
  - отметить доступ и обновить `last_accessed_at` / `access_count`;
  - рассчитать текущий `salience` без изменения оригинального события;
  - найти опыт по простым фильтрам: session_id, values_touched, depth, date range;
- локальный adapter хранения:
  - JSONL или SQLite;
  - in-memory adapter для тестов;
- CLI для ручной проверки:
  - `experience add`;
  - `experience get`;
  - `experience reflect`;
  - `experience search`;
  - `experience decay-preview`.

Не включать:

- генерацию чувств из сырого лога;
- Reflection Engine;
- Session Manager runtime;
- vector search.

## Контракты

Минимальный объект:

```json
{
  "id": "uuid",
  "session_id": "uuid",
  "timestamp": "RFC3339",
  "key_moments": [
    {
      "what_happened": "string",
      "when": "RFC3339",
      "how_i_felt": {
        "emotional_valence": 0.1,
        "emotional_intensity": 0.7,
        "depth": "meaningful"
      },
      "why_it_matters": "string",
      "values_touched": ["string"],
      "principles_confirmed": ["string"],
      "principles_questioned": ["string"],
      "what_changed": "string",
      "context_halo": "string"
    }
  ],
  "recorded_by": "session_manager",
  "identity_snapshot_id": "uuid",
  "importance": 0.5,
  "salience": 0.5,
  "incomplete_coloring": false,
  "reframing_notes": []
}
```

Инварианты:

- исходные `key_moments` нельзя менять после записи;
- `reframing_notes` добавляются слоями;
- `incomplete_coloring=true` допустим только как честный fallback;
- `salience` может вычисляться/обновляться, но не должен менять смысловую запись опыта.

## Запускаемый результат

После пакета должно быть возможно:

1. установить зависимости проекта;
2. создать тестовый `SessionExperience` из fixture-файла;
3. получить его по id;
4. добавить reframing note;
5. увидеть, что оригинальный `key_moments[0]` не изменился;
6. запустить unit-тесты.

## Минимальные тесты

- валидные/невалидные значения `emotional_valence`, `emotional_intensity`, `depth`;
- неизменяемость оригинального key moment;
- добавление нескольких reframing notes в порядке времени;
- decay снижает только эффективную salience;
- access обновляет `last_accessed_at` и `access_count`;
- поиск по `values_touched` и `depth`.

## Acceptance criteria

- Есть пара инструкций с командами запуска: `docs/features/experience-store/README.md` и `docs/features/experience-store/README-ru.md`.
- Есть фикстуры для минимум двух опытов.
- CLI работает без внешних сервисов.
- Тесты проходят локально.
- В коде явно запрещено ретроспективное "угадывание" эмоциональной окраски.
