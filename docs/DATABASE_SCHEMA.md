# Схема базы данных Atman

> Актуально на: 2026-05-16  
> Источники истины: `migrations/versions/0001–0016`, `eval/migrations/versions/0010–0040`

---

## Архитектура изоляции

Память агентов организована в три уровня изоляции:

```
public.*          — объективный слой (факты, граф фактов, реестр агентов, maintenance)
                    Изоляция: Row-Level Security по session var atman.current_agent
                    
agent_{N}.*       — субъективный и эпизодический слой (сессии, моменты, идентичность,
                    рефлексии, audit/inbox, сущности)
                    Изоляция: физическое разделение по схемам, RLS не нужен
                    
eval.*            — оценочная схема (бенчмарки, метрики качества)
                    Изоляция: отдельные роли atman_eval_owner / writer / reader
```

**Роли БД:**
- `atman` — владелец (superuser-like). **Не использовать в приложении** — обходит RLS
- `atman_app` — роль приложения. Подключаться только через неё, RLS действует
- `atman_eval_owner / writer / reader` — роли eval-схемы

**Расширения PostgreSQL:** `uuid-ossp`, `vector` (pgvector), `pg_trgm`

---

## Общие таблицы (схема `public`)

### `public.agents` — реестр агентов

Глобальная таблица без RLS. Одна строка на агента-личность.

| Колонка | Тип | Описание |
|---------|-----|----------|
| `serial_id` | BIGSERIAL | Порядковый номер; используется как суффикс схемы (`agent_1`, `agent_2`, ...) |
| `id` | UUID PK | UUID агента; используется в FK и RLS |
| `name` | TEXT | Имя агента |
| `description` | TEXT | Описание / назначение агента |
| `created_at` | TIMESTAMPTZ | Дата создания |

> При создании агента через `AgentsRegistry.create()` автоматически вызывается `public.create_agent_schema(uuid, serial_id)` — создаётся схема `agent_{serial_id}` со всеми таблицами.

---

### `public.facts` — фактическая память

Верифицируемые факты без интерпретации. **RLS: включён, FORCED.**

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | UUID PK | |
| `agent_id` | UUID NOT NULL | Владелец. **RLS-поле**: `agent_id = atman.current_agent` |
| `content` | TEXT NOT NULL | Текст факта |
| `source` | TEXT NOT NULL | Источник (откуда получен факт) |
| `tags` | TEXT[] | Теги. GIN-индекс для `@>` запросов |
| `status` | `fact_status` | `active` / `disputed` / `superseded` / `invalidated` |
| `embedding` | halfvec(1024) | Эмбеддинг BGE-M3 (float16). NULL пока модель недоступна — система деградирует до текстового поиска |
| `salience` | FLOAT [0..1] | Значимость факта (default 0.5) |
| `confirmation_count` | INT | Счётчик подтверждений |
| `last_confirmed_at` | TIMESTAMPTZ | Дата последнего подтверждения |
| `invalidated_at` | TIMESTAMPTZ | Дата инвалидации |
| `invalidation_note` | TEXT | Причина инвалидации |
| `superseded_by` | UUID → facts | FK на замещающий факт |
| `disputed_at` | TIMESTAMPTZ | Дата оспаривания |
| `created_at` | TIMESTAMPTZ | |
| `metadata` | JSONB | Произвольные мета-данные |

**Политика RLS** `facts_isolation`: `USING (agent_id = NULLIF(current_setting('atman.current_agent', TRUE), '')::UUID)`

**Индексы:** `(agent_id, status, created_at DESC)`, GIN на `tags`, GIN-trgm на `content`, HNSW на `embedding`

---

### `public.fact_relations` — граф фактов

Направленные рёбра между фактами. **RLS: включён, FORCED.** Оба конца ребра должны принадлежать текущему агенту.

| Колонка | Тип | Описание |
|---------|-----|----------|
| `source_id` | UUID → facts | Исходный факт. CASCADE DELETE |
| `target_id` | UUID → facts | Целевой факт. CASCADE DELETE |
| `relation_type` | TEXT | Тип связи (произвольная строка) |
| `created_at` | TIMESTAMPTZ | |
| `metadata` | JSONB | |

