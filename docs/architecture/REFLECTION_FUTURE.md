# Reflection Engine — будущие изменения

> **Статус:** частично реализовано. См. таблицу этапов §11. Сделано:
> R1 (новый порт `SessionRepository` + адаптер), R1.1 (`PostgresStateStore` v2),
> R2 (миграция `reframing_notes.experience_id → session_id`),
> R3 (`DailyReflectionService` на `SessionRepository`),
> R4 (`DeepReflectionService` на `SessionRepository`),
> R14 (удалён `ExperienceViewRepository` compat-адаптер — все три сервиса
> Micro/Daily/Deep теперь работают через `SessionRepository`),
> R11.5 (self-apply), R13 (overload monitor),
> R5 (`StructuredMarkersAggregator` — daily patterns из `structured_markers`),
> R12 (agent-driven `request_reflection` тул + drain очереди в Daily/Deep),
> R6 (`DivergenceAggregator` + `DivergenceEventStore` порт), R8 (`FindingsTriage`),
> R7 (`EntityStanceFormulator` — Daily формулирует, Deep пересматривает).
>
> Этот документ — единое место, куда собраны все изменения Reflection Engine,
> которые понадобятся **после** того как память переедет на новую архитектуру
> (Entity Registry, standalone key_moments с `session_id`, `structured_markers`,
> `entity_stance`, `validation_findings`, `entity_relations`, salience decay).
>
> Следующие шаги: R5+ (агрегаторы новых сигналов и пр.).

---

## 1. Зачем переписывать Reflection

Когда память реструктурирована:

- `SessionExperience` больше не первичная единица — её собирает compat-адаптер.
- `key_moments` имеют `structured_markers` (cognitive_load, boundary_event, …) — Reflection пока их не читает.
- Появились `entity_stance`, `entity_relations`, `validation_findings` — Reflection пока их не пишет и не читает.
- Появились `divergence_events` — Reflection пока их не агрегирует.
- `reframing_notes` живёт через legacy `experience_id` поле — нужно переехать на `session_id`.

Reflection — главный потребитель и автор этих новых сигналов. Сейчас он этого не видит, и поэтому новая память не "оживает". Этот документ — что нужно подключить, чтобы оживить.

---

## 2. Принципы

1. **Reflection — это интерпретатор, не агрегатор.** Никаких `avg(valence_toward_entity)`. Stance формулируется словами через LLM-вызов, всегда с `based_on_moment_ids`.
2. **Старый stance не удаляется.** `superseded_at` + `superseded_by`. История сохраняется.
3. **`is_provisional=true` по умолчанию.** Stance становится устойчивым только после подтверждения новыми моментами в течение времени.
4. **Reflection не инструмент срочной починки.** Если запускается слишком часто — calibrate пороги, не "запускать чаще".
5. **Findings — это видимое состояние памяти.** Reflection их читает как часть самонаблюдения, не как служебный лог.

---

## 3. Замена контракта `ExperienceRepository`

### 3.1 Что заменяется

Текущий порт (`src/atman/core/ports/reflection.py`):

```python
class ExperienceRepository(Protocol):
    def get(experience_id: UUID) -> SessionExperience | None: ...
    def get_by_session(session_id: UUID) -> list[SessionExperience]: ...
    def get_recent(limit: int) -> list[SessionExperience]: ...
    def get_in_range(start, end) -> list[SessionExperience]: ...
    def update(experience: SessionExperience) -> None: ...
    def add_reframing_note(experience_id, note) -> ReframingNoteAppendResult: ...
```

### 3.2 На что заменяется

Новый порт (`src/atman/core/ports/session_repository.py`):

```python
class SessionRepository(Protocol):
    def get_session(session_id: UUID) -> Session | None: ...
    def list_recent_sessions(limit: int) -> list[Session]: ...
    def get_sessions_in_range(start, end) -> list[Session]: ...
    def get_key_moments_for_session(session_id: UUID) -> list[KeyMoment]: ...
    def get_key_moments_in_range(start, end) -> list[KeyMoment]: ...
    def add_reframing_note(session_id: UUID, note: ReframingNote) -> ReframingNoteAppendResult: ...
```

### 3.3 Что меняется в Reflection Engine

`src/atman/core/services/reflection_service.py`:

