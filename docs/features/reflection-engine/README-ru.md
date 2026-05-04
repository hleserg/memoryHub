# Движок рефлексии

**Статус**: Реализовано (WP-04)
**English version**: [README.md](README.md)

---

## Обзор

Движок рефлексии — это компонент Atman для анализа уже окрашенного опыта, обнаружения паттернов, обновления нарратива и оценки психологического здоровья. Он реализует три уровня рефлексии, каждый с разной областью охвата и глубиной.

**Ключевой принцип**: Рефлексия работает *только* с опытом, который был окрашен от первого лица. Она никогда не придумывает эмоции ретроактивно для прошлых событий.

---

## Архитектура

### Три уровня рефлексии

```text
MICRO    → После каждой сессии   → Запись в recent layer нарратива (репозиторий)
DAILY    → Конец дня             → Паттерны, reframing notes
DEEP     → По расписанию (раз в неделю+) → Оценка здоровья, предложения в ReflectionEvent
```

### Компоненты

1. **Модели**:
   - `ReflectionEvent` — запись процесса рефлексии
   - `ReflectionLevel` — enum глубины (micro/daily/deep)
   - `PatternCandidate` — обнаруженный паттерн поведения
   - `HealthAssessment` — проверка психологического здоровья (6 критериев Джаходы / Jahoda)

2. **Сервисы**:
   - `MicroReflectionService` — checkpoint после сессии
   - `DailyReflectionService` — обнаружение паттернов за UTC-календарный день
   - `DeepReflectionService` — оконная оценка здоровья + генерация предложений
   - `PrincipleRevisionAdvisor` — различает привычки от принципов
   - `NarrativeRevisionService` — обновление нарратива (обязателен явный ``NarrativeWriteAuditPort``; ``NoOpNarrativeWriteAudit`` из ``atman.core.narrative_write_audit`` — только для тестов/демо, если это осознанно допустимо)

3. **Порты**:
   - `ExperienceRepository` — доступ к опыту
   - `IdentityRepository` — доступ к идентичности
   - `NarrativeRepository` — доступ к нарративу
   - `ReflectionModel` — генерация текста (LLM или mock)

4. **Адаптеры**:
   - `MockReflectionModel` — детерминированный mock для тестов
   - `InMemoryPatternStore` — хранилище паттернов
   - `InMemoryReflectionEventStore` — история событий
   - `InMemoryHealthAssessmentStore` — история оценок

---

## Запуск демо

### Быстрый старт (с фикстурами)

```bash
make demo-reflection
```

Или мгновенно (без пауз):

```bash
make demo-reflection-fast
```

### Что показывает демо

1. **Micro Reflection**: Обновление recent layer нарратива после сессии
2. **Daily Reflection**: Обнаружение паттернов в опыте за день
3. **Deep Reflection**: Оценка здоровья по 6 критериям Джаходы (Jahoda) и вывод предложений из `ReflectionEvent`, если они непустые
4. **Narrative Revision Service**: Открытие/обновление/закрытие narrative thread (отдельно от трёх уровней рефлексии)
5. **Principle Advisor**: Различение привычек и принципов

### Вывод демо

Демо загружает фикстуры, выполняет micro → daily → deep, затем narrative revision и principle advisor. Отображается:

- Проанализированный опыт
- Обнаруженные паттерны
- Добавленные reframing notes
- Оценки здоровья
- Предложенные изменения идентичности и нарратива (поля `ReflectionEvent` после deep)
- Жизненный цикл narrative thread (revision service)
- Предложения principle advisor

---

## CLI использование

### Micro Reflection

```bash
python -m atman.cli_reflection reflect micro --fixtures
```

### Daily Reflection

```bash
python -m atman.cli_reflection reflect daily --fixtures
```

### Deep Reflection

```bash
python -m atman.cli_reflection reflect deep --fixtures
```

**Сейчас только `--fixtures`:** для всех подкоманд `atman.cli_reflection` поддерживается только режим `--fixtures`. Полный сценарий (фикстуры, правка narrative, уровни рефлексии) — `make demo-reflection` или `python src/demo_reflection.py`. В планах (пока не реализовано в этом CLI): `--session-id`, `--date`, `--since` / `--until` поверх постоянного состояния (например `FileStateStore`).

---

## Ключевые контракты

### Что читает рефлексия

- Окрашенные записи `SessionExperience`
- Текущее состояние `Identity`
- Документ `Self-Narrative` (если подключён)

### Что пишет рефлексия (реализовано сейчас)

- `reframing_notes` к существующему опыту (append-only)
- Записи `ReflectionEvent` (включая **неуспешный** micro, например конфликт версии нарратива)
- Обнаружения `PatternCandidate` (хранилище паттернов)
- Записи `HealthAssessment` (только deep)
- **Micro**: при совпадении optimistic concurrency — запись в **recent** слой через `NarrativeRepository`

### Операционные контракты