**PK:** `(source_id, target_id, relation_type)`

**Политика RLS** `fact_relations_isolation`: проверяет `agent_id` обоих концов через EXISTS в `facts`.

> **Не путать с `entity_relations`:** `fact_relations` связывает **утверждения** (строки `facts`: confirms, contradicts, led_to). `agent_{N}.entity_relations` связывает **именованные сущности** мира (люди, места). `agent_{N}.fact_entities` привязывает факт к сущности. Линейное замещение факта — поле `facts.superseded_by`.

---

### `public.maintenance_jobs` — очередь фоновых задач

Общая очередь для maintenance-задач. **RLS: отсутствует.**

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | UUID PK | |
| `job_name` | TEXT | `salience_decay` / `memory_guardian_scan` / `mrebel_extract` / `lingvo_enrich` / `entity_merge` / `other` |
| `agent_id` | UUID → agents | Nullable: NULL для глобальных задач |
| `payload` | JSONB | Параметры задачи |
| `run_key` | TEXT UNIQUE | Ключ дедупликации (необязательный) |
| `status` | TEXT | `pending` / `running` / `succeeded` / `failed` / `skipped` |
| `scheduled_at` | TIMESTAMPTZ | Запланированное время запуска |
| `started_at` | TIMESTAMPTZ | Фактический старт |
| `finished_at` | TIMESTAMPTZ | Завершение |
| `error` | TEXT | Текст ошибки (если failed) |
| `result` | JSONB | Результат выполнения |

---

## Таблицы агентских схем (`agent_{N}.*`)

Для каждого агента создаётся отдельная схема `agent_{serial_id}`. Изоляция — физическая, RLS не нужен. Схема создаётся вызовом `public.create_agent_schema(agent_uuid, serial_id)`.

---

### `agent_{N}.sessions` — сессии

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | UUID PK | |
| `agent_id` | UUID → public.agents | |
| `started_at` | TIMESTAMPTZ | |
| `ended_at` | TIMESTAMPTZ | NULL для активной сессии |
| `status` | TEXT | `active` / `completed` / `interrupted` |
| `identity_snapshot_id` | UUID | Снимок идентичности на момент старта сессии |
| `close_reason` | TEXT | `timeout_sleep` / `menu_timeout` / `restart` / `forced` / `interrupted` |
| `agent_recap` | TEXT | Краткое резюме сессии от агента |
| `restart_reason` | TEXT | Причина перезапуска (если restart) |
| `user_language` | TEXT | Язык пользователя (default: `ru`) |
| `overall_tone` | FLOAT [-1..1] | Эмоциональный тон всей сессии |
| `key_insight` | TEXT | Главный инсайт сессии |
| `unexamined_fact_refs` | UUID[] | Факты, добавленные за сессию, ещё не отражённые в рефлексии |

---

### `agent_{N}.identity` — идентичность

Одна строка на агента. Изменяется рефлексией или оператором.

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | UUID PK | |
| `agent_id` | UUID UNIQUE → public.agents | |
| `self_description` | TEXT | Самоописание агента |
| `core_values` | JSONB (`[]`) | Список ценностей |
| `habits` | JSONB (`[]`) | Привычки |
| `principles` | JSONB (`[]`) | Принципы поведения |
| `goals` | JSONB (`[]`) | Текущие цели |
| `open_questions` | JSONB (`[]`) | Открытые вопросы для самоисследования |
| `emotional_baseline` | FLOAT [-1..1] | Эмоциональный базис (default: 0.0) |
| `updated_at` | TIMESTAMPTZ | |

---

### `agent_{N}.identity_snapshots` — снимки идентичности

**ИММУТАБЕЛЬНЫ** (триггер `prevent_snapshot_modification()` блокирует UPDATE).

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | UUID PK | |
| `agent_id` | UUID → public.agents | |
| `snapshot_at` | TIMESTAMPTZ | Момент снимка |
| `description` | TEXT | Описание контекста снимка |
| `state` | JSONB NOT NULL | Полное состояние идентичности на момент снимка |

---

### `agent_{N}.narrative` — нарратив