- Заменить везде где сейчас `experience: SessionExperience` → пара `(session: Session, moments: list[KeyMoment])`.
- `experience.key_moment_ids` → `moments` напрямую.
- `experience.salience` → нет. Salience теперь живёт на каждом `KeyMoment` отдельно. Если нужен агрегат "брайтность сессии" — считать `mean(moments.salience)` явно по месту.
- `experience.avg_emotional_intensity` / `has_profound_moment` — те же, считать по месту от moments.
- `experience.recorded_by`, `incomplete_coloring`, `identity_snapshot_id` — теперь на каждом KeyMoment отдельно. Reflection пусть берёт первый (или сводит).

`src/atman/adapters/reflection_compat/experience_view_repository.py` — **удаляется** после переезда.

### 3.4 Миграция `reframing_notes`

Текущая схема: `agent_N.reframing_notes.experience_id`. После реструктуризации `experience_id` указывает на удалённую `experiences` (FK дропнут, поле — legacy).

Миграция XX (после Reflection-переезда):
- `ALTER TABLE reframing_notes ADD COLUMN session_id UUID`
- `UPDATE reframing_notes SET session_id = experience_id` (для legacy записей `experience_id` == старому `experiences.session_id`)
- `ALTER TABLE reframing_notes ALTER COLUMN session_id SET NOT NULL`
- `ALTER TABLE reframing_notes DROP COLUMN experience_id`
- `ADD CONSTRAINT reframing_notes_session_fk FOREIGN KEY (session_id) REFERENCES sessions(id)`

### 3.5 `reflections.experience_refs`

Текущая колонка хранит `UUID[]` — ссылки на старые `experiences.id`. После переезда:
- Семантически это уже `session_id[]` (потому что `experiences.id` бэкфилит в `session_id`).
- Можно либо переименовать колонку в `session_refs`, либо оставить имя как есть и задокументировать что значения интерпретируются как `session_id`.

Рекомендация: переименовать одной миграцией, чтобы не было путаницы. PatternStore хранит то же.

---

## 4. Daily Reflection — новые задачи

### 4.1 Чтение `structured_markers`

```
для каждого нового key_moment за день:
    читаем moment.structured_markers (если есть)
    агрегируем по типам:
        cognitive_load распределение
        boundary_event распределение
        trust_signal распределение
        agency_level распределение
    если какой-то тип имеет 5+ моментов с одинаковым значением:
        создаём PatternCandidate(pattern_type=COGNITIVE/RELATIONAL/...)
```

Реализация: новый метод `DailyReflectionService._analyze_structured_markers(moments)`. Запись через существующий `PatternStore.save_with_detection_key()`.

### 4.2 Чтение `divergence_events`

```
читаем divergence_events за день
группируем по divergence_type
если какой-то тип >= 3 раз за день:
    создаём PatternCandidate(pattern_type=BEHAVIOR, description="<тип> recurring")
если есть severity='rupture' хотя бы раз:
    добавляем в reflection content явное наблюдение
```

### 4.3 Формулирование `entity_stance`

```
для каждого entity_id с >= 5 новыми key_moment_entities за период:
    собираем эти моменты + их structured_markers
    LLM-вызов: "На основе этих моментов сформулируй своё текущее
                отношение к {entity.canonical_name}"
    получаем stance_text, valence_estimate, intensity_estimate, confidence
    EntityStanceStore.write_stance(
        entity_id, stance_text, based_on_moments=[...],
        formed_in_reflection=current_reflection.id,
        is_provisional=True
    )
    если старый stance существует → он автоматически superseded_at = now
```

Новый компонент: `EntityStanceFormulator` (внутри `reflection/`), использует `ReflectionModel` (тот же OpenAI-compatible). Промт — отдельный шаблон в `adapters/reflection/prompts.py`: `STANCE_FORMULATION_PROMPT`.

### 4.4 Обработка `validation_findings` уровня B

```
для каждого finding со status='unresolved' и severity in ('info','warning'):
    if finding_type == 'orphan_entity':
        # память не выбрасываем по mention_count
        mark_resolved(finding, resolution='ignored', note='kept by policy')
    elif finding_type == 'similar_entities':
        # проверка через embedding + LLM "это правда один?"
        if confirmed_duplicate:
            EntityRegistry.merge_entities(keep_id, merge_id, audit_reason)
            mark_resolved(finding, resolution='fixed')
        else:
            mark_resolved(finding, resolution='ignored', note='not duplicates')
    elif finding_type == 'pending_structured_markers':
        # async didn't deliver — записать что приняли как есть
        mark_resolved(finding, resolution='ignored', note='accepted as-is')
    elif finding_type == 'analysis_failed':
        mark_resolved(finding, resolution='requires_attention')
```

