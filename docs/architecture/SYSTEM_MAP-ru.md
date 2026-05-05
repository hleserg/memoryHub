# Карта системы Atman

> Документ создан в ответ на [issue #125](https://github.com/hleserg/atman/issues/125).
> Цель — структурированно описать кодовую базу для планирования покрытия тестами:
> модули, интеграции, пользовательские сценарии, нестандартные входы и известные баги.
>
> **Поддержка:** карта — живой документ. Любое изменение кода, которое добавляет,
> удаляет или перепроводит модули, порты, адаптеры, сервисы, точки входа CLI/TUI/web,
> демо или e2e-флоу, ОБЯЗАНО обновить и `SYSTEM_MAP.md`, и `SYSTEM_MAP-ru.md`
> в том же PR. Новые тесты должны быть привязаны к соответствующему разделу
> карты (см. `docs/development/DEVELOPMENT_STANDARD.md` §26).
>
> **Канонический язык — английский:** правки сначала вносятся в `SYSTEM_MAP.md`,
> затем синхронизируется русская версия (как для `README.md`/`README-ru.md`).

Все пути абсолютные относительно корня репозитория.

---

## 1. Модули

### 1.1. Доменные модели (`src/atman/core/models/`)

| Файл | Назначение | Публичные классы |
|------|------------|------------------|
| `core/models/fact.py` | Верифицируемые факты и связи между ними | `FactRecord`, `Relation` |
| `core/models/experience.py` | Прожитый опыт, ключевые моменты, переосмысление | `SessionExperience`, `KeyMoment`, `FeltSense`, `ContextHalo`, `ReframingNote`, `EmotionalDepth`, `ReframingNoteAppendResult` |
| `core/models/identity.py` | Самопредставление агента (ценности, привычки, принципы, цели, открытые вопросы) | `Identity`, `CoreValue`, `Habit`, `Principle`, `Goal`, `OpenQuestion`, `IdentitySnapshot`, `HelpfulnessLevel` |
| `core/models/narrative.py` | Документ самонарратива (CORE/RECENT/THREADS) и собственное состояние | `NarrativeDocument`, `NarrativeLayer`, `NarrativeThread`, `Eigenstate` (`schema_version`, опциональный `identity_id`), `LayerType` |
| `core/models/session.py` | Модели сессионного runtime: контекст, события, входящий key moment, результат, сводка активных | `SessionContext`, `SessionEvent`, `KeyMomentInput`, `SessionResult`, `ActiveSessionSummary` |
| `core/models/reflection.py` | Процесс рефлексии, паттерны, оценка здоровья (критерии Йоды) | `ReflectionLevel`, `PatternCandidate`, `PatternStatus`, `PatternType`, `ReflectionEvent`, `HealthAssessment`, `JahodaCriterion`, `CriterionAssessment` |
| `core/models/governance.py` | Решения governance для мутаций ядра нарратива | `GovernanceDecision`, `GovernanceMode` |

### 1.2. Порты / интерфейсы (`src/atman/core/ports/`)

| Файл | Назначение | Контракты |
|------|------------|-----------|
| `core/ports/memory_backend.py` | Интерфейс факт-памяти | `FactualMemory` (ABC) |
| `core/ports/clock.py` | Доменные часы для воспроизводимости | `ClockPort` (Protocol) |
| `core/ports/state_store.py` | Хранилище опыта/identity/нарратива | `StateStore`, `ExperienceQuery`, `SessionExperienceQuery`, `ValuesTouchedQuery`, `DepthQuery`, `DateRangeQuery` |
| `core/ports/reflection.py` | Зависимости Reflection Engine | `ExperienceRepository`, `IdentityRepository`, `NarrativeRepository`, `ReflectionModel`, `PatternStore`, `ReflectionEventStore`, `HealthAssessmentStore`, `ReflectionEventPersistenceObserver`, `NarrativeWriteAuditPort` |

### 1.3. Сервисы (`src/atman/core/services/`)

| Файл | Назначение | Классы |
|------|------------|--------|
| `core/services/experience_service.py` | Жизненный цикл опыта: создание, выборка, переосмысление, salience | `ExperienceService` |
| `core/services/identity_service.py` | Жизненный цикл identity: bootstrap, update, snapshot | `IdentityService` |
| `core/services/narrative_service.py` | Документ нарратива: создание, обновление, архивация, валидация | `NarrativeService` |
| `core/services/narrative_revision.py` | Обновления нарратива во время рефлексии с контролем конкуренции | `NarrativeRevisionService` |
| `core/services/session_manager.py` | Сессионный runtime: старт, запись событий/key moments, завершение с eigenstate (потокобезопасный реестр, опциональный `max_active_sessions`) | `SessionManager`, `MAX_EIGENSTATE_ITEMS`; ошибки сессий в `core/exceptions.py` |
| `core/services/reflection_service.py` | Три уровня рефлексии: micro, daily, deep | `MicroReflectionService`, `DailyReflectionService`, `DeepReflectionService` |
| `core/services/principle_advisor.py` | Различение привычки и принципа; советник пересмотра принципов | `PrincipleRevisionAdvisor` |

### 1.4. Утилиты ядра

| Файл | Назначение |
|------|------------|
| `core/exceptions.py` | `AtmanError`, `GovernanceRejectedError`, `NarrativePersistenceConflictError`, `SessionNotFoundError`, `SessionAlreadyFinishedError`, `TooManyActiveSessionsError` |
| `core/clock_impl.py` | `SystemClock`, `FrozenClock` |
| `core/narrative_write_audit.py` | Хуки аудита коммитов нарратива |
| `core/reflection_event_audit.py` | Наблюдатели персистенса событий рефлексии |
| `core/reflection_run_keys.py` | Детерминированные ключи прогонов рефлексии |

### 1.5. Адаптеры (`src/atman/adapters/`)

| Файл | Реализует порт | Поведение |
|------|----------------|-----------|
| `adapters/memory/in_memory_backend.py` (`InMemoryBackend`) | `FactualMemory` | без персистенса |
| `adapters/memory/file_backend.py` (`FileBackend`) | `FactualMemory` | JSONL + file locking |
| `adapters/storage/in_memory_experience_store.py` (`InMemoryExperienceStore`) | `StateStore` | в памяти |
| `adapters/storage/jsonl_experience_store.py` (`JsonlExperienceStore`) | `StateStore` | JSONL для опыта |
| `adapters/storage/file_state_store.py` (`FileStateStore`) | `StateStore` | JSON-файлы (опыт + identity + нарратив + eigenstate) |
| `adapters/storage/in_memory_reflection_store.py` | `PatternStore`, `ReflectionEventStore`, `HealthAssessmentStore` | хранилища выводов рефлексии |
| `adapters/reflection/mock_reflection_model.py` (`MockReflectionModel`) | `ReflectionModel` | детерминированный мок |
| `adapters/reflection/fixture_loader.py` | — | загрузка фикстур для демо |

### 1.6. CLI / TUI / Web / Демо

| Файл | Категория | Назначение |
|------|-----------|------------|
| `cli.py` | CLI | REPL факт-памяти |
| `cli_experience.py` | CLI | Experience Store |
| `cli_identity.py` | CLI | Identity Store |
| `cli_reflection.py` | CLI | Reflection Engine (micro/daily/deep) |
| `term.py` | utility | Rich-вывод для CLI/демо |
| `tui/app.py` | TUI | Точка входа Textual-приложения (Tests / Features / Docs) |
| `tui/tests_tab.py`, `tui/features_tab.py`, `tui/docs_tab.py` | TUI | вкладки |
| `tui/features_registry.py` | TUI | реестр фич |
| `tui/pytest_utils.py`, `tui/runner.py`, `tui/repo_root.py` | TUI | подпроцессы и поиск корня репо |
| `web_dashboard/app.py` | web | Streamlit-главная |
| `web_dashboard/pages/1_Tests.py`, `web_dashboard/pages/2_Docs.py` | web | страницы Streamlit |
| `web_dashboard/utils/cmd.py`, `web_dashboard/utils/runner.py` | web | подпроцессы |
| `src/demo.py` | demo | демо факт-памяти |
| `src/demo_experience_store.py` | demo | прогон Experience Store |
| `src/demo_identity.py` | demo | bootstrap identity + рендер нарратива |
| `src/demo_session_manager.py` | demo | жизненный цикл сессии: старт, запись событий/key moments, завершение с eigenstate |
| `src/demo_reflection.py` | demo | micro→daily→deep с фикстурами |
| `src/demo_web_dashboard.py` | demo | подсказка запуска веб-дашборда |
| `e2e/generate_fixtures.py` | e2e | генератор JSON-фикстур сессий через LLM (`python -m e2e.generate_fixtures`); по умолчанию корпуса 20 `en/` + 20 `ru/` с параллельным запуском локалей; Anthropic tool_use, два прохода; флаги `--corpus-policy strict|soft`, `--max-corpus-regen N` (ограничение хвоста в strict); опционально `[e2e]`; не CI ([issue #141](https://github.com/hleserg/atman/issues/141)) |
| `e2e/models.py`, `e2e/validation.py`, `e2e/llm.py`, `e2e/prompts.py` | e2e | схема фикстур, валидаторы внутри/между сессиями, вызов API, промпты |

---

## 2. Интеграции

Связки, где две или более частей работают вместе. Это места, где может сломаться **стык**, а не сама логика.

### 2.1. Сервис ↔ порт

| Связка | Файлы | Тип |
|--------|-------|-----|
| `ExperienceService` ↔ `StateStore` | `core/services/experience_service.py` → `core/ports/state_store.py` | DI |
| `IdentityService` ↔ `StateStore` | `core/services/identity_service.py` → `core/ports/state_store.py` | DI |
| `NarrativeService` ↔ `StateStore` | `core/services/narrative_service.py` → `core/ports/state_store.py` | DI |
| `SessionManager` ↔ `StateStore` | `core/services/session_manager.py` → `core/ports/state_store.py` | старт: identity/narrative + `IdentitySnapshot`; `finish_session`: детерминированный `SessionExperience.id` (uuid5 от `session_id`) для идемпотентных ретраев; загрузка eigenstate с фильтром `identity_id`; обновление recent narrative через `save_narrative(..., expected_updated_at=...)` |
| `NarrativeRevisionService` ↔ `NarrativeRepository` | `core/services/narrative_revision.py` → `core/ports/reflection.py` | оптимистическая блокировка |
| `MicroReflectionService` ↔ `ExperienceRepository` + `NarrativeRepository` | `core/services/reflection_service.py` | чтение опыта, апдейт recent-слоя |
| `DailyReflectionService` ↔ `ExperienceRepository` + `PatternStore` + `ReflectionEventStore` | `core/services/reflection_service.py` | детекция паттернов |
| `DeepReflectionService` ↔ все рефлексионные порты | `core/services/reflection_service.py` | здоровье + апдейт identity и нарратива |
| `PrincipleRevisionAdvisor` ↔ `PatternCandidate` + `Identity` | `core/services/principle_advisor.py` | анализ паттернов в контексте identity |

### 2.2. Адаптер ↔ порт

| Адаптер | Реализует |
|---------|-----------|
| `InMemoryBackend`, `FileBackend` | `FactualMemory` |
| `InMemoryExperienceStore`, `JsonlExperienceStore`, `FileStateStore` | `StateStore` |
| `MockReflectionModel` | `ReflectionModel` |
| `InMemoryPatternStore`, `InMemoryReflectionEventStore`, `InMemoryHealthAssessmentStore` | соответствующие порты |

### 2.3. CLI ↔ сервис

| CLI | Проводка | Файл |
|-----|----------|------|
| `cli.py` | `FileBackend` напрямую как `FactualMemory` | `cli.py:14-24` |
| `cli_experience.py` | `ExperienceService(JsonlExperienceStore)` | `cli_experience.py:17-29` |
| `cli_identity.py` | `IdentityService(FileStateStore)` + `NarrativeService(FileStateStore)` | `cli_identity.py:15-29` |
| `cli_reflection.py` | `Micro/Daily/DeepReflectionService` + fixture_loader | `cli_reflection.py:18-47` |

### 2.4. Демо ↔ реальные объекты

| Демо | Цепочка |
|------|---------|
| `demo.py` | `InMemoryBackend` + `FileBackend` для `FactualMemory` |
| `demo_experience_store.py` | `JsonlExperienceStore` → `ExperienceService` |
| `demo_identity.py` | `FileStateStore` → `IdentityService` + `NarrativeService` |
| `demo_session_manager.py` | `FileStateStore` → `SessionManager` (загрузка identity/narrative, запись событий/моментов, сохранение experience/eigenstate) |
| `demo_reflection.py` | моки + fixture_loader → `MicroReflectionService` → `DailyReflectionService` → `DeepReflectionService` |

### 2.5. TUI / Web ↔ подпроцессы

| Компонент | Интеграция |
|-----------|------------|
| `tui/tests_tab.py` | запускает pytest через подпроцесс |
| `tui/features_tab.py` | запускает демо через подпроцесс по `features_registry.FEATURES` |
| `web_dashboard/app.py` | запускает демо через подпроцесс, использует `FEATURES` |

### 2.6. Цепочка сервисов рефлексии

```text
конец сессии
  ↓
MicroReflectionService — читает ExperienceRepository
  ↓ обновляет
NarrativeRepository (recent-слой) — оптимистическая блокировка
  ↓
DailyReflectionService — читает опыт за UTC-сутки, детектит паттерны
  ↓ сохраняет
PatternStore + ReflectionEventStore
  ↓
DeepReflectionService — читает все репозитории, оценивает здоровье,
  обновляет identity и нарратив (с governance)
  ↓ предлагает
PrincipleRevisionAdvisor — пересмотр принципов
```

### 2.7. parser ↔ model и reflection ↔ identity update

- `adapters/storage/jsonl_experience_store.py:_read_all_experiences()` — JSONL → `ExperienceRecord.model_validate(...)`.
- `adapters/memory/file_backend.py:_read_facts_from_disk()` — JSONL → `FactRecord.model_validate(...)`.
- `DeepReflectionService` → `IdentityService.update_*` с созданием `IdentitySnapshot` (идемпотентно по `reflection_run_key`).

---

## 3. Пользовательские сценарии

### A. Bootstrap нового агента

Файлы: `docs/features/identity-store/`, `src/demo_identity.py`, `cli_identity.py`.

1. `IdentityService.bootstrap_identity(agent_id)`.
2. Создаётся честная пустая `Identity` с открытыми вопросами.
3. Создаётся первый `IdentitySnapshot` с описанием «Bootstrap».
4. `python -m atman.cli_identity` показывает identity.

### B. Запись опыта после сессии

Файлы: `docs/features/experience-store/`, `src/demo_experience_store.py`, `cli_experience.py`.

1. Во время сессии — `KeyMoment` + `FeltSense` (валентность, интенсивность, глубина).
2. Конец сессии — `SessionExperience`.
3. `ExperienceService.create_experience(...)` → запись в JSONL/память (immutable).
4. Позже — `add_reframing_note(experience_id, ...)`.
5. Поиск по `values_touched`, глубине, дате.

### C. Micro reflection (после сессии)

Файлы: `docs/features/reflection-engine/`, `src/demo_reflection.py`, `cli_reflection.py`.

1. `MicroReflectionService.reflect_micro(...)` берёт свежий опыт + опциональный eigenstate.
2. `ReflectionModel` (LLM или мок) генерирует резюме.
3. Обновляется `NarrativeDocument.recent_layer` с проверкой `expected_updated_at`.
4. `NarrativeWriteAuditPort` пишет аудит.

### D. Daily — детекция паттернов

1. `DailyReflectionService.reflect_daily(...)` собирает опыт за UTC-день.
2. `ReflectionModel` возвращает `list[PatternCandidate]`.
3. Запись в `PatternStore` + `ReflectionEvent(level=DAILY)`.

### E. Deep reflection + здоровье

1. `DeepReflectionService.reflect_deep(...)`: опыт + паттерны + identity.
2. Считаются критерии Йоды (autonomy, competence, integration, actualization, aspiration, purpose).
3. `ReflectionModel` предлагает правки нарратива (core/recent).
4. Создаётся `IdentitySnapshot` (идемпотентно по `reflection_run_key`).
5. Обновляются identity + предложения по нарративу + `HealthAssessment`.

### F. Факт-память: запись и поиск

Файлы: `docs/features/factual-memory/`, `src/demo.py`, `cli.py`.

1. `add "..." session_042 task` — `FactRecord` с UUID.
2. `search --tags task` — фильтрация.
3. `link <id1> <id2> "caused_by"` — связь.
4. Факты неизменяемы, добавляются только связи.

### G. Рендер NARRATIVE.md

Файлы: `docs/features/identity-store/`, `src/demo_identity.py`, `cli_identity.py`.

1. `NarrativeService.render_narrative_md(identity_id)`.
2. Три слоя: CORE / RECENT / THREADS.
3. Валидация first-person стиля.

### H. Жизненный цикл сессии с first-hand опытом

Файлы: `docs/features/session-manager/`, `src/demo_session_manager.py`, `tests/test_session_manager.py`.

1. `SessionManager.start_session(agent_id)` → загружает identity, narrative, eigenstate → `SessionContext`.
2. Во время сессии: `record_event(...)` отслеживает сырые события от нижнего агента.
3. `record_key_moment(...)` фиксирует значимые моменты с обязательной эмоциональной окраской (valence/intensity/depth).
4. Если окраска неполная → флаг `incomplete_coloring=True` (честность об ограничении).
5. `finish_session(...)` → создаёт `SessionExperience` (`recorded_by="session_manager"`) + `Eigenstate`.
6. Оба сохраняются через `StateStore` (опыт immutable, eigenstate для следующей сессии).
7. Ключевой инвариант: эмоциональная окраска ОБЯЗАНА быть (от реального переживания) или явно помечена неполной.
8. `KeyMomentInput.recorded_at` копируется в `KeyMoment.when` для согласованной временной шкалы относительно валидации и `finish`.
9. `finish_session(..., alignment_check=False)` требует непустой `alignment_notes`.
10. `list_active_sessions()` возвращает `ActiveSessionSummary` (счётчики и `started_at`) для сессий не в фазе завершения.

---

## 4. Нестандартные входы (edge cases)

### 4.1. Пустые / некорректные входы

| Сценарий | Где проверяется | Файл |
|----------|-----------------|------|
| Пустой `FactRecord.content` | `@field_validator` → `ValueError` | `core/models/fact.py:31-37` |
| Пустой `Relation.relation_type` | `@field_validator` → `ValueError` | `core/models/fact.py:71-77` |
| Пустой `Identity.self_description` | `min_length=1` | `core/models/identity.py:30` |
| `CoreValue.confidence` вне 0..1 | `@field_validator` | `core/models/identity.py:52-58` |
| `FeltSense.emotional_valence` вне -1..+1 | `@field_validator` | `core/models/experience.py:57-67` |
| `KeyMomentInput` с нулевым valence/intensity без `incomplete_coloring` | `SessionManager.record_key_moment` → `ValueError` | `core/services/session_manager.py` |
| `alignment_check=False` с пустым `alignment_notes` | `SessionManager.finish_session` → `ValueError` | `core/services/session_manager.py` |
| Повторный `finish_session` после успешного завершения | сессия снята с активного реестра → `SessionNotFoundError` | `core/services/session_manager.py` |
| Конкурентный второй `finish_session` пока первый пишет в store | `SessionAlreadyFinishedError` | `core/services/session_manager.py` |
| Лимит активных сессий | `SessionManager(..., max_active_sessions=n)` → `TooManyActiveSessionsError` в `start_session` | `core/services/session_manager.py` |
| Невалидный UUID в CLI | try/except `UUID(...)` | `cli.py:50-54` |
| Несуществующий файл опыта | `if not json_file.exists()` | `cli_experience.py:40-43` |
| **GAP**: пустой `key_moments` в `SessionExperience` | проверяется в `SessionManager.finish_session` | `core/services/session_manager.py` |
| **GAP**: пустой eigenstate (`open_threads`, `dominant_themes`, `unresolved_tensions`) | дефолт пустой список | `core/models/narrative.py:50-59` |

### 4.2. Дубли / идемпотентность

| Сценарий | Поведение | Файл |
|----------|-----------|------|
| Дубликат fact ID | `ValueError` | `adapters/memory/file_backend.py` |
| Дубликат `triggered_by` для reframing-ноты | возвращается `DUPLICATE_TRIGGERED_BY` (явно) | `core/models/experience.py` |
| Дубликат опыта при `create_experience` | `ValueError` | `adapters/storage/jsonl_experience_store.py:94` |
| Коллизия `reflection_run_key` | детерминированный ключ; `IdentitySnapshot` создаётся один раз | `core/reflection_run_keys.py` |

### 4.3. Парсинг JSON / JSONL

| Место | Обработка ошибок |
|-------|------------------|
| `FileBackend._read_facts_from_disk()` | ✅ битые строки идут через `warnings.warn(RuntimeWarning, ...)` и пропускаются (`adapters/memory/file_backend.py`); тест `tests/test_file_backend.py::test_read_facts_skips_malformed_lines_without_data_loss` |
| `JsonlExperienceStore._read_all_experiences()` | `warnings.warn(...)`, продолжение (`adapters/storage/jsonl_experience_store.py:57-73`) |
| `FileStateStore.get_experience()` / `load_identity()` / др. | ✅ `_read_json_file` оборачивает `json.JSONDecodeError` в `ValueError` с путём + строкой/колонкой (`adapters/storage/file_state_store.py`); тесты в `tests/test_file_state_store.py` |
| `cli_experience.py:cmd_add()` | общий `except Exception` (`cli_experience.py:45-56`) |

### 4.4. Governance и конкуренция

| Сценарий | Механизм | Файл |
|----------|----------|------|
| Апдейт core-нарратива требует одобрения | `GovernanceDecision.allows_core_narrative_commit()` | `core/models/governance.py:36-42` |
| Конкурентные записи нарратива | оптимистическая блокировка по `updated_at` | `core/ports/reflection.py:133-147` |
| Конфликт записи | `NarrativePersistenceConflictError` | `core/exceptions.py:8-14` |
| Падение аудита нарратива | вложенный try/except — нарратив пишется, аудит логируется warning | `core/services/narrative_revision.py:73-88` |

### 4.5. Что нужно проверить (gaps)

- ✅ Пустой `key_moments` в `SessionExperience` — `tests/test_experience_models.py::test_session_experience_rejects_empty_key_moments` (отказ через `min_length=1`).
- ✅ Битый JSONL в `FileBackend` — починено (warn-and-skip), тест `tests/test_file_backend.py::test_read_facts_skips_malformed_lines_without_data_loss`.
- ✅ `json.JSONDecodeError` в `FileStateStore` — обёрнут в `ValueError` с контекстом файла; тесты в `tests/test_file_state_store.py`.
- Валидация `confidence > 0.7` для паттернов — частично: границы 0..1 закрыты `tests/test_reflection_models.py::test_pattern_candidate_confidence_at_boundary_zero_and_one`. Семантика порога — на уровне сервисов.
- ✅ Пустой eigenstate — поведение зафиксировано тестом `tests/test_narrative_models.py::test_eigenstate_with_all_empty_collections_is_explicitly_marked` (намеренно разрешено; пробельные строки нормализуются).
- ✅ Конкурентные записи identity — `tests/test_file_state_store.py::test_save_identity_concurrent_writers_resolve_to_last_writer` (last-writer-wins). Конкурентная запись нарратива по-прежнему живёт через оптимистическую блокировку (`tests/test_narrative_revision.py`).
- ✅ Поток `GovernanceRejectedError` — `LOCKED` режим закрыт `tests/test_narrative_revision.py::test_governance_mode_locked_raises_governance_rejected_error` (плюс существующие AUTO и REVIEW-без-approval).

---

## 5. Известные баги / регрессии

### 5.1. Из истории git (последние 50 коммитов)

| Коммит | Тема | Статус |
|--------|------|--------|
| `2271b46`, `5e8d6fd`, `909aa5e` | Раунды правок по review | закрыто |
| `12e527f` | pre-commit hook + scope `pip-audit` | закрыто |
| `15bce2d` | Переключатель языка в docs site | закрыто |
| `28a2285` | Артефакты GitHub Pages | закрыто |
| `b530f36` | Сохранение связей в `FileBackend` — добавлен regression-тест | покрыто (`tests/test_file_backend.py`) |
| `e48a060`, `83df039` | Правки ruff lint/format/type | в основном закрыто |

### 5.2. Из инспекции кода

| Проблема | Где | Влияние |
|----------|-----|---------|
| Аудит коммита нарратива не блокирует запись при сбое | `core/services/narrative_revision.py:73-88` | низкое — нарратив пишется, теряется только сообщение аудита |
| Тихий пропуск битого JSONL | `adapters/memory/file_backend.py` | низкое (dev) |
| Нет миграции схем моделей | все модели имеют версию схемы, но логики миграции нет | среднее (на будущее) |
| `expected_updated_at` опционален | `core/ports/reflection.py` | среднее — зависит от дисциплины вызывающего |

### 5.3. Дыры в покрытии тестами

| Зона | Статус | Где |
|------|--------|-----|
| `FileBackend` с битым JSONL | ✅ закрыто | `tests/test_file_backend.py::test_read_facts_skips_malformed_lines_without_data_loss` |
| Конкурентные записи identity | ✅ закрыто (last-writer-wins зафиксирован) | `tests/test_file_state_store.py::test_save_identity_concurrent_writers_resolve_to_last_writer` |
| Конкурентная запись нарратива (реальная гонка потоков) | открыто — есть только мок оптимистической блокировки | `tests/test_narrative_revision.py::test_repo_update_rejects_stale_concurrency_token` |
| Идемпотентность `reflection_run_key` | ✅ закрыто | `tests/test_reflection_services.py::test_deep_reflection_repeated_run_does_not_duplicate_snapshot`, `test_daily_reflection_repeated_run_does_not_duplicate_snapshot` |
| Пустой eigenstate | ✅ закрыто | `tests/test_narrative_models.py::test_eigenstate_with_all_empty_collections_is_explicitly_marked` |
| Поток `GovernanceRejectedError` | ✅ закрыто | `tests/test_narrative_revision.py::test_governance_mode_locked_raises_governance_rejected_error` (+ существующие AUTO / REVIEW-без-approval) |
| Сквозной §3 lifecycle | ✅ закрыто | `tests/test_system_e2e_lifecycle.py::test_bootstrap_to_deep_reflection_full_lifecycle` |
| CLI surface (factual / experience / identity / reflection) | ✅ закрыто | `tests/test_cli_factual_memory.py`, `tests/test_cli_experience.py`, `tests/test_cli_identity.py`, `tests/test_cli_reflection.py` |
| Demo entrypoints (smoke) | ✅ закрыто | `tests/test_demo_smoke.py` |

### 5.4. TODO / FIXME

В исходниках явных `TODO`/`FIXME`/`HACK` не найдено. Известные ограничения зафиксированы в `reports/IMPLEMENTATION_REPORT.md`:

- ⏳ Embedded vector search — не реализовано.
- ⏳ Поддержка Graph DB — не реализовано.
- ⏳ Session Manager (WP-05) — в очереди.

---

## 6. Сводная архитектура

### Семь компонентов системы (по `README.md` и `docs/architecture/SYSTEM.md`)

1. **Factual Memory Adapter** ✅ (WP-01) — `adapters/memory/` + `core/ports/memory_backend.py`.
2. **Experience Store** ✅ (WP-02) — `core/models/experience.py` + `adapters/storage/`.
3. **Identity Store** ✅ (WP-03) — `core/models/identity.py` + `core/services/identity_service.py`.
4. **Reflection Engine** ✅ (WP-04) — `core/services/reflection_service.py`.
5. **Self-Narrative** ✅ — `core/models/narrative.py` + `core/services/narrative_service.py`.
6. **Eigenstate** ✅ — `core/models/narrative.py` (`Eigenstate`).
7. **Session Manager** ⏳ (WP-05) — в очереди.

### Два режима

- **⚡ Во время сессии:** агент работает, фиксирует опыт.
- **🌑 Между сессиями:** фоновая рефлексия (micro → daily → deep) обновляет identity и нарратив.

### Тесты

- 23 тест-модуля в `tests/`.
- Цель — ≥90% покрытия.
- CLI исключены из coverage (см. `pyproject.toml`).

### Зависимости

- Pydantic, Python ≥3.12, Rich, Textual, Streamlit, pytest, Pyright, hatchling, uv, bandit, pip-audit.

---

## 7. Предлагаемый порядок работ по тестам

Согласно issue #125:

1. **Модули** → unit-тесты на нормальный путь, граничные случаи, ошибки — для всего, что принимает вход и преобразует данные.
2. **Интеграции** → integration-тесты на каждую связку из §2 (сервис↔порт, CLI↔сервис, demo↔реальные объекты, цепочка рефлексии).
3. **Сценарии** → system/e2e-тесты на A–G из §3.
4. **Edge cases** → закрыть GAP'ы из §4.5.
5. **Регрессии** → зафиксировать тестами проблемы из §5.2 и §5.3.

---

## 8. Как поддерживать карту в актуальном состоянии

Карта — часть кода: она устаревает в момент, когда PR забывает её обновить. Конкретные правила:

1. **Добавили модуль / порт / адаптер / сервис / CLI-команду / вкладку TUI / страницу web / демо** — добавьте строку в соответствующую таблицу §1 с путём, назначением и публичным API.
2. **Подключили сервис к новому порту или добавили новую точку входа CLI/демо** — добавьте строку в §2 (подраздел зависит от типа стыка).
3. **Добавили или изменили e2e-флоу** — добавьте или поправьте сценарий в §3 со ссылками на файлы.
4. **Добавили валидацию входа, защиту от дублей или обработчик парсинга JSON** — зафиксируйте в §4.1–4.3 и удалите соответствующий «GAP», если он закрыт.
5. **Починили регрессию** — добавьте строку в §5.1 (хеш коммита + тема) и добавьте regression-тест в `tests/`.
6. **Написали новые тесты** — привяжите их к разделу карты, который они покрывают (§1 → unit, §2 → integration, §3 → system/e2e, §4 → edge cases, §5 → регрессии). В описании PR явно укажите эту привязку.
7. **Двуязычная синхронизация** — `SYSTEM_MAP.md` — канонический английский. Сначала правится он, затем синхронизируется `SYSTEM_MAP-ru.md`. То же правило, что и для `README.md`/`README-ru.md`, `MANIFEST.md`/`MANIFEST-ru.md`, `SYSTEM.md`/`SYSTEM-ru.md`.