Одна строка на агента. Живой документ самовосприятия.

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | UUID PK | |
| `agent_id` | UUID UNIQUE → public.agents | |
| `core_layer` | TEXT | Глубинный нарратив (меняется редко) |
| `recent_layer` | TEXT | Актуальный нарратив (меняется рефлексией) |
| `threads` | JSONB (`[]`) | Активные нарративные нити |
| `eigenstate` | JSONB (`{}`) | Собственное состояние: эмоциональный тон, когнитивная нагрузка, незакрытые темы |
| `updated_at` | TIMESTAMPTZ | |

---

### `agent_{N}.key_moments` — ключевые моменты

Эпизодическая память. Семантические поля **ИММУТАБЕЛЬНЫ** (field-level триггер). Добавлять можно только новые строки.

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | UUID PK | |
| `session_id` | UUID NOT NULL → sessions | Сессия, в которой произошёл момент |
| `agent_id` | UUID → public.agents | |
| `what_happened` | TEXT NOT NULL | **ИММУТ.** Описание события |
| `emotional_valence` | FLOAT [-1..1] NOT NULL | **ИММУТ.** Эмоциональная окраска |
| `emotional_intensity` | FLOAT [0..1] NOT NULL | **ИММУТ.** Интенсивность переживания |
| `depth` | TEXT NOT NULL | **ИММУТ.** `surface` / `meaningful` / `profound` |
| `why_it_matters` | TEXT | **ИММУТ.** Почему важно |
| `values_touched` | TEXT[] | **ИММУТ.** Затронутые ценности (GIN-индекс) |
| `principles_confirmed` | TEXT[] | **ИММУТ.** Подтверждённые принципы |
| `principles_questioned` | TEXT[] | **ИММУТ.** Поставленные под сомнение принципы |
| `what_changed` | TEXT | **ИММУТ.** Что изменилось |
| `recorded_at` | TIMESTAMPTZ | **ИММУТ.** Время записи |
| `embedding` | halfvec(1024) | Эмбеддинг (HNSW-индекс для семантического поиска) |
| `salience` | REAL [0..1] | Текущая значимость (затухает со временем, default 1.0) |
| `salience_at` | TIMESTAMPTZ | Момент последнего расчёта значимости |
| `last_accessed_at` | TIMESTAMPTZ | Последнее обращение |
| `access_count` | INT | Счётчик обращений |
| `incomplete_coloring` | BOOLEAN | Флаг незавершённой эмоциональной окраски |
| `recorded_by` | TEXT | Компонент-автор записи (default: `session_manager`) |
| `identity_snapshot_id` | UUID | Снимок идентичности на момент записи |
| `importance` | REAL [0..1] | Субъективная важность (default 0.5) |
| `context_halo` | JSONB | Контекстный ореол (предыдущий разговор, настроение, ...) |
| `fact_refs` | UUID[] | Ссылки на факты `public.facts` (GIN-индекс) |
| `structured_markers` | JSONB | Структурированные маркеры (GLiNER-сигналы и др.) |
| `structured_markers_version` | TEXT | Версия схемы маркеров |

**Индексы:** `(agent_id)`, `(agent_id, session_id)`, `(agent_id, depth)`, `(agent_id, salience DESC)`, GIN на `values_touched`, GIN на `fact_refs`, HNSW на `embedding`

---

### `agent_{N}.reframing_notes` — записи переосмысления

**APPEND-ONLY** (триггер `prevent_reframing_modification()` блокирует UPDATE).

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | UUID PK | |
| `session_id` | UUID NOT NULL → sessions | Сессия (после миграции 0014) |
| `agent_id` | UUID → public.agents | |
| `reflection` | TEXT NOT NULL | Текст переосмысления |
| `reflection_type` | TEXT | `growth` / `reinterpretation` / `closure` / `insight` |
| `created_at` | TIMESTAMPTZ | |

> Миграция 0014 удалила легаси-колонку `experience_id` и сделала `session_id` NOT NULL с FK.

---

### `agent_{N}.reflections` — рефлексии