Новый компонент: `FindingsTriage` (внутри `reflection/`). Подключается в `DailyReflectionService`.

---

## 5. Deep Reflection — новые задачи

### 5.1 Долгосрочные паттерны (30 дней)

- Тренды `cognitive_load` по неделям.
- Тренды `agency_level` (regression vs progress).
- Тренды `growth_indicator`.
- Паттерны по конкретным сущностям (например: с этой сущностью моменты стабильно `boundary_event=tested`).

### 5.2 Пересмотр давних `entity_stance`

```
для каждого entity_stance со statused='current' и formed_at > 30 дней назад:
    если за этот период появились новые моменты с этой сущностью:
        пересмотр через LLM
        если изменилось — write_stance(... superseded предыдущий)
        если нет — confidence повышается, is_provisional=False
```

### 5.3 Формулирование `entity_relations`

```
для каждой пары сущностей которые часто упоминаются вместе:
    LLM-вызов: "Что связывает A и B? Какой тип отношения? Дата начала?"
    если получили relation_type c confidence >= 0.7:
        EntityRelations.add(from=A, to=B, type=...,
                            learned_by='reflection', learned_from_fact_id=...)
```

Дополняет то, что mREBEL извлекает в реальном времени из текстов фактов.

### 5.4 Обработка merge candidates

`MemoryGuardian` пишет findings типа `similar_entities` с deталями (cosine, mention_counts). Deep reflection:

```
для каждого 'similar_entities' finding:
    LLM-вызов: "Это правда один человек/объект? Контекст A: ..., контекст B: ...
                Если да — какое каноническое имя выбрать?"
    если confirmed:
        EntityRegistry.merge_entities(keep=...)
        переписать FK в fact_entities, key_moment_entities, entity_stance, entity_relations
    finding.resolution = 'fixed' или 'ignored' + note
```

### 5.5 Identity-level выводы

После анализа всего выше — обновление Identity:
- Новые ценности? → `identity.core_values.append(...)`
- Изменения в принципах? (например, новый сформировался из 10 моментов с `principles_confirmed`)
- Закрытые `open_questions`?
- Новые `open_questions`?

Это уже частично работает. Расширение — учитывать `structured_markers` и `entity_stance` как сигналы.

---

## 6. Триггеры запуска

### 6.1 Plan-based (как сейчас)

Daily в конце дня, Deep раз в неделю — через CLI / scheduler. Не меняется.

### 6.2 Flag-based (новое)

`MemoryGuardian` периодически пишет findings. Если в `validation_findings` накапливается N+ unresolved уровня B (например, N=20) → выставляется флаг `reflection_needed=true` в `public.agents.metadata` или отдельной таблице. Ближайший scheduled запуск проходит с этим флагом и в стартовый контекст подгружает findings приоритетно.

### 6.3 Agent-driven (новое)

Новый тул в `src/atman/adapters/agent/tools/`: `request_reflection(reason: str)`. Агент сам решает что пора. `reason` идёт в стартовый контекст рефлексии.

Идемпотентность: один и тот же `reason` в пределах часа — не запускает повторно (через `run_keys`).

### 6.4 User-driven (как сейчас)

CLI команда — без изменений.

---

## 7. Мониторинг частоты Reflection

`reflection_overload` — critical alert:

```
если daily reflection > 1 раз в день за последние 3 дня → calibrate
если deep reflection > 1 раз в 3 дня → reflection_overload critical
```

Причины такого алерта (не лечатся "пускать чаще"):
- порог `validation_findings` flag-trigger слишком низкий → поднять
- pipeline ломается и пишет много findings → разбираться
- reflection не справляется с работой → разбираться

Реализация: новая таблица или поле в `reflections` для отслеживания частоты, либо использовать существующий `reflection_event_audit`.

---

## 8. Размер промптов

Daily reflection — окно ~24 часа, размер промпта зависит от количества событий за день. Deep reflection — 7-30 дней, может быть большим.

При размере >50k токенов:
- Делим moments на батчи по 20-30 и обрабатываем последовательно
- Каждый батч → промежуточные паттерны
- Финальный промпт → синтез паттернов

Reflection использует отдельную LLM (`gemma3:27b-it-qat` через Ollama по умолчанию, или OpenAI-compatible endpoint). Это единственное место где LLM используется в pipeline Atman за пределами финального ответа агенту.

---