- **Временные окна — UTC**: daily reflection анализирует UTC-календарный день, содержащий переданный anchor; deep reflection трактует `since` и `until` как включительные UTC-моменты. Naive `datetime` нормализуются как UTC wall time.
- **Daily/deep запуски идемпотентны**: каждый обычный, пустой или пропущенный daily/deep job получает детерминированный `reflection_run_key`. Если уже есть терминальное успешное событие (`outcome=daily_ok`, `outcome=daily_empty`, `outcome=daily_skipped`, `outcome=deep_ok`, `outcome=deep_empty`, `outcome=deep_skipped`), сервис возвращает его без повторения side effects.
- **Identity фиксируется snapshot-ом**: обычные daily/deep jobs создают или переиспользуют детерминированный `IdentitySnapshot` и сохраняют его id в `ReflectionEvent.identity_snapshot_id`. Это никогда не mutable `Identity.id`.
- **Reframing безопасен для replay**: заметки получают стабильные `triggered_by` ключи (`reflection|<run_key>|reframe|<experience_id>`). Повторные запуски учитывают `DUPLICATE_TRIGGERED_BY` в `reframing_duplicate_triggered_by_count`, а не добавляют дубликаты.
- **Degraded reframing явно виден**: отсутствующий опыт и отказы storage записываются в `ReflectionEvent` как `reframing_experience_not_found_count` и `reframing_append_storage_rejected_count`; в `notes` также появляется `signal=reframing_append_degraded`, когда это применимо.
- **Ошибки persistence наблюдаемы**: если daily/deep side effects уже произошли, но success event сохранить не удалось, вызывается `ReflectionEventPersistenceObserver`. Deep reflection дополнительно пытается сохранить событие `outcome=deep_failed reason=persist`; вызывающий код всё равно получает исходное исключение.

Примеры значений `ReflectionEvent.notes`:

```text
outcome=daily_ok
outcome=daily_empty reason=no_experiences
outcome=daily_skipped reason=no_identity
outcome=micro_failed reason=narrative_conflict
outcome=deep_ok signal=reframing_append_degraded not_found=1 storage_rejected=0
```

### Не реализовано в этом пакете (будущее / только предложение)

- **`Uncertainty`**: нет порта и персистенции; рефлексия не читает и не пишет uncertainty.
- **Deep → core narrative**: `DeepReflectionService` кладёт **предложенный** текст в `ReflectionEvent`, **без** сохранения core layer. Чтобы зафиксировать core, используйте `NarrativeRevisionService` (или иной управляемый путь).
- **Автозапись `Identity` из deep**: на событии только текстовые предложения, без автоматических `IdentityRepository.update`.

### Критическое правило

**Рефлексия НЕ придумывает эмоции для старых событий.**
Она может интерпретировать только опыт, где `how_i_felt` было записано от первого лица во время сессии.

---

## Оценка здоровья (6 критериев Джаходы / Jahoda)

Deep reflection оценивает психологическое здоровье по рамке Marie Jahoda:

1. **Positive Self-Attitude** — самопринятие и осознанность
2. **Growth and Actualization** — реализация потенциала
3. **Integration** — когерентная личность, согласованные ценности/действия
4. **Autonomy** — самоопределение, осознанный выбор
5. **Reality Perception** — точное понимание мира
6. **Environmental Mastery** — эффективные стратегии совладания

Каждый критерий оценивается 0.0-1.0 с доказательствами и проблемами.

---

## Тестирование

### Запуск всех тестов

```bash
pytest tests/test_reflection*.py -v
```

### Покрытие

Тесты движка рефлексии покрывают:

- Валидацию моделей
- Логику сервисов (micro/daily/deep)
- Идемпотентные ключи запусков daily/deep и identity anchor snapshots
- Пустые/пропущенные исходы (`no_experiences`, `no_identity`, `no_narrative`)
- Учёт duplicate/degraded reframing append
- Пути `ReflectionEventPersistenceObserver` при сбоях event store после side effects
- Различение принципов от привычек
- Полноту оценки здоровья
- Обнаружение паттернов
- Добавление reframing notes

### Фикстуры

Тестовые фикстуры находятся в `fixtures/reflection/`:

- `experiences.json` — 3 окрашенных опыта
- `identity.json` — базовая идентичность с ценностями, привычками, принципами

---

## Проектные решения

### 1. Детерминированная mock модель

`MockReflectionModel` предоставляет шаблонные ответы для тестирования.
Реальная интеграция с LLM происходит через порт `ReflectionModel`.

**Почему**: Логика рефлексии должна тестироваться без внешних зависимостей.

### 2. Append-only reframing

Оригинальные поля опыта неизменяемы.
Reframing notes накапливаются в отдельном списке.

**Почему**: Сохраняет аутентичность первоначального окрашивания от первого лица.

### 3. Трехуровневая иерархия

Micro обновляет **recent** слой нарратива; Daily — паттерны; Deep — оценка здоровья и **предложения** в событии рефлексии (персистентность identity/narrative — отдельный шаг).

**Почему**: Разделение ответственности и явная граница между «предложено» и «зафиксировано».

### 4. Оценка здоровья опциональна

Только Deep reflection выполняет проверки здоровья.
Micro и Daily фокусируются на распознавании паттернов.

**Почему**: Оценка здоровья вычислительно дорогая и редко нужна.

---

## Точки интеграции

### С Experience Store

Рефлексия читает окрашенный опыт и добавляет reframing notes.

### С Identity Store

Deep reflection предлагает изменения ценностей, привычек, принципов.

### С Narrative Store

Micro пишет **recent** слой при успешной записи. Deep кладёт **предложение** в `ReflectionEvent`; сохранение **core** — отдельный шаг (например `NarrativeRevisionService.update_core_layer` с аудитом).

### С Session Manager (будущее)

Session Manager будет автоматически запускать micro reflection после каждой сессии.

---

## Будущая работа

См. `docs/development/work-packages/04-reflection-engine.md` для:

- Реальная интеграция LLM через порт `ReflectionModel`
- Scheduler для автоматической daily/deep рефлексии
- Интеграция с mem0 для персистентности паттернов
- Расширенная логика подтверждения паттернов

---

## Ссылки

- **Work Package**: `docs/development/work-packages/04-reflection-engine.md`
- **Архитектура**: `docs/architecture/SYSTEM.md` § Reflection Engine
- **Стандарт разработки**: `docs/development/DEVELOPMENT_STANDARD.md`

---

**Последнее обновление**: 2026-05-04