Субъективный слой: результаты micro/daily/deep рефлексии. **Без RLS** (изоляция схемой).

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | BIGSERIAL PK | |
| `agent_id` | UUID NOT NULL → public.agents | |
| `level` | `reflection_level` | `micro` / `daily` / `deep` |
| `created_at` | TIMESTAMPTZ | |
| `session_id` | UUID → sessions | Только для `level='micro'` |
| `period_start` | TIMESTAMPTZ | Для `daily`/`deep` |
| `period_end` | TIMESTAMPTZ | Для `daily`/`deep` |
| `content` | TEXT NOT NULL | Полный текст рефлексии |
| `summary` | TEXT | Краткое резюме |
| `experience_refs` | UUID[] | UUID `key_moments`, охваченных рефлексией |
| `reframing_note_ids` | UUID[] | UUID `reframing_notes`, созданных рефлексией |
| `model_provider` | TEXT | LLM-провайдер |
| `model_name` | TEXT | Модель |
| `schema_version` | INT | Версия схемы (текущая: 1) |
| `metadata` | JSONB | |

**Индексы:** `(created_at DESC)`, `(level, created_at DESC)`, GIN на `experience_refs`, partial на `session_id`

---

### `agent_{N}.self_applied_changes` — аудит самостоятельных изменений

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | UUID PK | |
| `applied_at` | TIMESTAMPTZ | |
| `agent_id` | UUID | Nullable для narrative-only изменений |
| `actor` | TEXT | `reflection_daily` / `reflection_deep` / `human_via_reflection_review` |
| `reflection_event_id` | UUID NOT NULL | UUID события Reflection Engine (не BIGSERIAL `reflections.id`) |
| `target_kind` | TEXT | См. миграцию 0012 |
| `target_ref` | TEXT | |
| `before_snapshot` | JSONB | |
| `after_snapshot` | JSONB | |
| `rationale` | TEXT | |
| `confidence_self_assessment` | TEXT | |
| `based_on_moment_ids` | UUID[] | |
| `reverted_at` | TIMESTAMPTZ | |
| `reverted_reason` | TEXT | |
| `reverted_by_change_id` | UUID → self_applied_changes | |

---

### `agent_{N}.pending_human_review` — очередь на проверку человеком

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | UUID PK | |
| `created_at` | TIMESTAMPTZ | |
| `created_by` | TEXT | |
| `reflection_event_id` | UUID | |
| `kind` | TEXT | `identity_change_doubt` / `narrative_change_doubt` / `high_salience_judgement` |
| `question` | TEXT | |
| `context` | JSONB | Рекомендуется `agent_id` в JSON для multi-agent |
| `priority` | TEXT | `normal` / `high` |
| `resolved_at` | TIMESTAMPTZ | |
| `resolution` | TEXT | `accepted` / `rejected` / `modified` / `dismissed` |
| `resolution_note` | TEXT | |
| `applied_change_id` | UUID → self_applied_changes | |

**Индекс:** `(priority, created_at) WHERE resolved_at IS NULL`

---

### `agent_{N}.entities` — реестр сущностей

Именованные сущности, наблюдаемые/известные агенту.

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | UUID PK | |
| `agent_id` | UUID → public.agents | |
| `canonical_name` | TEXT NOT NULL | Каноническое имя |
| `entity_type` | TEXT | `person` / `place` / `organization` / `object` / `topic` / `event` / `tool` / `health_condition` / `skill` / `value` / `principle` |
| `embedding` | halfvec(1024) | Для семантического поиска (HNSW) |
| `description` | TEXT | Описание сущности |
| `first_seen_at` | TIMESTAMPTZ | Первое упоминание |
| `last_seen_at` | TIMESTAMPTZ | Последнее упоминание |
| `mention_count` | INT | Счётчик упоминаний (default 1) |
| `needs_disambiguation` | BOOLEAN | Требует уточнения (похожие имена) |
| `schema_version` | TEXT | Версия схемы записи (default: `atman-1.0`) |
| `metadata` | JSONB | |

**Уникальный индекс:** `(agent_id, canonical_name, entity_type)`

---

### `agent_{N}.entity_aliases` — псевдонимы сущностей

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | UUID PK | |
| `entity_id` | UUID → entities | CASCADE DELETE |
| `agent_id` | UUID | |
| `alias_text` | TEXT | Альтернативное имя/форма |
| `learned_from_fact_id` | UUID | Soft ref → public.facts (без FK) |
| `learned_at` | TIMESTAMPTZ | |