## 9. Принципы работы со `stance`

- Stance — **интерпретация**, не агрегация. LLM читает моменты и формулирует словами что в них общего.
- Старый stance не удаляется — `superseded_at` + `superseded_by`.
- `based_on_moment_ids` обязателен — всегда видно на каких моментах основан stance.
- `is_provisional=true` по умолчанию. Чтобы стать "устоявшимся" — подтверждение через новые моменты в течение времени.

---

## 10. Что Reflection делает с findings

Прочитал `similar_entities`:
- Проверил действительно ли дубликаты
- Если да → `EntityRegistry.merge_entities()` + `finding.resolution='fixed'`
- Если нет → `finding.resolution='ignored'` + note

Прочитал `orphan_entity`:
- Решил оставить (память не выбрасываем по mention_count)
- `finding.resolution='ignored'`

Прочитал `affect_detector_silent` (критическое):
- Понял что pipeline сломан
- Это не моя задача чинить — `finding.resolution='requires_attention'`
- + critical alert для пользователя

---

## 11. Этапы реализации (примерные)

После того как основная итерация памяти стабилизирована (этапы 0-17 из основного плана):

| # | Этап | Файлы | Статус |
|---|---|---|---|
| R1 | Новый порт `SessionRepository` + адаптер над StateStore | `core/ports/session_repository.py`, `adapters/reflection/state_store_session_repository.py` | ✅ done |
| R1.1 | Переписать `PostgresStateStore` на v2 (per-agent schemas + Session API) | `adapters/state/postgres_state_store.py` | ✅ done |
| R2 | Миграция `reframing_notes.experience_id → session_id` + DROP старого FK | `migrations/versions/0014_reframing_notes_session_id.sql` | ✅ done (PR #565) |
| R3 | Переезд `DailyReflectionService` на `SessionRepository` | `core/services/reflection_service.py`, `core/services/session_experience_view.py` | ✅ done (PR #565) |
| R4 | Переезд `DeepReflectionService` на `SessionRepository` | `core/services/reflection_service.py` | ✅ done (PR #569) |
| R-Micro | Переезд `MicroReflectionService` на `SessionRepository` | `core/services/reflection_service.py` | ✅ done |
| R5 | `StructuredMarkersAggregator` → паттерны из markers | `core/services/structured_markers_aggregator.py` | ✅ done |
| R6 | `DivergenceAggregator` → паттерны из divergence_events | `core/services/divergence_aggregator.py` + порт `DivergenceEventStore` + in-memory адаптер | ✅ done |
| R7 | `EntityStanceFormulator` + промт | `core/services/entity_stance_formulator.py`, `adapters/reflection/prompts.py` (`SYSTEM_PROMPT_STANCE`); подключено в `DailyReflectionService.formulate_for_new_entities` и `DeepReflectionService.revise_stale` | ✅ done |
| R8 | `FindingsTriage` | `core/services/findings_triage.py` | ✅ done |
| R9 | `EntityRelationsFormulator` (для deep reflection) | новый компонент | TODO |
| R10 | Merge handler (для deep reflection) | новый компонент | TODO |
| R11 | Identity-level выводы из новых сигналов | расширение существующих сервисов | частично (R11.5 self-apply ✅ в #559) |
| R12 | Тулы `request_reflection` для agent-driven | `adapters/agent/tools.py`; `DailyReflectionService` / `DeepReflectionService` дрейнят очередь | ✅ done |
| R13 | `reflection_overload` мониторинг | новый компонент | ✅ done (PR #559) |
| R14 | Удаление `ExperienceViewRepository` compat-адаптера | удалён `src/atman/adapters/reflection_compat/` | ✅ done |
| R15 | Переименование `reflections.experience_refs` → `session_refs` (если решено) | новая миграция | TODO |

Эти этапы можно делать параллельно с поздними этапами основного плана, если основные миграции памяти уже на проде стабилизировались.

---

## 12. Что НЕ делаем

- Не агрегируем эмоции автоматически (никакого `avg(valence_toward_entity)` — план v3 §17).
- Не выдаём в RAG агрегаты прошлых чувств — Reflection пишет stance, RAG читает stance.
- Не запускаем reflection чаще как лечение `reflection_overload` — calibrate пороги.
- Не удаляем старые stance, паттерны, identity_snapshots — только `superseded`.
- Не используем Reflection для срочной починки pipeline-проблем — это видимое состояние, не fix.

---

_Документ открыт для расширения по ходу реализации._