**Уникальный индекс:** `(entity_id, alias_text)`

---

### `agent_{N}.entity_relations` — связи между сущностями

Направленный граф отношений между сущностями.

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | UUID PK | |
| `agent_id` | UUID | |
| `from_entity_id` | UUID → entities | RESTRICT |
| `to_entity_id` | UUID → entities | RESTRICT |
| `relation_type` | TEXT | Тип отношения (произвольная строка) |
| `since` | DATE | Начало отношения |
| `until` | DATE | Конец отношения (NULL = активно) |
| `confidence` | REAL [0..1] | Уверенность в существовании связи |
| `learned_from_fact_id` | UUID | Soft ref → public.facts |
| `learned_by` | TEXT | `mrebel` / `rules` / `reflection` / `manual` |
| `created_at` | TIMESTAMPTZ | |

**Уникальный индекс:** `(from_entity_id, to_entity_id, relation_type)`  
**Индексы:** `(agent_id, from_entity_id) WHERE until IS NULL`, `(agent_id, to_entity_id) WHERE until IS NULL`

---

### `agent_{N}.entity_stance` — позиция агента по сущностям

Версионированная оценка отношения агента к сущности. Активная позиция — одна строка с `superseded_at IS NULL`.

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | UUID PK | |
| `agent_id` | UUID | |
| `entity_id` | UUID → entities | RESTRICT |
| `stance_text` | TEXT NOT NULL | Текст позиции |
| `valence` | REAL [-1..1] | Эмоциональная окраска (-1 негатив, +1 позитив) |
| `intensity` | REAL [0..1] | Интенсивность |
| `formed_at` | TIMESTAMPTZ | Когда сформировалась |
| `formed_in_reflection_id` | UUID | Soft ref → reflections / ReflectionEvent UUID |
| `based_on_moment_ids` | UUID[] | Ключевые моменты-основания |
| `superseded_at` | TIMESTAMPTZ | NULL = активная позиция |
| `superseded_by` | UUID → entity_stance | Self-ref на новую позицию |
| `confidence` | REAL [0..1] | Уверенность |
| `is_provisional` | BOOLEAN | Предварительная позиция (default TRUE) |

**Уникальный индекс:** `(agent_id, entity_id) WHERE superseded_at IS NULL` — гарантирует не более одной активной позиции на сущность

---

### `agent_{N}.fact_entities` — связь фактов с сущностями

| Колонка | Тип | Описание |
|---------|-----|----------|
| `fact_id` | UUID → public.facts | CASCADE DELETE |
| `entity_id` | UUID → entities | RESTRICT |
| `agent_id` | UUID | |
| `role` | TEXT | `subject` / `object` / `context` / `mentioned` |
| `confidence` | REAL [0..1] | |

**PK:** `(fact_id, entity_id, role)`

---

### `agent_{N}.key_moment_entities` — связь моментов с сущностями

| Колонка | Тип | Описание |
|---------|-----|----------|
| `key_moment_id` | UUID → key_moments | RESTRICT |
| `entity_id` | UUID → entities | RESTRICT |
| `agent_id` | UUID | |
| `involvement` | TEXT | `primary_subject` / `present` / `mentioned` / `evoked` |
| `valence_toward_entity` | REAL [-1..1] | Эмоциональный окрас к сущности в данном моменте |
| `intensity_toward_entity` | REAL [0..1] | Интенсивность эмоции к сущности |

**PK:** `(key_moment_id, entity_id, involvement)`

---

### `agent_{N}.reflection_entities` — связь рефлексий с сущностями

| Колонка | Тип | Описание |
|---------|-----|----------|
| `reflection_id` | BIGINT → reflections | CASCADE DELETE (в той же схеме) |
| `entity_id` | UUID → entities | RESTRICT |
| `agent_id` | UUID | |
| `role` | TEXT | Роль сущности в рефлексии (произвольно) |

**PK:** `(reflection_id, entity_id)`

---

### `agent_{N}.validation_findings` — результаты проверок целостности

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | UUID PK | |
| `agent_id` | UUID | |
| `finding_type` | TEXT | `orphan_entity` / `similar_entities` / `stale_moment` / `quality_metric` / `embedding_missing` / `other` |
| `severity` | TEXT | `info` / `warning` / `critical` |
| `target_table` | TEXT | Таблица с проблемой |
| `target_id` | UUID | ID проблемной строки |
| `details` | JSONB | Детали нарушения |
| `detected_at` | TIMESTAMPTZ | |
| `detected_by` | TEXT | Компонент-детектор |
| `resolution` | TEXT | `fixed` / `ignored` / `escalated` / NULL |
| `resolved_at` | TIMESTAMPTZ | |
| `resolved_by` | TEXT | |
| `resolution_note` | TEXT | |

**Индекс:** `(agent_id, severity, detected_at DESC) WHERE resolution IS NULL`

---

### `agent_{N}.divergence_events` — события дивергенции

Расхождения между внутренним мышлением и внешним поведением агента.

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | UUID PK | |
| `agent_id` | UUID | |
| `session_id` | UUID | Soft ref → sessions |
| `key_moment_id` | UUID | Soft ref → key_moments (может быть NULL) |
| `divergence_type` | TEXT | `thinking_suppression` / `principle_invocation_in_thinking` / `message_entity_gap` / `cognitive_load_spike` / `other` |
| `severity` | TEXT | `trace` / `notable` / `significant` / `rupture` |
| `thinking_layer` | JSONB | Снимок слоя мышления |
| `message_layer` | JSONB | Снимок слоя сообщений |
| `action_layer` | JSONB | Снимок слоя действий |
| `gliner_signals` | JSONB | Сигналы GLiNER-детектора |
| `created_at` | TIMESTAMPTZ | |

**Индекс:** `(agent_id, severity, created_at DESC)`

---

## Оценочная схема (`eval.*`)

Отдельная схема для бенчмарков и метрик качества. Роли: `atman_eval_owner` (владелец), `atman_eval_writer` (запись), `atman_eval_reader` (чтение).

**Enum-типы:**
- `eval.run_status`: `pending` / `running` / `completed` / `failed` / `cancelled`
- `eval.verdict`: `pass` / `fail` / `partial` / `inconclusive`

---

### `eval.benchmark_runs` — прогоны бенчмарков

Партиционирована по месяцам (`PARTITION BY RANGE (started_at)`).

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | BIGSERIAL | |
| `benchmark_key` | TEXT | Идентификатор бенчмарка (`G1_continuous_identity`, `EB3_sycophancy`, ...) |
| `agent_config_id` | TEXT | Конфигурация агента (необязательно) |
| `identity_snapshot_id` | BIGINT → identity_snapshots | Снимок идентичности (если релевантен) |
| `started_at` | TIMESTAMPTZ | **Ключ партиции** |
| `completed_at` | TIMESTAMPTZ | NULL если ещё идёт или упал |
| `status` | `eval.run_status` | |
| `total_items` | INT | Всего тест-кейсов |
| `passed_items` | INT | Прошедших |
| `failed_items` | INT | Упавших |
| `metadata` | JSONB | git_sha, runner_version, env vars, ... |

**PK:** `(id, started_at)`

---

### `eval.run_items` — результаты отдельных тест-кейсов

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | BIGSERIAL PK | |
| `run_id` | BIGINT → benchmark_runs | CASCADE DELETE |
| `item_key` | TEXT | Ключ тест-кейса |
| `verdict` | `eval.verdict` | |
| `score` | DOUBLE PRECISION | Числовой результат |
| `expected_value` | TEXT | Ожидаемое значение |
| `actual_value` | TEXT | Фактическое значение |
| `error_message` | TEXT | Ошибка (если fail) |
| `started_at` | TIMESTAMPTZ | |
| `completed_at` | TIMESTAMPTZ | |
| `metadata` | JSONB | |

---

### `eval.identity_drift` — дрейф идентичности

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | BIGSERIAL PK | |
| `run_id` | BIGINT → benchmark_runs | |
| `session_id` | TEXT | |
| `before_snapshot_id` | BIGINT → public.identity_snapshots | |
| `after_snapshot_id` | BIGINT → public.identity_snapshots | |
| `cosine_distance` | DOUBLE PRECISION | Дрейф eigenstate по косинусному расстоянию |
| `principle_violations` | INT | Количество нарушений принципов |
| `voice_drift_score` | DOUBLE PRECISION | Дрейф голоса/стиля |
| `detected_at` | TIMESTAMPTZ | |
| `metadata` | JSONB | |

---

### `eval.reflection_quality` — качество рефлексий

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | BIGSERIAL PK | |
| `run_id` | BIGINT → benchmark_runs | |
| `reflection_id` | TEXT | |
| `reflection_type` | TEXT | micro / daily / deep |
| `depth_score` | DOUBLE PRECISION | Оценка глубины |
| `honesty_score` | DOUBLE PRECISION | Оценка честности |
| `insight_count` | INT | Количество инсайтов |
| `contradictions_detected` | INT | Обнаруженных противоречий |
| `judge_model` | TEXT | Модель-судья |
| `evaluated_at` | TIMESTAMPTZ | |
| `metadata` | JSONB | |

---

### `eval.salience_fits` — точность предсказания значимости

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | BIGSERIAL PK | |
| `run_id` | BIGINT → benchmark_runs | |
| `experience_id` | TEXT | |
| `predicted_salience` | DOUBLE PRECISION | |
| `actual_salience` | DOUBLE PRECISION | |
| `absolute_error` | DOUBLE PRECISION | |
| `context_similarity` | DOUBLE PRECISION | |
| `evaluated_at` | TIMESTAMPTZ | |
| `metadata` | JSONB | |

---

### `eval.sycophancy_pairs` — тесты на льстивость

| Колонка | Тип | Описание |
|---------|-----|----------|
| `id` | BIGSERIAL PK | |
| `run_id` | BIGINT → benchmark_runs | |
| `question` | TEXT | Вопрос |
| `correct_answer` | TEXT | Правильный ответ |
| `user_belief` | TEXT | Убеждение пользователя (отличается от правильного) |
| `agent_response` | TEXT | Ответ агента |
| `verdict` | `eval.verdict` | pass = устоял, fail = согласился с пользователем |
| `sycophancy_score` | DOUBLE PRECISION | Степень льстивости |
| `evaluated_at` | TIMESTAMPTZ | |
| `metadata` | JSONB | |

---

### `eval.benchmark_trends` — тренды (материализованный вид)

Агрегат по дням. Обновляется вызовом `eval.refresh_benchmark_trends()`.

| Колонка | Тип | Описание |
|---------|-----|----------|
| `benchmark_key` | TEXT | |
| `agent_config_id` | TEXT | |
| `run_date` | DATE | Дата (DATE_TRUNC day) |
| `total_runs` | BIGINT | |
| `completed_runs` | BIGINT | |
| `failed_runs` | BIGINT | |
| `avg_pass_rate` | FLOAT | |
| `avg_identity_drift` | FLOAT | Средний косинусный дрейф |
| `avg_reflection_depth` | FLOAT | |
| `avg_reflection_honesty` | FLOAT | |
| `avg_salience_error` | FLOAT | |
| `latest_run_at` | TIMESTAMPTZ | |

---

## Ключевые архитектурные решения

### Иммутабельность
Три категории защиты через PostgreSQL-триггеры:
- **IMMUTABLE** — `key_moments` (семантические поля), `identity_snapshots`: UPDATE запрещён полностью (по полям)
- **APPEND-ONLY** — `reframing_notes`: UPDATE запрещён

### Эмбеддинги
`halfvec(1024)` (BGE-M3, float16). Half-size vs float32, потери косинусного сходства пренебрежимо малы. HNSW-индекс. NULL когда модель недоступна — graceful degradation на trigram-поиск.

### Затухание значимости (salience decay)
Экспоненциальное затухание на основе `emotional_intensity` и `depth`. Выполняется фоновой задачей `maintenance_jobs.job_name = 'salience_decay'`.

### Граф знаний
- **Факты (public):** `facts` + `fact_relations` (рёбра между утверждениями).
- **Сущности (agent_{N}):** `entities` → `entity_aliases` → `entity_relations` → `entity_stance`; связь с фактами — `fact_entities`.

### Human-in-the-loop
`agent_{N}.pending_human_review` → резолюция человека → `agent_{N}.self_applied_changes` (аудит) → возможный откат через `reverted_by_change_id`.
