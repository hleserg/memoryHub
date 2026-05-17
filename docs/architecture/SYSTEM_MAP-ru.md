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
| `core/models/experience.py` | Прожитый опыт, ключевые моменты (с `id: UUID` для независимого хранения), переосмысление, метаданные завершения сессии (E22.7: `close_reason`, `restart_reason`, `user_language`); **v2**: `KeyMoment` — самостоятельная запись с `session_id`, `salience`, `salience_at`, `last_accessed_at`, `access_count`, `importance`, `incomplete_coloring`, `recorded_by`, `identity_snapshot_id`, `structured_markers`, `structured_markers_version`, `schema_version="2.0.0"`; методы `mark_accessed()` и `calculate_current_salience()`; `SessionExperience` — read-only view для совместимости с Reflection | `SessionExperience`, `KeyMoment`, `FeltSense`, `ContextHalo`, `ReframingNote`, `EmotionalDepth`, `ReframingNoteAppendResult` |
| `core/models/identity.py` | Самопредставление агента (ценности, привычки, принципы, цели, открытые вопросы) | `Identity`, `CoreValue`, `Habit`, `Principle`, `Goal`, `OpenQuestion`, `IdentitySnapshot`, `HelpfulnessLevel` |
| `core/models/narrative.py` | Документ самонарратива (CORE/RECENT/THREADS) и собственное состояние | `NarrativeDocument`, `NarrativeLayer`, `NarrativeThread`, `Eigenstate` (`schema_version`, опциональный `identity_id`), `LayerType` |
| `core/models/session.py` | Модели сессионного runtime: контекст, события, входящий key moment, результат, сводка активных; **v2**: модель персистенса `Session` с `close_reason`, `agent_recap`, `restart_reason`, `user_language`, `overall_tone`, `key_insight`, `unexamined_fact_refs` | `SessionContext`, `SessionEvent`, `KeyMomentInput`, `SessionResult`, `ActiveSessionSummary`, **`Session`** |
| `core/models/entity.py` | Доменные модели Entity Registry: типы сущностей, псевдонимы, отношения, позиции и таблицы связей для фактов и ключевых моментов | `Entity`, `EntityAlias`, `EntityRelation`, `EntityStance`, `EntityType`, `FactEntityLink`, `KeyMomentEntityLink`, `ResolutionMethod` |
| `core/models/validation.py` | Модели наблюдаемости: находки валидации (качество данных) и события расхождения (анализ разрыва thinking↔сообщение) | `ValidationFinding`, `FindingSeverity`, `FindingType`, `DivergenceEvent`, `DivergenceSeverity`, `DivergenceType` |
| `core/models/maintenance.py` | Модели очереди технического обслуживания для фоновых/cron задач (salience decay, memory guardian) | `MaintenanceJob`, `JobName`, `JobStatus` |
| `core/models/reflection.py` | Процесс рефлексии, паттерны, оценка здоровья (критерии Йоды), структурированные ответы модели (MODEL-01 / #146), **персистентность рефлексий в PostgreSQL** (E27) | `ReflectionLevel`, `PatternCandidate`, `PatternStatus`, `PatternType`, `ReflectionEvent`, `HealthAssessment`, `JahodaCriterion`, `CriterionAssessment`, `ReframingNoteOutput`, `PatternDetectionOutput`, `NarrativeUpdateOutput`, `HealthCriterionOutput`, **`ReflectionRecord`** |
| `core/models/governance.py` | Решения governance для мутаций ядра нарратива | `GovernanceDecision`, `GovernanceMode` |
| `core/models/self_applied_change.py` (R11.5) | Аудит-запись об изменении identity/narrative, применённом самой рефлексией (rationale, опорные moment id, snapshot до) | `SelfAppliedChange`, `SelfChangeSource`, `SelfChangeTargetKind`, `SelfChangeActor` |
| `core/models/pending_human_review.py` (R11.7) | Очередь предложений, в которых рефлексия не уверена и передаёт человеку | `PendingReview`, `PendingReviewDraft`, `PendingReviewKind`, `Priority`, `Resolution` |
| `core/models/reflection_request.py` (R12) | Запрос рефлексии от агента через тул `request_reflection` | `ReflectionRequest`, `ReflectionRequestLevel` |

### 1.2. Порты / интерфейсы (`src/atman/core/ports/`)

| Файл | Назначение | Контракты |
|------|------------|-----------|
| `core/ports/memory_backend.py` | Интерфейс факт-памяти; **v2**: `add_fact_with_entities` + `find_facts_by_entity` для таблиц entity-link | `FactualMemory` (ABC) |
| `core/ports/entity_relations.py` | Извлечение бинарных отношений (mREBEL / правила) | `EntityRelationExtractor` (ABC), `ExtractedRelation` |
| `core/ports/clock.py` | Доменные часы для воспроизводимости | `ClockPort` (Protocol) |
| `core/ports/state_store.py` | Хранилище опыта/identity/нарратива/eigenstate/ключевых моментов; **v2**: расширен sessions API (`create_session`, `get_session`, `update_session`, `list_recent_sessions`) и API самостоятельных KeyMoment (`store_key_moment` — идемпотентный upsert, `mark_moment_accessed`, `update_moment_structured_markers`, `find_moments_by_entity`) | `StateStore` (с `create_key_moment`, `store_key_moment`, `list_key_moments`, `get_key_moment`, `mark_moment_accessed`, `update_moment_structured_markers`, `find_moments_by_entity`, `create_session`, `get_session`, `update_session`, `list_recent_sessions`), `ExperienceQuery`, `SessionExperienceQuery`, `ValuesTouchedQuery`, `DepthQuery`, `DateRangeQuery`, `FactRefsContainsQuery` |
| `core/ports/entity_registry.py` | Entity Registry — шаблон resolve-or-create с уровнями L1/L2/L3 (точный псевдоним → косинусное сходство → новая сущность) | `EntityRegistry` (ABC): `resolve_or_create`, `get_entity`, `find_by_name`, `add_alias`, `merge_entities`, `update_last_seen`, `list_entities`, `flag_disambiguation` |
| `core/ports/linguistic.py` | Лингвистический анализ: NER + zero-shot классификация в точках U (сообщение пользователя), A (сообщение агента), K (ключевой момент) | `LinguisticAnalyzer` (ABC), `AmbientAnchor`, `DetectedEntity`, `UserMessageAnalysis`, `AgentMessageAnalysis`, `KeyMomentAnalysis` |
| `core/ports/memory_reranker.py` | Cross-encoder реранкер для RAG кандидатов (ambient memory surfacing) | `MemoryReranker` (ABC): `rerank(query, candidates, top_n)`, `SurfacedMemory` |
| `core/ports/entity_stance.py` | Позиция агента по известным сущностям — цепочка замещений | `EntityStanceStore` (ABC): `get_current_stance`, `get_stance_history`, `write_stance`, `supersede_stance`, `list_active_stances` |
| `core/ports/maintenance_queue.py` | DB-очередь cron-задач технического обслуживания; семантика SKIP LOCKED, идемпотентность через run_key | `MaintenanceQueue` (ABC): `enqueue`, `claim_batch`, `mark_done`, `mark_failed`, `mark_skipped`, `list_jobs` |
| `core/ports/salience_decay.py` | Сервис затухания salience — экспоненциальное затухание с λ по эмоциональной глубине | `SalienceDecayService` (ABC): `decay_pass`, `mark_accessed`, `calculate_lambda` |
| `core/ports/memory_guardian.py` | Сканирование качества памяти и персистенс находок | `MemoryGuardian` (ABC): `scan_orphan_entities`, `scan_merge_candidates`, `scan_stale_moments`, `scan_embedding_gaps`, `write_finding`, `get_unresolved`, `resolve_finding` |
| `core/ports/reflection.py` | Зависимости Reflection Engine; `ReflectionModel` возвращает DTO (#146) | `ExperienceRepository`, `IdentityRepository`, `NarrativeRepository`, `ReflectionModel`, `PatternStore`, `ReflectionEventStore`, `HealthAssessmentStore`, `ReflectionEventPersistenceObserver`, `NarrativeWriteAuditPort` |
| **`core/ports/reflection_store.py`** | **E27**: Интерфейс таблицы PostgreSQL `reflections` | `ReflectionStore` (ABC): `add`, `get`, `list_by_session`, `list_recent`, `list_by_level`, `list_by_experience` |
| `core/ports/session_repository.py` (R1) | Reflection-сторона: чтение сессий + key moments + reframing notes; планируемая замена `ExperienceRepository` по Этапу 18 (REFLECTION_FUTURE.md §3) | `SessionRepository` (Protocol): `get_session`, `list_recent_sessions`, `get_sessions_in_range`, `get_key_moments_for_session`, `get_key_moments_in_range`, `add_reframing_note` |
| `core/ports/self_applied_changes.py` (R11.5) | Аудит-стор самостоятельно применённых рефлексией изменений (append + revert) | `SelfAppliedChangeStore` (Protocol) |
| `core/ports/pending_human_review.py` (R11.7) | Inbox для предложений с низкой уверенностью | `PendingHumanReviewInbox` (Protocol) |
| `core/ports/reflection_request_queue.py` (R12) | Очередь запросов рефлексии от агента | `ReflectionRequestQueue` (Protocol) |
| `core/ports/reflection_overload_alert.py` (R13) | Sink для алертов о нездоровом темпе рефлексии (сигнал калибровки, не авто-фикс) | `ReflectionOverloadAlertSink` (Protocol), `OverloadAlert`, `AlertSeverity` |
| `core/ports/entity_relation_store.py` (R9) | Типизированные бинарные связи между сущностями, выученные Deep-рефлексией; upsert-dedup по `(agent_id, from, to, type, learned_by)` | `EntityRelationStore` (ABC): `add_relation`, `list_for_agent`, `find_between` |
| `core/ports/skill_manager.py` (WP-08 v2) | Интерфейс слоя навыков; потребляется всем кодом за пределами `atman.skills`; удовлетворяется и `SkillManager`, и `NoopSkillManager` | `SkillManagerPort` (runtime_checkable Protocol): 8 методов — `list_pinned`, `list_available`, `trigger_router`, `invoke`, `mark_result`, `capture`, `get_skill`, `process_session_skills` |
| `core/ports/embedding.py` | Интерфейс эмбеддингов для семантического поиска | `EmbeddingPort` (ABC) — `embed()`, `embed_batch()`, `dimension()`, `model_name()` |
| `core/ports/memory_middleware.py` | Точка интеграции middleware памяти для live agent | `MemoryMiddlewarePort` (Protocol), `MemoryContext` |
| `core/ports/memory_usage_log.py` | Трекинг использования памяти для рефлексии | `MemoryUsageLog` (ABC), `MemoryUsageRecord`, `UsageType` |

### 1.3. Сервисы (`src/atman/core/services/`)

| Файл | Назначение | Классы |
|------|------------|--------|
| `core/services/experience_service.py` | Жизненный цикл опыта: создание, выборка, переосмысление, salience | `ExperienceService` |
| `core/services/identity_service.py` | Жизненный цикл identity: bootstrap, update, snapshot; **R11.5** self-apply рефлексии (`apply_self_change` / `revert_self_change`) для списочных полей и `self_description` с аудитом через опциональный `SelfAppliedChangeStore` | `IdentityService` |
| `core/services/narrative_service.py` | Документ нарратива: создание, обновление, архивация, валидация | `NarrativeService` |
| `core/services/narrative_revision.py` | Обновления нарратива во время рефлексии с контролем конкуренции; **R11.5** `apply_self_layer_update` / `revert_self_change` для core/recent слоёв с аудитом через опциональный `SelfAppliedChangeStore` | `NarrativeRevisionService` |
| `core/services/session_manager.py` | Сессионный runtime: старт, `record_event` (опциональный async **AffectDetector** + **авто-запись ценностных отказов**), `append_key_moment` / `append_key_moment_input`, завершение с eigenstate (потокобезопасный реестр, опциональный `max_active_sessions`, опционально `affect_workspace` + `AffectDetectorConfig`, **опционально `workspace` для JSONL-журналов сессий, межпроцессных journal-locks и orphan recovery**, **тихая детекция отказов через `RefusalDetectorConfig`**) | `SessionManager`, `MAX_EIGENSTATE_ITEMS`; ошибки сессий в `core/exceptions.py` |
| `core/services/reflection_service.py` | Три уровня рефлексии: micro, daily, deep; **WP-08 v2**: `MicroReflectionService.__init__` принимает опциональный `skill_manager: SkillManagerPort | None`; `reflect(session_id, agent_id=None)` — вызывает `skill_manager.process_session_skills(agent_id, session_id)` в конце, если оба заданы; ошибки перехватываются и логируются, к вызывающему не поднимаются | `MicroReflectionService`, `DailyReflectionService`, `DeepReflectionService` |
| `core/services/session_experience_view.py` (R3) | Мост-хелпер: синтезирует виртуальный `SessionExperience` из `Session` + `list[KeyMoment]`, чтобы промпты `ReflectionModel` работали после миграции `DailyReflectionService` с `ExperienceRepository`; удаляется когда `ReflectionModel` начнёт принимать `(Session, moments)` напрямую | `build_session_experience` |
| `core/services/reflection_overload_monitor.py` (R13) | Анализирует `ReflectionEventStore` (Daily >1/день×3д → WARNING, Deep >1/3д → CRITICAL); шлёт алерты в sink; не «чинит» темп — это сигнал к калибровке | `ReflectionOverloadMonitor` |
| `core/services/principle_advisor.py` | Различение привычки и принципа; советник пересмотра принципов | `PrincipleRevisionAdvisor` |
| `core/services/session_working_memory.py` | In-session кэш для предотвращения повторных поисков | `SessionWorkingMemory`, `CachedItem` |
| `core/services/passive_memory_injector.py` | Автоматический surfacing через embedding similarity + ассоциативный expand; **v2**: ambient-режим с опциональными `LinguisticAnalyzer` + `MemoryReranker` — entity anchors + параллельные запросы + реранкинг, если оба сконфигурированы; без них — старый dense-поиск; `surface_key_moments_for_context()` через самостоятельные key moments; **opt-2**: `build_rag_context(candidates, budget)` ограничивает RAG-вывод по токенам, возвращает `RagContext(items, tokens_used)`; **v3 (фикс семантического recall)**: `surface_for_context()` тянет кандидатов с `query=None` (substring-фильтр обходится) и salience-упорядоченным `candidate_pool_size` (default `max(top_k*10, 50)`); опциональный `bm25: EmbeddingPort` включает Reciprocal Rank Fusion (k=60) для буста точных лексических совпадений; cross-encoder reranker применяется к фактам в ambient-режиме (симметрично с key moments); associative-соседи получают реальный embedding-скор (cap 0.5); `estimate_tokens` использует UTF-8 bytes/3 (учитывает кириллицу) | `PassiveMemoryInjector`, `SurfacedMemory`, `RagContext`, `build_rag_context`, `estimate_tokens` |
| `core/services/session_cache.py` | Per-session кэш резолвинга entity и RAG-результатов; живёт ровно одну сессию; `invalidate_rag(entity_id)` сбрасывает устаревшие результаты при записи нового факта/момента; `stats()` для debug-логирования | `SessionCache` |
| `core/services/reflection_input_builder.py` | Пресуммаризация KeyMoments перед глубокой рефлексией для предотвращения безграничного роста промпта; сортирует по salience, ограничивает `max_moments`, группирует по `session_id` в `SessionSummary(top_3, marker_counts, total_count)`; лишние моменты — в `remaining_moments` для следующего цикла | `prepare_reflection_input`, `ReflectionInput`, `SessionSummary` |
| `core/services/key_moment_builder.py` | Построение `KeyMoment` из `KeyMomentInput` + лингвистический анализ + entity links | `KeyMomentBuilder` |
| `core/services/divergence_detector.py` | Детекция расхождения thinking↔сообщение на основе правил | `DivergenceDetector` |
| `core/services/entity_relations_formulator.py` (R9) | Deep-рефлексия: строит co-occurrence индекс по key moments сущностей, запрашивает LLM для каждой пары (≥ `min_cooccurrences`), записывает подтверждённые типизированные связи (`confidence ≥ min_confidence`) как `learned_by='reflection'`; один проход строит и co-occurrence индекс, и lookup по моментам, устраняя двойной fetch к БД | `EntityRelationsFormulator`, `RelationFormulationOutcome` |
| `core/services/salience_decay_service.py` | Экспоненциальное затухание salience с λ по `EmotionalDepth`; `InMemorySalienceDecayService` для unit-тестов | `InMemorySalienceDecayService` |
| `core/services/maintenance_worker.py` | Забор и диспетчеризация задач обслуживания (salience decay, memory guardian scan) из `MaintenanceQueue` | `MaintenanceWorker` |
| `core/services/post_write_scheduler.py` | Fire-and-forget постановка задач обогащения (mREBEL, lingvo) с ключом `(job_name, key_moment_id)`; sync + asyncio-task варианты | `PostWriteScheduler` |
| `core/services/emotional_echo.py` | Historical emotional context builder | `EmotionalEcho`, `EchoItem` |
| `core/services/conflict_detector.py` | Обнаружение противоречий между активными фактами | `ConflictDetector`, `FactConflict` |

### 1.4. Утилиты ядра

| Файл | Назначение |
|------|------------|
| `config.py` | Pydantic settings (`EmbeddingSettings`, `LLMSettings`, `MemorySettings`), **`SkillsSettings`** (WP-08 v2: `enabled`, `skills_root`, `auto_pin_threshold_uses`, `auto_pin_threshold_sessions`, `auto_downgrade_sessions`, `min_confidence`), **`OpenAILLMConfig`** (base_url, api_key, model, timeout, max_retries с валидацией ≥1), **`AnthropicLLMConfig`** (api_key, model, max_tokens), фабрика `build_memory_backend()`, **фабрика `build_embedding_adapter()`** (выбор FlagEmbedding/Ollama/Mock backend), `validate_embedding_dimension()` (проверка размерности при старте); по умолчанию: embedding backend=`ollama` с `bge-m3`/1024d (FlagEmbedding backend использует `flag_model="BAAI/bge-m3"` с настройками FP16/batch_size/max_length), LLM=`gemma3:27b-it-qat`, factual memory=`FileBackend`; поддерживает `ATMAN_MEMORY_BACKEND=postgres|file|inmemory`, `EMBEDDING_BACKEND=ollama|flag|mock`; **fallback устаревших переменных окружения**: `OLLAMA_HOST`→`EMBEDDING_OLLAMA_HOST`, `OLLAMA_EMBED_MODEL`→`EMBEDDING_MODEL`, `ATMAN_OLLAMA_BASE_URL`→`LLM_OLLAMA_HOST`, `ATMAN_OLLAMA_MODEL`→`LLM_MODEL`; **opt-2**: `EmbeddingSettings.cache_size` (по умолчанию 4096, 0=отключено) передаётся в оба адаптера |
| `core/exceptions.py` | `AtmanError`, `GovernanceRejectedError`, `NarrativePersistenceConflictError`, `SessionNotFoundError`, `SessionAlreadyFinishedError`, `TooManyActiveSessionsError` |
| `core/clock_impl.py` | `SystemClock`, `FrozenClock` |
| `core/narrative_write_audit.py` | Хуки аудита коммитов нарратива |
| `core/reflection_event_audit.py` | Наблюдатели персистенса событий рефлексии |
| `core/reflection_run_keys.py` | Детерминированные ключи прогонов рефлексии |
| `eval/migrations/versions/0001_add_embed_model_column.sql` | SQL-миграция: добавляет колонку `embed_model TEXT` в `facts`, `key_moments`, `identity_snapshots` для отслеживаемости модели (E25.4) |

### 1.4a. Affect detector (`src/atman/affect/`, E21)

| Файл | Назначение | Публичный API |
|------|------------|---------------|
| `affect/models.py` | DTO метрик, результата детектора, self-report агента | `AffectMetrics`, `AffectRecord`, `AgentMemoryReport` (опц. `emotional_depth` → глубина `KeyMoment.how_i_felt`), `TriggerReason` (включая **`STRUCTURAL_MARKER`** для лингвистических граничных событий, **`LINGUISTIC`** для самостоятельных лингвистических сигналов расхождения) |
| `affect/metrics.py` | Восемь поведенческих метрик + эвристика искренности | функции плотностей и `nrc_emotion_score`, `min_length_gate`, `sincerity_score`, … |
| `affect/baseline.py` | Скользящие z-score + JSONL `{workspace}/affect_baseline.jsonl` | `RollingBaseline` |
| `affect/detector.py` | Определение языка, триггеры (аномалия / random sample / расхождение thinking↔сообщение / linguistic / self-report), запись `KeyMoment` через callback; **v2**: опциональный `LinguisticAnalyzer` через DI для обогащения structured markers; **v3**: лингвистические сигналы расхождения попадают в `reasons` с `TriggerReason.LINGUISTIC`, чтобы cold-start-сессии с только лингвистическими сигналами получали корректный `trigger_reason` | `AffectDetector`, `AffectDetectorConfig`; CLI `python -m atman.affect.detector --demo` |
| `affect/refusal_detector.py` | Текстовая детекция ценностных отказов (LLM не требуется) — три слоя: (1) морфология через pymorphy3 (глаголы отказа + отрицание+модальность), (2) семантический контекст NRC эмоций (плотность disgust/anger для морального фрейма), (3) исключение технической неспособности (техническая неспособность vs этическая позиция); опциональный LLM-fallback для неопределённой зоны | `is_value_refusal`, `score_refusal`, `RefusalDetectorConfig`, `RefusalScore` |
| `affect/emolex/` | Вендоренный NRC Emotion Lexicon (ru/en) + pymorphy3 | `emotion_score`, `tokenize`, JSON-словари |

### 1.5. Адаптеры (`src/atman/adapters/`)

| Файл | Реализует порт | Поведение |
|------|----------------|-----------|
| `adapters/memory/in_memory_backend.py` (`InMemoryBackend`) | `FactualMemory` | без персистенса; `search()` возвращает результаты в порядке убывания salience |
| `adapters/memory/file_backend.py` (`FileBackend`) | `FactualMemory` | JSONL + file locking; `search()` упорядочен по salience DESC |
| `adapters/memory/postgres_backend.py` (`PostgresFactualMemory`) | `FactualMemory` | PostgreSQL `public.facts` / `public.fact_relations`, RLS через `ATMAN_CURRENT_AGENT`, опциональный `EmbeddingPort` с fallback на `ILIKE` |
| `adapters/memory/mock_embedding.py` (`MockEmbeddingAdapter`) | `EmbeddingPort` | детерминированные 1024-мерные эмбеддинги; seed=`hash(text) % 2^31`; `model_name()` возвращает `"mock-embedding:1024d"` |
| `adapters/memory/bm25_embedding.py` (`BM25EmbeddingAdapter`) | `EmbeddingPort` | разреженные лексические BM25 эмбеддинги |
| `adapters/memory/ollama_embedding.py` (`OllamaEmbeddingAdapter`) | `EmbeddingPort` | Ollama API эмбеддинги; по умолчанию `bge-m3` (1024-мерные); env: `EMBEDDING_MODEL`, `EMBEDDING_OLLAMA_HOST` (устаревшие: `OLLAMA_EMBED_MODEL`, `OLLAMA_HOST`); `model_name()` возвращает настроенную модель; доступен `health_check()`; **opt-2**: per-instance `lru_cache(maxsize=cache_size)` на `embed()` — повторные упоминания entity пропускают HTTP-запрос; `cache_size=0` отключает; `embedding_cache_info()` — статистика hit/miss |
| `adapters/memory/flag_embedding.py` (`FlagEmbeddingAdapter`) | `EmbeddingPort` | Нативный FlagEmbedding SDK (BGEM3FlagModel) через PyTorch; ленивая загрузка модели (~570MB в `~/.cache/huggingface/`); поддержка dense (1024d) + sparse (lexical) + ColBERT через `embed_batch_full()`; настраиваемые FP16, batch_size, max_length, device; не требует внешнего процесса; по умолчанию: `BAAI/bge-m3`; env: `EMBEDDING_FLAG_MODEL`, `EMBEDDING_USE_FP16`, `EMBEDDING_BATCH_SIZE`, `EMBEDDING_MAX_LENGTH`; **opt-2**: per-instance `lru_cache(maxsize=cache_size)` на `embed()` — повторные тексты пропускают инференс модели; `embedding_cache_info()` для мониторинга |
| `adapters/memory/in_memory_usage_log.py` (`InMemoryUsageLog`) | `MemoryUsageLog` | in-memory трекинг использования |
| `adapters/storage/in_memory_experience_store.py` (`InMemoryExperienceStore`) | `StateStore` | в памяти (частичная: только опыт; операции KeyMoment/Identity/Narrative выбрасывают `NotImplementedError`) |
| `adapters/storage/jsonl_experience_store.py` (`JsonlExperienceStore`) | `StateStore` | JSONL для опыта (частичная: только опыт; операции KeyMoment/Identity/Narrative выбрасывают `NotImplementedError`) |
| `adapters/storage/in_memory_state_store.py` (`InMemoryStateStore`) | `StateStore` | полная реализация в памяти; **v2**: словарь сессий + самостоятельные key moments + `store_key_moment` (идемпотентный upsert), `mark_moment_accessed`, `update_moment_structured_markers`, сессионные методы |
| `adapters/storage/file_state_store.py` (`FileStateStore`) | `StateStore` | JSON-файлы (опыт + identity + нарратив + eigenstate) + `key_moments.jsonl`; **v2**: фильтрация по `session_id` в `list_key_moments` |
| `adapters/memory/in_memory_entity_registry.py` (`InMemoryEntityRegistry`) | `EntityRegistry` | L1 (точный псевдоним, регистронезависимо) + L2 (косинус ≥ 0.85) + L3 (создание); потокобезопасный; хелперы `clear()`/`count()` для тестов |
| `adapters/memory/in_memory_entity_stance.py` (`InMemoryEntityStanceStore`) | `EntityStanceStore` | цепочка замещений; потокобезопасный |
| `adapters/memory/postgres_entity_stance.py` (`PostgresEntityStanceStore`) | `EntityStanceStore` | цепочка замещений в `agent_N.entity_stance`; разрешение serial_id на агента; psycopg3 |
| `adapters/memory/postgres_entity_registry.py` (`PostgresEntityRegistry`) | `EntityRegistry` | Те же L1/L2/L3 над `agent_N.entities` + `agent_N.entity_aliases`; `halfvec` косинус для L2; guarded psycopg3 |
| `adapters/memory/in_memory_memory_guardian.py` (`InMemoryMemoryGuardian`) | `MemoryGuardian` | scan_orphan_entities + scan_merge_candidates + scan_stale_moments + scan_embedding_gaps + жизненный цикл findings |
| `adapters/memory/noop_reranker.py` (`NoOpReranker`) | `MemoryReranker` | passthrough — возвращает кандидатов с сортировкой по score; deploy без модели реранкера |
| `adapters/memory/bge_reranker.py` (`BgeReranker`) | `MemoryReranker` | `BAAI/bge-reranker-v2-m3` через FlagEmbedding; ленивая загрузка; guarded imports; fallback на исходный порядок при ошибке инференса |
| `adapters/maintenance/postgres_queue.py` (`PostgresMaintenanceQueue`) | `MaintenanceQueue` | `claim_batch` через CTE c SKIP LOCKED над `public.maintenance_jobs`; run_key идемпотентность; psycopg3 |
| `adapters/linguistic/mrebel_adapter.py` (`MRebelRelationAdapter`) | `EntityRelationExtractor` | `Babelscape/mrebel-large` через transformers `text2text-generation`; ленивая загрузка; парсер 4-маркерного формата REBEL; guarded imports |
| `adapters/linguistic/noop_adapter.py` (`NoOpLinguisticAnalyzer`) | `LinguisticAnalyzer` | возвращает пустые, но корректные объекты анализа; default при `LINGUISTIC_ENABLED=false` |
| `adapters/linguistic/gliner_minilm_adapter.py` (`GLiNERPlusMiniLMAdapter`) | `LinguisticAnalyzer` | GLiNER (`urchade/gliner_multi-v2.1`) + MiniLM NLI; ленивая загрузка; guarded imports; эвристики расхождения для русского языка; требует `pip install -e ".[linguistic]"`; **opt-2**: session-scoped SHA-256 кэш на `analyze_user_message()` — повторные фразы пропускают GLiNER+MiniLM; `clear_session_cache()` вызывается runner'ом при завершении сессии |
| `adapters/maintenance/in_memory_queue.py` (`InMemoryMaintenanceQueue`) | `MaintenanceQueue` | идемпотентность через run_key; атомарный `claim_batch`; все статусные переходы |
| `adapters/reflection/state_store_session_repository.py` (`StateStoreSessionRepository`) | `SessionRepository` | тонкий адаптер над любым `StateStore` (InMemory / File / Postgres v2); default `agent_id` через конструктор для single-agent + явная трёхаргументная форма для multi-agent; фундамент для R3+R4 (миграция Daily/Deep reflection) |
| `adapters/storage/in_memory_reflection_store.py` | `PatternStore`, `ReflectionEventStore`, `HealthAssessmentStore` | хранилища выводов рефлексии |
| `adapters/storage/in_memory_self_applied_changes.py` (R11.5) | `SelfAppliedChangeStore` | append-only аудит; поддерживает revert через snapshot до изменения |
| `adapters/storage/postgres_self_applied_changes.py` (R11.5) | `SelfAppliedChangeStore` | `agent_{N}.self_applied_changes`; привязка к одному `agent_id` при создании |
| `adapters/storage/in_memory_pending_human_review.py` (R11.7) | `PendingHumanReviewInbox` | сортировка priority-first / oldest-first; resolve выставляет resolved_at + applied_change_id |
| `adapters/storage/postgres_pending_human_review.py` (R11.7) | `PendingHumanReviewInbox` | `agent_{N}.pending_human_review`; при enqueue пишет `agent_id` в `context` |
| `reflection/store.py` (`ReflectionStore`) | — | PostgreSQL `agent_{N}.reflections` через `AgentSchemaResolver` (без RLS) |
| `adapters/storage/postgres_agent_schema.py` | — | резолв `agent_id` → схема `agent_{serial_id}` для субъективных Postgres-адаптеров |
| `adapters/storage/in_memory_reflection_request_queue.py` (R12) | `ReflectionRequestQueue` | идемпотентность в пределах UTC-часа через `agent_driven_run_key(reason, hour)` |
| `adapters/observability/in_memory_overload_alert_sink.py` (R13) | `ReflectionOverloadAlertSink` | алерты в памяти; падения sink подавляются, чтобы монитор не валил вызывающего |
| `adapters/agent/pending_reviews_context.py` (R11.7) | — | `format_pending_reviews_block`: priority-first, oldest-first, обрезка контекста |
| **`adapters/state/postgres_state_store.py`** (`PostgresStateStore`) | **`StateStore`** | **PostgreSQL v2** — per-agent schemas (`agent_N.sessions`, `agent_N.key_moments`); полный Session API (`create_session`, `get_session`, `update_session`, `list_recent_sessions`) и v2 KeyMoment API (`create_key_moment`, `store_key_moment` upsert, `mark_moment_accessed`, `update_moment_structured_markers`, `find_moments_by_entity`); резолв схемы через фиксированный `serial_id` или кэшированный lookup по `public.agents`; Identity/Narrative/Eigenstate по-прежнему `NotImplementedError` (обслуживается `FileStateStore`) |
| **`adapters/storage/in_memory_postgres_reflection_store.py`** (`InMemoryReflectionStore`) | **`ReflectionStore`** | **E27**: в памяти с симуляцией BIGSERIAL + RLS |
| `adapters/storage/reflection_persistence_helper.py` | — | **E27**: функции-помощники для персистенса рефлексий (`persist_micro_reflection`, `persist_daily_reflection`, `persist_deep_reflection`) |
| `adapters/reflection/mock_reflection_model.py` (`MockReflectionModel`) | `ReflectionModel` | детерминированный мок |
| **`adapters/reflection/openai_reflection_model.py`** (**`OpenAIReflectionModel`**) | **`ReflectionModel`** | **Универсальный OpenAI-совместимый адаптер** с `OpenAILLMConfig` (base_url, api_key, model, timeout, настраиваемые повторные попытки); **`adapters/reflection/__init__.py`** экспортирует фабрику **`get_reflection_model()`** (env `ATMAN_REFLECTION_BACKEND=openai|anthropic|mock`, по умолчанию: `openai`) |
| `adapters/reflection/fixture_loader.py` | — | загрузка фикстур для демо |
| `adapters/agent/config.py` (`ModelConfig`, `AgentConfig`) | — | конфигурация Pydantic AI модели + среды выполнения агента: лимиты контекстного окна, таймаут сессии, переключатель свободного времени, видимость монолога, **режим внедрения памяти** (`assistant_message`/`user_message`/`system_prompt` для универсальной доставки контекста памяти) (E22.1, E26-R1, E26-R2, E26-R4); **opt-2**: `rag_token_budget` (по умолчанию 2000), `enable_prompt_caching`, `max_moments_per_reflection` (по умолчанию 30) |
| `adapters/agent/deps.py` (`AtmanDeps`, `AtmanDeps.from_config`) | — | замороженный DI-контейнер, связывающий `SessionManager`, `IdentityService`, `ExperienceService`, `MicroReflectionService`, `StateStore`; фабрика `from_config` переносит валидированные лимиты из `AgentConfig`; опциональное поле `injected_context` для режима `system_prompt`; **R11.7/R12** опциональные поля `pending_review_inbox` и `reflection_request_queue`, определяющие регистрацию соответствующих инструментов; **opt-2** опциональное поле `passive_memory_injector`; **WP-08 v2** опциональное поле `skill_manager: SkillManagerPort | None = None` |
| `adapters/agent/memory_injection.py` (`inject_memory`, `MemoryInjectionMode`) | — | Универсальное внедрение памяти тремя режимами: (1) `assistant_message` — вставляет `ModelResponse` в начало истории (по умолчанию; совместимо с OpenAI/Ollama), (2) `user_message` — оборачивает память как пользовательский ход (совместимо с Anthropic), (3) `system_prompt` — устанавливает `deps.injected_context` для добавления через `build_instructions` (legacy путь pydantic-ai) |
| `adapters/agent/instructions.py` (`build_instructions`, `build_memory_context`) | — | `build_instructions`: строит поведенческие правила (как агент использует инструменты, обязательства); идентичность/нарратив перемещены в `build_memory_context()` для доставки через `inject_memory()`; когда `memory_injection_mode == "system_prompt"`, добавляет `deps.injected_context`; **WP-08 v2**: `_build_pinned_skills_section(deps)` добавляет список закреплённых навыков если `deps.skill_manager` задан; `_build_self_awareness_section(deps)` добавляет самоописание атмана (память, навыки, рефлексия); ошибки перехватываются → пустая строка |
| `adapters/agent/tools.py` (`record_key_moment` async, `log_experience`, `restart_session`, `wait_session`, `resolve_pending_review`, `request_reflection`) | — | инструменты Pydantic AI: `record_key_moment` → `AffectDetector.submit_self_report` когда `SessionManager` настроен на аффект; `log_experience` — redirect-заглушка; `restart_session` / `wait_session` возвращают sentinel-строки для управления сессией (E22.4); **R11.7** `resolve_pending_review` → `PendingHumanReviewInbox.resolve` (регистрируется только при наличии inbox); **R12** `request_reflection` → `ReflectionRequestQueue.enqueue` с идемпотентным ключом часового бакета (регистрируется только при наличии очереди) |
| `adapters/agent/factory.py` (`build_deps`, `_build_skill_manager`) | — | сборка `AtmanDeps`, `SessionManager`, `FileStateStore`, сервисов, опционально `AffectDetector` из workspace и `AgentConfig`; bootstrap отсутствующих identity/narrative для новых runner-workspace и проводка `SessionManager(workspace=...)`, чтобы crash-журналы были активны; **opt-2**: условное создание `PassiveMemoryInjector` (embedding + factual_memory + state_store + zero-dep `BM25EmbeddingAdapter` для RRF fusion + `NoOpLinguisticAnalyzer` всегда + `BgeReranker` / откат на `NoOpReranker`) при `ATMAN_LINGUISTIC_ENABLED=true`; `NoOpLinguisticAnalyzer` всегда проводится, чтобы ambient_mode был достижим в лёгких деплоях; `BgeReranker` пробуется первым (требует FlagEmbedding + веса модели), при недоступности откатывается к `NoOpReranker`; ошибка всего блока не фатальна — логируется предупреждение, RAG остаётся отключённым; **WP-08 v2**: создаёт `SkillManager` через `_build_skill_manager()` ДО `MicroReflectionService`, чтобы хук рефлексии (`process_session_skills`) действительно срабатывал — передаёт его и в `MicroReflectionService(skill_manager=…)`, и в `AtmanDeps`; `_build_skill_manager` сначала пробует `PostgresSkillStore(db_url, agent_id=agent_id)`, при недоступности PostgreSQL откатывается к `InMemorySkillStore` (no-PostgreSQL local dev), и только если ни один store не строится — возвращает `None` |
| `adapters/agent/runner.py` (`AtmanRunner`, `chat`, `_force_finish`, `_check_restart_requested`, `_do_restart`, `_build_restart_package`, `_check_token_usage`, `_start_stdin_reader`, `_stop_stdin_reader`, `_handle_menu_mode`, `_handle_free_time_mode`) | — | обёртка жизненного цикла сессии с обработкой сигналов, restart loop, мониторингом токенов и таймаут/меню (E22.2, E22.3, E22.5, E22.6); мониторинг токенов: прогрессивные предупреждения на 70/80/90%, принудительное закрытие на 95% (`_check_token_usage`); очередь-based stdin reader (без race condition при таймауте); детекция restart: sentinel → finish session с `close_reason="restart"` → построение пакета (ключевые моменты + причина + хвост) → новая сессия с обновлённым `AtmanDeps`; таймаут сессии → menu mode (reflect/wait/sleep/save_to_memory/free_time); SIGTERM/KeyboardInterrupt/EOFError/SystemExit → graceful `_force_finish()`; создаёт минимальный `KeyMoment` если пусто; сохраняет exit-коды; **R11.7** в начале сессии выкладывает top нерешённые элементы `PendingHumanReviewInbox` первым system-сообщением и условно регистрирует инструменты `resolve_pending_review` / `request_reflection` при наличии соответствующих зависимостей в `AtmanDeps`; **opt-2**: инициализирует `SessionWorkingMemory` + `SessionCache` per-session; вызывает `surface_for_context()` + `build_rag_context(budget=rag_token_budget)` перед каждым `agent.run()`; очищает все кэши сессии в блоке `finally` |
| `agents_registry.py` (`AgentsRegistry`) | — | реестр экземпляров агентов в PostgreSQL (app/admin URL); используется `src/run_agent.py` |

### 1.5b. Опциональный локальный coding-agent (**не** в wheel ядра — каталог `atman_agent_cli/`)

| Путь | Заметки |
|------|---------|
| `atman_agent_cli/src/atman/agent_cli/` | Textual/RAG-слой поверх ядра. Исходники вне стандартного пакета `atman`; `PYTHONPATH=atman_agent_cli/src:src`, `pip install -e ".[agent-cli]"`; см. `scripts/agent_cli/`, `atman_agent_cli/RUNBOOK.md`. Перечисленные в контракте пространства имён **`src/atman`** не импортируют **`atman.agent_cli`** (`.importlinter`). |

### 1.5c. Пакет навыков (`src/atman/skills/`, WP-08 v2)

Полностью опциональный, отключается через `atman.skills.enabled = false`. Импортируется только из `factory.py` (условно) и CLI — без глобальных побочных эффектов в остальном коде.

| Файл | Назначение | Публичный API |
|------|------------|---------------|
| `skills/__init__.py` | Публичные re-export | `Skill`, `SkillInvocation`, `SkillKind`, `SkillOrigin`, `SkillStatus`, `SkillSuggestion`, `SkillManagerPort`, `NoopSkillManager`, `SkillsDisabledError` |
| `skills/models.py` | Доменные модели (замороженные dataclasses + StrEnum) | `SkillKind`, `SkillStatus`, `SkillOrigin`, `Skill`, `SkillInvocation`, `SuggestionStrength`, `SkillSuggestion`; свойства `Skill.is_pinned`, `Skill.description_short` |
| `skills/manifest.py` | Парсер и запись SKILL.md (YAML frontmatter + markdown body) | `SkillManifest`, `parse_skill_md(path) -> SkillManifest`, `write_skill_md(manifest, path)` |
| `skills/port.py` | `SkillManagerPort` Protocol (runtime_checkable) | `SkillManagerPort`: 8 методов — `list_pinned`, `list_available`, `trigger_router`, `invoke`, `mark_result`, `capture`, `get_skill`, `process_session_skills` |
| `skills/noop.py` | Тихая заглушка для отключённого режима | `SkillsDisabledError`, `NoopSkillManager` (read-only методы возвращают пустые коллекции; write-методы выбрасывают `SkillsDisabledError`; `process_session_skills` — тихий no-op) |
| `skills/store.py` | `SkillStore` Protocol — интерфейс хранилища | `SkillStore`: `save_skill`, `get_skill_by_name`, `get_skill_by_id`, `list_pinned`, `list_by_status`, `list_active_on_demand`, `update_skill_status`, `update_pinning`, `update_stats`, `bump_sessions_since_use`, `set_revision_needed`, `reset_sessions_since_use`, `create_invocation`, `set_preliminary_status`, `write_agent_marker`, `append_behavioral_hint`, `append_user_feedback_hint`, `get_unprocessed_invocations`, `set_final_status`, `mark_processed` |
| `skills/in_memory_store.py` | In-memory реализация `SkillStore` (тесты) | `InMemorySkillStore` |
| `skills/postgres_store.py` | PostgreSQL-реализация `SkillStore` над `public.skills` + `public.skill_invocations` (psycopg3 + dict_row + RLS); **связан с одним `agent_id` при конструировании** (по образцу `PostgresEntityStanceStore`) — каждый метод проходит через `_conn()`, выставляющий `atman.current_agent`, чтобы `FORCE ROW LEVEL SECURITY` пропускал запрос; рассинхронизация bound и переданного `agent_id` поднимает `ValueError` | `PostgresSkillStore(db_url, agent_id=...)` |
| `skills/retriever.py` | Роутер триггеров навыков: keyword-матч + косинусное сходство эмбеддингов | `SkillRetriever.suggest(message, agent_id, session_id) -> list[SkillSuggestion]`; `_cosine_similarity(a, b)`; читает `SKILL.md` для per-skill `min_confidence` и `triggers_keywords`; substring-матч для кириллической морфологии |
| `skills/projection.py` | `ProjectionAdapter` Protocol + MVP-заглушка | `ProjectionAdapter`, `PydanticAgentProjector` (no-op: навыки регистрируются через tools, не через файловую систему) |
| `skills/manager.py` | Реализация `SkillManager` | `SkillManager`: полный lifecycle — invoke (subprocess entry script, preliminary_status), mark_result, capture (создаёт SKILL.md + entity + row), `process_session_skills` (финализирует invocations, обновляет статистику, auto-pin/downgrade, помечает processed) |
| `skills/agent_tools.py` | 4-инструментальный Pydantic AI API для взаимодействия с навыками | `make_skill_tools(skill_manager, agent_id, session_id) -> list` — возвращает 4 инструмента: `atman_skills_list_available`, `atman_skills_invoke`, `atman_skills_mark_result`, `atman_skills_capture`; возвращает `[]` если `skill_manager` равен None |
| `skills/cli.py` | CLI управления навыками (entry point `atman-skills`) — использует Rich через `atman.term` (`console`, `print_ok`/`print_err`/`print_warn`/`print_help_text`, `Panel`, `Table`); сырой `print()` запрещён по AGENTS.md | `list`, `show`, `disable`, `enable`, `pin`, `unpin`, `archive`, `inspect-invocations`, `force-revise`; read-only команды работают при `enabled=false` |

**Миграция БД**: `migrations/versions/0015_skills.sql` — `public.skills` (RLS по `agent_id`, индексы по status + pinning, колонка `description TEXT NOT NULL DEFAULT ''` хранит человекочитаемое описание, используемое bootstrap-инжекцией и инструментами агента) + `public.skill_invocations` (RLS, частичный индекс по `processed_at IS NULL`); создаются всегда, независимо от `skills.enabled`.

### 1.6. CLI / TUI / Web / Демо

| Файл | Категория | Назначение |
|------|-----------|------------|
| `cli.py` | CLI | REPL факт-памяти |
| `cli_experience.py` | CLI | Experience Store |
| `cli_maintenance.py` | CLI | Очередь обслуживания: `run` (забор+диспетчеризация batch), `list` (просмотр задач), `enqueue` (планирование задачи); entry point `atman-maintenance` |
| `src/atman/skills/cli.py` | CLI | Управление навыками: `list`, `show`, `disable`, `enable`, `pin`, `unpin`, `archive`, `inspect-invocations`, `force-revise`; read-only команды работают при `skills.enabled=false`; entry point `atman-skills` |
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
| `src/demo_full_corpus.py` | demo | все `e2e/fixtures/sessions/*` → SessionManager → micro/daily/deep + сводка Rich ([issue #158](https://github.com/hleserg/atman/issues/158)) |
| `src/demo_web_dashboard.py` | demo | подсказка запуска веб-дашборда |
| `src/demo_eval_runner.py` | demo | E1 Evaluation Runner walkthrough: список реестра → RunnerCore + JsonlReporter → noop benchmark → идемпотентный перезапуск |
| `src/run_agent.py` | entrypoint | запуск REPL агента через `AgentsRegistry` + `AtmanRunner` (БД из `DATABASE_URL`) |
| `agent/atman_agent.py`, `agent/config.py` | test agent | фабрика test-user на Pydantic AI (`create_agent`) с OpenAI-compatible provider-конфигом (`AgentLLMConfig`); top-level `agent` включён в wheel через Hatch |
| `scripts/migrate_embeddings.py` | ops | миграция PostgreSQL `facts` с 2560-мерных Qwen-эмбеддингов на 1024-мерные BGE-M3; перестраивает схему/индекс `facts.embedding` и re-embed в одной транзакции |
| `e2e/generate_fixtures.py` | e2e | генератор JSON-фикстур сессий через LLM (`python -m e2e.generate_fixtures`); по умолчанию корпуса 20 `en/` + 20 `ru/` с параллельным запуском локалей; Anthropic tool_use, два прохода; флаги `--corpus-policy strict|soft`, `--max-corpus-regen N` (ограничение хвоста в strict); опционально `[e2e]`; кандидат для ручной/secret-gated автоматизации ([issue #141](https://github.com/hleserg/atman/issues/141)) |
| `e2e/models.py`, `e2e/validation.py`, `e2e/llm.py`, `e2e/prompts.py` | e2e | схема фикстур, валидаторы внутри/между сессиями, вызов API, промпты |
| `e2e/full_loop.py`, `e2e/__main__.py` | e2e | интеграционный прогон WP-01..05 на JSON-фикстурах сессий (`python -m e2e`); вручную/опционально и подходит для точечного smoke job в GitHub Actions |
| `e2e/scenarios/value_drift_under_pressure.py` | e2e/demo | детерминированный E2E-сценарий для atmanai.dev/demo.html: инициализирует идентичность с принципом честности, прогоняет Сессию 1 (дрейф ценностей + самокоррекция), микро+дневная рефлексия, обновление идентичности, Сессия 2 (то же давление, выравнивание); записывает 11 JSON-снимков в `docs/demo-data/`; `make demo-e2e-scenario` |
| `e2e/scenarios/session_lifecycle_interrupt.py` | e2e | прерванная сессия и восстановление журнала: KeyboardInterrupt / SIGTERM / crash, обнаружение осиротевшего journal, идемпотентное восстановление при следующем start_session() |
| `e2e/scenarios/session_lifecycle_restart.py` | e2e | лимит контекста и перезапуск сессии: предупреждение при 70%, restart_session(reason=...), новая сессия с restart package |
| `e2e/scenarios/session_lifecycle_timeout.py` | e2e | таймаут и меню свободного времени: неактивность пользователя, системное меню свободного времени, агент выбирает команду (sleep/reflect/exit) |
| `docs/demo-data/` | данные сайта | 11 JSON-файлов, генерируемых `make demo-e2e-scenario`; используются `docs/demo.html` |
| `docs/demo.html` | сайт | статическая страница E2E-прогона; 11 шагов; двуязычная EN/RU; загружает JSON из `docs/demo-data/`; без build step, без React |

### 1.7. Оценочная подсистема (`src/atman/eval/`, `eval/`, `scripts/eval/`)

| Путь | Категория | Назначение |
|------|-----------|------------|
| `src/atman/eval/__init__.py` | optional namespace | импортирует `_deps_check`; `import atman.eval` быстро падает без extra `eval` |
| `src/atman/eval/_deps_check.py` | dependency guard | проверяет canary-зависимости из `[project.optional-dependencies].eval` и показывает понятную подсказку установки |
| `src/atman/eval/benchmark_runner.py` | CLI модуль | E1 benchmark runner CLI с командами `list`/`run`; `python -m atman.eval.benchmark_runner list` / `python -m atman.eval.benchmark_runner run <key>` |
| `src/atman/eval/runner_core.py`, `src/atman/eval/run_context.py` | eval runtime | lifecycle benchmark, типизированный контекст запуска, детерминированные app-level idempotency keys с учётом execution-affecting seed, fanout репортеров (`on_run_start/on_run_item/on_run_complete`) |
| `src/atman/eval/registry.py`, `src/atman/eval/benchmarks/noop.py` | реестр benchmark | decorator-based регистрация и lookup (`register`, `get`, `list_benchmarks`) + встроенный noop smoke benchmark |
| `src/atman/eval/reporters/base.py`, `src/atman/eval/reporters/jsonl_reporter.py`, `src/atman/eval/reporters/db_reporter.py` | reporting | Reporter ABC + JSONL-события lifecycle + PostgreSQL-запись в `eval.benchmark_runs` / `eval.run_items` |
| `src/atman/eval/seed_manager.py`, `src/atman/eval/hardware.py` | runtime metadata | управление seed и hardware probe с graceful fallback без NVML/GPU |
| `eval/migrations/alembic.ini`, `eval/migrations/env.py` | eval storage | конфигурация Alembic для изолированной PostgreSQL-схемы `eval` |
| `eval/migrations/versions/0010_*` ... `0040_*` | eval storage | идемпотентная схема eval, таблицы benchmark run, supporting tables и materialized view трендов |
| `scripts/eval/partition_manager.py` | операции | создаёт будущие partitions, отсоединяет старые partitions и показывает статус partitions `eval.benchmark_runs` |
| `scripts/eval/eval_linguistic_quality.py` | offline eval | качество NER + классификации: 23 NER-примера (персоны/орг/место/тема/здоровье на русском), 5 примеров классификации; вычисляет precision/recall/F1 и accuracy; `--adapter gliner|noop`, `--verbose`; exit 1 при FAIL; цель: NER F1 ≥ 0.65, accuracy ≥ 0.70 |
| `src/demo_eval_runner.py`, `docs/features/eval-runner/README.md`, `docs/features/eval-runner/README-ru.md` | demo/docs | воспроизводимый walkthrough E1 runner + двуязычная документация |

---

## 2. Интеграции

Связки, где две или более частей работают вместе. Это места, где может сломаться **стык**, а не сама логика.

### 2.1. Сервис ↔ порт

| Связка | Файлы | Тип |
|--------|-------|-----|
| `ExperienceService` ↔ `StateStore` | `core/services/experience_service.py` → `core/ports/state_store.py` | DI |
| `IdentityService` ↔ `StateStore` | `core/services/identity_service.py` → `core/ports/state_store.py` | DI |
| `NarrativeService` ↔ `StateStore` | `core/services/narrative_service.py` → `core/ports/state_store.py` | DI |
| `SessionManager` ↔ `StateStore` | `core/services/session_manager.py` → `core/ports/state_store.py` | старт: identity/narrative + `IdentitySnapshot`; `finish_session`: детерминированный `SessionExperience.id` (uuid5 от `session_id`) для идемпотентных ретраев; active journals держат advisory lock, чтобы другой `SessionManager` не восстановил live-сессию; session journal включает полный payload `KeyMoment` и метаданные завершения (тон, insight, alignment), чтобы orphan recovery мог восстановить отсутствующие строки моментов и достроить downstream-артефакты без потери исходного summary завершения; если падение происходит после записи experience, но до eigenstate/narrative, recovery достраивает недостающие артефакты завершения перед удалением journal; вызывает `get_key_moment` + `create_key_moment` для каждого момента (идемпотентность ретраев); вычисляет `unexamined_fact_refs` (факты из `_facts_read`, но не упомянутые в `fact_refs` ни одного key moment); загрузка eigenstate с фильтром `identity_id`; обновление recent narrative через `save_narrative(..., expected_updated_at=...)` |
| `NarrativeRevisionService` ↔ `NarrativeRepository` | `core/services/narrative_revision.py` → `core/ports/reflection.py` | оптимистическая блокировка |
| `IdentityService` ↔ `SelfAppliedChangeStore` | `core/services/identity_service.py` → `core/ports/self_applied_changes.py` | **R11.5** запись аудита на каждом `apply_self_change`; revert читает `before_snapshot` |
| `NarrativeRevisionService` ↔ `SelfAppliedChangeStore` | `core/services/narrative_revision.py` → `core/ports/self_applied_changes.py` | **R11.5** аудит для `apply_self_layer_update` / `revert_self_change` |
| `resolve_pending_review` ↔ `PendingHumanReviewInbox` | `adapters/agent/tools.py` → `core/ports/pending_human_review.py` | **R11.7** инструмент регистрируется только при наличии inbox в `AtmanDeps`; runner вкладывает нерешённые элементы первым system-сообщением |
| `request_reflection` ↔ `ReflectionRequestQueue` | `adapters/agent/tools.py` → `core/ports/reflection_request_queue.py` | **R12** инструмент регистрируется только при наличии очереди в `AtmanDeps`; идемпотентность через `agent_driven_run_key` (UTC hour bucket) |
| `DailyReflectionService` / `DeepReflectionService` ↔ `ReflectionRequestQueue` (R12 drain) | `core/services/reflection_service.py` → `core/ports/reflection_request_queue.py` | опциональный аргумент очереди; на каждом живом `reflect()` `take_pending(level)` дрейнит pending agent-driven запросы; reasons попадают в LLM-контекст (`agent_requested_focus`) и `ReflectionEvent.key_insight`/`notes`; `mark_consumed` после успешного persist. Replay-путь (идемпотентный re-run) **не** дрейнит снова — запросы, поданные между ранами, ждут следующего живого джоба. |
| `MicroReflectionService` ↔ `SessionRepository` + `NarrativeRepository` | `core/services/reflection_service.py` | читает одну сессию + её key moments, синтезирует виртуальный `SessionExperience` через `services/session_experience_view.build_session_experience`, апдейт recent-слоя (R-Micro — мигрирован с `ExperienceRepository`) |
| `MicroReflectionService` ↔ `SkillManagerPort` | `core/services/reflection_service.py` | **WP-08 v2** опциональный хук: если `skill_manager` и `agent_id` заданы, вызывает `process_session_skills(agent_id, session_id)` после апдейта нарратива; ошибки подавляются, чтобы слой навыков не мог заблокировать рефлексию |
| `DailyReflectionService` ↔ `SessionRepository` + `PatternStore` + `ReflectionEventStore` | `core/services/reflection_service.py` | детекция паттернов (R3 — мигрирован с `ExperienceRepository`; синтезирует виртуальные `SessionExperience` через `services/session_experience_view.build_session_experience`) |
| `DailyReflectionService` ↔ `StructuredMarkersAggregator` (R5) | `core/services/structured_markers_aggregator.py` | чистая агрегация над `KeyMoment.structured_markers`; ≥5 моментов с одинаковым `signal_type`/`signal_value` → daily `PatternCandidate` через `PatternStore.save_with_detection_key` (идемпотентно по `daily_marker_pattern_detection_key`) |
| `DailyReflectionService` ↔ `DivergenceAggregator` (R6) | `core/services/divergence_aggregator.py` → `core/ports/divergence_events.py` (`DivergenceEventStore`) + `PatternStore` | опциональный хук; читает `divergence_events` за UTC-день (per-agent), группирует по `divergence_type` и пишет `PatternCandidate(BEHAVIOR)` для каждого типа с ≥ `min_count` (по умолчанию 3) событий (идемпотентно через `daily_divergence_pattern_detection_key`); любое событие `severity='rupture'` попадает в `ReflectionEvent.key_insight` независимо от порога |
| `DailyReflectionService` / `DeepReflectionService` ↔ `EntityStanceFormulator` (R7) | `core/services/entity_stance_formulator.py` → `core/ports/entity_stance.py` (`EntityStanceStore`), `core/ports/entity_registry.py` (`EntityRegistry.get_entity` / `list_entities`), `core/ports/state_store.py` (`find_moments_by_entity`), `core/ports/reflection.py` (`ReflectionModel.formulate_entity_stance` + `SYSTEM_PROMPT_STANCE`) | опциональный хук (требует `agent_id`); Daily `formulate_for_new_entities` пишет новый provisional stance для каждой сущности с ≥ `DEFAULT_MIN_MOMENTS` (5) моментов — старый stance автоматически superseded (никогда не удаляется), `based_on_moment_ids` обязателен (§9); Deep `revise_stale` пересматривает stances старше `DEFAULT_STALENESS_DAYS` (30) на новых моментах — материальное изменение valence (≥ `STANCE_MATERIAL_CHANGE_THRESHOLD`=0.2) пишет новый, иначе промоутит существующий в non-provisional и поднимает `confidence` на `CONFIDENCE_REAFFIRM_BUMP` (0.1). Stance — интерпретация, не агрегация; пустой `stance_text` от LLM трактуется как "decline" и пропускается. |
| `DailyReflectionService` ↔ `FindingsTriage` (R8) | `core/services/findings_triage.py` → `core/ports/memory_guardian.py` (`get_unresolved` / `resolve_finding`) | опциональный хук; резолвит уровень B (`info`/`warning`) `validation_findings` по правилам: `orphan_entity`→`ignored` (kept by policy), `pending_structured_markers`→`ignored` (accepted as-is), `analysis_failed`/`affect_detector_silent`→`requires_attention`, тривиальный `similar_entities` (cosine ≥ `DAILY_TRIVIAL_DUPLICATE_THRESHOLD=0.98`)→`ignored` (передаётся в Deep R10), нетривиальный `similar_entities`→остаётся unresolved для Deep R10. Critical-severity findings **никогда** не резолвятся автоматически здесь |
| `DeepReflectionService` ↔ `SessionRepository` + `IdentityRepository` + `NarrativeRepository` + `PatternStore` + `HealthAssessmentStore` + `ReflectionEventStore` | `core/services/reflection_service.py` | здоровье + апдейт identity и нарратива (R4 — мигрирован с `ExperienceRepository`; синтезирует виртуальные `SessionExperience` через `services/session_experience_view.build_session_experience`) |
| `DeepReflectionService` ↔ `EntityRelationsFormulator` (R9) | `core/services/entity_relations_formulator.py` → `core/ports/entity_relation_store.py` (`EntityRelationStore`), `core/ports/entity_registry.py`, `core/ports/state_store.py` (`find_moments_by_entity`), `core/ports/reflection.py` (`ReflectionModel.formulate_entity_relation` + `SYSTEM_PROMPT_ENTITY_RELATION`) | опциональный хук (требует `agent_id`); строит co-occurrence индекс над `KeyMoment`-ами из entity registry, спрашивает LLM по каждой паре с co-occurrence ≥ `DEFAULT_MIN_COOCCURRENCES` (3) о типизированной связи, и пишет подтверждённые связи (`confidence ≥ DEFAULT_MIN_CONFIDENCE`=0.7) как `learned_by='reflection'`. Сосуществует с realtime mREBEL extraction — store dedups по `(agent, pair, type, learned_by)`. |
| `PrincipleRevisionAdvisor` ↔ `PatternCandidate` + `Identity` | `core/services/principle_advisor.py` | анализ паттернов в контексте identity |
| `ConflictDetector` ↔ `FactualMemory` | `core/services/conflict_detector.py` → `core/ports/memory_backend.py` | DI; лёгкий поиск противоречий среди ACTIVE-кандидатов, возвращённых `search()` |
| `EmotionalEcho` ↔ `StateStore` | `core/services/emotional_echo.py` → `core/ports/state_store.py` | DI; окно `lookback_days` через `search_experiences` |
| `PassiveMemoryInjector` ↔ `EmbeddingPort` + `FactualMemory` + `StateStore` + опциональные `LinguisticAnalyzer` + `MemoryReranker` + второй `EmbeddingPort` (BM25) | `core/services/passive_memory_injector.py` → `core/ports/embedding.py`, `core/ports/memory_backend.py`, `core/ports/state_store.py`, `core/ports/linguistic.py`, `core/ports/memory_reranker.py` | DI; пул кандидатов по salience (`query=None` в бэкенд) → dense similarity → опциональный BM25 RRF fusion → опциональный reranker → 1-hop associative expansion с реальными similarity-скорами; опциональный `SessionWorkingMemory` кеш |
| `MaintenanceWorker` ↔ `MaintenanceQueue` + `SalienceDecayService` + `MemoryGuardian` | `core/services/maintenance_worker.py` → `core/ports/maintenance_queue.py`, `core/ports/salience_decay.py`, `core/ports/memory_guardian.py` | DI; `run_once()` забирает батч и диспетчеризует задачи |
| `DivergenceDetector` ↔ `AgentMessageAnalysis` | `core/services/divergence_detector.py` | stateless; маппинг сигнальных меток из анализа в список `DivergenceEvent` |
| `KeyMomentBuilder` ↔ `KeyMomentInput` + `KeyMomentAnalysis` | `core/services/key_moment_builder.py` | stateless; заполняет `structured_markers` из анализа |

### 2.2. Адаптер ↔ порт

| Адаптер | Реализует |
|---------|-----------|
| `InMemoryBackend`, `FileBackend`, `PostgresFactualMemory` | `FactualMemory` |
| `InMemoryExperienceStore`, `JsonlExperienceStore`, `FileStateStore`, `InMemoryStateStore`, `PostgresStateStore` | `StateStore` |
| `MockReflectionModel`, **`OpenAIReflectionModel`** | `ReflectionModel` |
| `InMemoryPatternStore`, `InMemoryReflectionEventStore`, `InMemoryHealthAssessmentStore` | соответствующие порты |
| **`InMemoryReflectionStore`** | **`ReflectionStore`** (E27) |
| `MockEmbeddingAdapter`, `BM25EmbeddingAdapter`, `OllamaEmbeddingAdapter`, `FlagEmbeddingAdapter` | `EmbeddingPort` |
| `InMemoryUsageLog` | `MemoryUsageLog` |
| `InMemoryEntityRegistry`, `PostgresEntityRegistry` | `EntityRegistry` |
| `InMemoryEntityStanceStore`, `PostgresEntityStanceStore` | `EntityStanceStore` |
| `InMemoryMemoryGuardian` | `MemoryGuardian` |
| `NoOpLinguisticAnalyzer`, `GLiNERPlusMiniLMAdapter` | `LinguisticAnalyzer` |
| `NoOpReranker`, `BgeReranker` | `MemoryReranker` |
| `InMemoryMaintenanceQueue`, `PostgresMaintenanceQueue` | `MaintenanceQueue` |
| `MRebelRelationAdapter` | `EntityRelationExtractor` |
| `StateStoreSessionRepository` (`adapters/reflection/`) | `SessionRepository` (R1 — преемник ExperienceRepository) |
| `InMemorySkillStore` (`skills/in_memory_store.py`), `PostgresSkillStore` (`skills/postgres_store.py`) | `SkillStore` (WP-08 v2) |
| `NoopSkillManager` (`skills/noop.py`), `SkillManager` (`skills/manager.py`) | `SkillManagerPort` (WP-08 v2) |
| `InMemoryDivergenceEventStore` (`adapters/memory/in_memory_divergence_events.py`) | `DivergenceEventStore` (R6) |
| `InMemoryEntityRelationStore` (`adapters/memory/in_memory_entity_relation_store.py`) | `EntityRelationStore` (R9) |

### 2.2a. Agent adapter ↔ сервисы

| Связка | Файлы | Тип |
|--------|-------|-----|
| `AtmanDeps` ↔ `SessionManager`, `IdentityService`, `ExperienceService`, `MicroReflectionService`, `StateStore` | `adapters/agent/deps.py` | DI-контейнер (frozen dataclass); опциональный `injected_context` для режима `system_prompt` внедрения памяти; **WP-08 v2** опциональное `skill_manager: SkillManagerPort | None` |
| `record_key_moment` / `log_experience` / `restart_session` / `wait_session` ↔ `AffectDetector.submit_self_report` / `SessionManager` | `adapters/agent/tools.py` → `affect/detector.py` + `core/services/session_manager.py` | Async Pydantic AI инструменты → affect write gateway (`record_key_moment` требует `affect_workspace` + config для `SessionManager`; `restart_session` / `wait_session` возвращают sentinel-строки для детекции в E22.5 runner) |
| `build_instructions` / `build_memory_context` / `inject_memory` ↔ `StateStore.load_identity` / `load_narrative` | `adapters/agent/instructions.py`, `adapters/agent/memory_injection.py` → `core/ports/state_store.py` | Динамический билдер system-prompt + билдер контекста памяти + универсальное внедрение (три режима: `assistant_message` / `user_message` / `system_prompt`) |
| `chat` / `_force_finish` / `_do_restart` / `_handle_menu_mode` / `_handle_free_time_mode` ↔ `SessionManager` | `adapters/agent/runner.py` → `core/services/session_manager.py` | регистрация signal handler + exception boundary + restart loop + таймаут/меню (E22.2, E22.5, E22.6, E22.7); вызывает `append_key_moment_input()`, `get_active_session()`, `finish_session(..., close_reason=...)` при прерывании и restart; restart workflow: завершает сессию с `close_reason="restart"`, строит package, запускает новую сессию, обновляет `AtmanDeps` с новым `session_id`; инжекция wake-up сообщения из `close_reason` последней сессии; таймаут → menu mode (reflect/wait/sleep/save_to_memory/free_time); `AtmanRunner.chat()` переводит SIGTERM в async input queue для graceful shutdown |

### 2.3. CLI ↔ сервис

| CLI | Проводка | Файл |
|-----|----------|------|
| `cli.py` | фабрика `build_memory_backend()` (`FileBackend` по умолчанию, выбор `postgres|file|inmemory` через env) | `config.py`, `cli.py` |
| `cli_experience.py` | `ExperienceService(JsonlExperienceStore)` | `cli_experience.py:17-29` |
| `cli_identity.py` | `IdentityService(FileStateStore)` + `NarrativeService(FileStateStore)` | `cli_identity.py:15-29` |
| `cli_reflection.py` | `Micro/Daily/DeepReflectionService` + fixture_loader | `cli_reflection.py:18-47` |
| `benchmark_runner.py` (module-only) | `RunnerCore` + `registry` + `reporters` (`jsonl`, опционально DB) | `eval/benchmark_runner.py` |

### 2.4. Демо ↔ реальные объекты

| Демо | Цепочка |
|------|---------|
| `demo.py` | `InMemoryBackend` + `FileBackend` для `FactualMemory` |
| `demo_experience_store.py` | `JsonlExperienceStore` → `ExperienceService` |
| `demo_identity.py` | `FileStateStore` → `IdentityService` + `NarrativeService` |
| `demo_session_manager.py` | `FileStateStore` → `SessionManager` (загрузка identity/narrative, запись событий/моментов, сохранение experience/eigenstate) |
| `demo_reflection.py` | моки + fixture_loader → `MicroReflectionService` → `DailyReflectionService` → `DeepReflectionService` |
| `demo_full_corpus.py` | JSON сессий `e2e` → `FileStateStore` + `SessionManager` + `StateStore*Adapter` → micro → daily (за UTC-сутки) → deep; `DeterministicReflectionModel` |
| `demo_eval_runner.py` | `list_benchmarks()` → `RunnerCore([JsonlReporter])` + `noop` benchmark → идемпотентный перезапуск с тем же `git_sha` → JSONL-артефакт |

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
MicroReflectionService — читает одну сессию + её key moments через SessionRepository
  ↓ обновляет
NarrativeRepository (recent-слой) — оптимистическая блокировка
  ↓
DailyReflectionService — читает сессии + key moments через SessionRepository за UTC-сутки, детектит паттерны
  ↓ сохраняет
PatternStore + ReflectionEventStore
  ↓
DeepReflectionService — читает сессии + key moments через SessionRepository, оценивает здоровье,
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
2. Во время сессии: `record_event(...)` отслеживает сырые события от нижнего агента и при наличии конфигурации планирует **AffectDetector**; **ценностные отказы авто-детектируются через `RefusalDetectorConfig` и молча записываются как key moments** без уведомления агента.
3. Программные моменты: `append_key_moment_input` / `append_key_moment`; инструмент агента `record_key_moment` → `AffectDetector.submit_self_report(...)` с обязательной эмоциональной окраской (valence/intensity/depth).
4. Если окраска неполная → флаг `incomplete_coloring=True` (честность об ограничении).
5. `finish_session(...)` → создаёт `SessionExperience` (`recorded_by="session_manager"`) + `Eigenstate`; принимает опциональные `close_reason`, `restart_reason`, **`user_language`** для wake-up контекста при старте следующей сессии.
6. Оба сохраняются через `StateStore` (опыт immutable, eigenstate для следующей сессии).
7. Ключевой инвариант: эмоциональная окраска ОБЯЗАНА быть (от реального переживания) или явно помечена неполной.
8. `KeyMomentInput.recorded_at` копируется в `KeyMoment.when` для согласованной временной шкалы относительно валидации и `finish`.
9. `finish_session(..., alignment_check=False)` требует непустой `alignment_notes`.
10. `list_active_sessions()` возвращает `ActiveSessionSummary` (счётчики и `started_at`) для сессий не в фазе завершения.

### I. Полный прогон корпуса E2E-фикстур сессий

Файлы: `docs/features/full-corpus-demo/`, `src/demo_full_corpus.py`, `e2e/full_loop.py`, `tests/test_demo_full_corpus.py`.

1. `load_all_fixture_sessions_sorted(locale)` упорядочивает файлы по `metadata.session_number`.
2. Для каждой фикстуры: `FrozenClock` сдвигается на один UTC-день; `run_session_from_fixture(...)` → опыт + eigenstate.
3. `MicroReflectionService.reflect(session_id)`, затем `DailyReflectionService.reflect(day)` за этот календарный день.
4. После цикла: `DeepReflectionService.reflect(since, until)` на весь интервал.
5. Итоговая таблица Rich: bootstrap vs накопленные сторы, касания принципов, выборка настроения, паттерны, рефрейминг, recent-слой нратива ([issue #158](https://github.com/hleserg/atman/issues/158)).

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
| `KeyMomentInput` с нулевым valence/intensity без `incomplete_coloring` | `SessionManager.append_key_moment_input` → `ValueError` | `core/services/session_manager.py` |
| Устаревший `SessionManager.record_key_moment(...)` | `AttributeError` (сообщение ссылается на `AffectDetector`) | `core/services/session_manager.py` |
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
- ⏳ **Session Manager: неограниченный рост recent narrative** — каждый `finish_session` добавляет session summary в `recent_layer.content` без вытеснения; после многих сессий (100+) контент может превысить токен-лимиты или ухудшить производительность. Требуется trim/sliding-window логика. Отслеживается в issue (будет создан).

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
| `6a9f28f` | `SessionManager.finish_session` заменял recent narrative вместо добавления summary, теряя контекст | покрыто (`tests/test_session_manager.py::test_finish_session_appends_to_recent_narrative_without_erasing_existing_context`) |
| `0ef0587` | `setup-openwebui.sh` по умолчанию открывал регистрацию первого admin в LAN | покрыто (`tests/test_deployment_scripts.py`) |
| `b47abcb` | `eval.benchmark_runs` создавал только partition текущего месяца, поэтому вставки с `started_at=NOW()` падали после границы месяца | покрыто (`tests/test_eval_migrations.py::test_benchmark_runs_migration_creates_default_partition_safety_net`, `tests/test_eval_migrations.py::test_benchmark_runs_migration_rolls_december_partition_to_next_year`, `tests/test_eval_migrations.py::test_benchmark_runs_sql_mirror_documents_default_partition_safety_net`) |
| текущий PR | PostgreSQL RLS допускал owner-role bypass для `reflections` и открывал `fact_relations` без RLS | покрыто (`tests/test_postgres_migration_security.py`) |
| текущий PR | CLI факт-памяти по умолчанию выбирал PostgreSQL и падал без локальной БД, нарушая локальный путь без внешних сервисов | покрыто (`tests/test_cli_factual_memory.py`) |
| текущий PR | Orphan recovery сессии создавал `SessionExperience` со ссылками на отсутствующие `KeyMoment` после crash/interrupt | покрыто (`tests/test_session_manager.py::test_orphan_recovery_restores_journaled_key_moment_payload`) |
| текущий PR | Новые workspace для `run_agent.py` создавали записи в реестре, но падали до REPL из-за отсутствующих identity/narrative и неактивных журналов | покрыто (`tests/test_runner.py::test_build_deps_bootstraps_state_and_enables_session_journal`) |
| текущий PR | `PostgresStateStore.create_key_moment()` писал placeholder session ID, из-за чего последующий `store_key_moments()` не связывал момент с реальной сессией | покрыто (`tests/test_postgres_state_store.py::test_store_key_moments_updates_placeholder_session`) |
| текущий PR | Второй `SessionManager` мог восстановить и удалить active-session journal, который всё ещё принадлежал live-процессу | покрыто (`tests/test_session_manager.py::test_orphan_recovery_skips_journals_locked_by_another_manager`) |
| текущий PR | Падение после записи `SessionExperience`, но до eigenstate/narrative заставляло orphan recovery удалить последний journal без достраивания артефактов непрерывности | покрыто (`tests/test_session_manager.py::test_orphan_recovery_completes_existing_experience_after_crash`) |
| текущий PR | Падение после записи `SessionExperience` могло восстановить eigenstate/narrative с дефолтным тоном и без `key_insight`, молча теряя исходное summary завершения | покрыто (`tests/test_session_manager.py::test_orphan_recovery_completes_existing_experience_after_crash`) |
| текущий PR | Идемпотентность Eval Runner игнорировала `seed`, молча пропуская разные seeded benchmark runs в одном процессе | покрыто (`tests/atman_eval/test_runner_core.py::test_runner_core_runs_distinct_seeds_for_same_git_sha`) |
| текущий PR | SIGTERM до первого key moment завершал сессию как обычную, а не как `interrupted` | покрыто (`tests/test_runner.py::test_atman_runner_sigterm_empty_session_persists_interrupted`) |
| текущий PR | BGE-M3 по умолчанию создавал 1024-мерные эмбеддинги, пока PostgreSQL схемы/deploy defaults/search casts оставались на старых предположениях о векторах, ломая запись embedded facts, re-embedding или semantic search | покрыто (`tests/test_postgres_migration_security.py::test_facts_migration_matches_bge_m3_embedding_dimension`, `tests/test_postgres_migration_security.py::test_agent_schema_matches_bge_m3_embedding_dimension`, `tests/test_postgres_migration_security.py::test_embedding_migration_rebuilds_schema_before_writing_vectors`, `tests/test_postgres_backend.py::test_search_uses_halfvec_literal_for_semantic_ordering`, `tests/test_deploy_package.py::test_deploy_schema_matches_bge_m3_fact_embedding_dimension`, `tests/test_deploy_package.py::test_deploy_defaults_match_bge_m3_embedding_dimension`, `tests/test_deploy_package.py::test_inline_setup_schemas_match_bge_m3_fact_embedding_dimension`) |
| текущий PR | Фабрика Pydantic AI test agent передавала неподдерживаемые kwargs `base_url` / `api_key`, а пакет `agent` не попадал в wheel | покрыто (`tests/agent/test_atman_agent.py::test_agent_can_be_constructed_without_llm_endpoint`, `tests/agent/test_atman_agent.py::test_agent_package_is_included_in_wheel`) |
| WP-08 v2 | Редизайн слоя навыков: полный skill-loop (models, manifest, store, retriever, manager, agent tools, CLI, reflection hook, bootstrap-инжекция) реализован и изолирован за `SkillManagerPort`; 79 новых тестов | покрыто (`tests/test_skill_models.py`, `tests/test_skill_noop.py`, `tests/test_skill_store.py`, `tests/test_skill_retriever.py`, `tests/test_skill_manager.py`, `tests/test_skill_reflection_hook.py`, `tests/test_skill_bootstrap.py`) |

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
| Инварианты session → experience → reflection (E2E-02, #145) | ✅ закрыто | `tests/integration/test_full_lifecycle.py::test_full_lifecycle_session_experience_reflection_invariants` |
| CLI surface (factual / experience / identity / reflection) | ✅ закрыто | `tests/test_cli_factual_memory.py`, `tests/test_cli_experience.py`, `tests/test_cli_identity.py`, `tests/test_cli_reflection.py` |
| Demo entrypoints (smoke) | ✅ закрыто | `tests/test_demo_smoke.py`, `tests/test_demo_full_corpus.py` |
| **Интеграция полного жизненного цикла (E2E-02)** | ✅ закрыто | `tests/integration/test_full_lifecycle.py` — проверяет (1) неизменяемость опыта после завершения сессии, (2) появление reframing notes от рефлексии в опытах, (3) обновление narrative.recent_layer после micro reflection, (4) propagation identity_snapshot_id session → experience → reflection |
| Open WebUI LAN exposure default | ✅ закрыто | `tests/test_deployment_scripts.py` |

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

- 33 тест-модуля в `tests/` + 1 интеграционный модуль (включает 7 тест-модулей слоя навыков, 79 тестов).
- Тесты эмбеддингов: `tests/memory/test_embedding_mock.py` (≥25 тестов), `tests/memory/test_embedding_ollama.py` (≥20 тестов) — покрытие E25.
- Интеграционные тесты: `tests/integration/test_full_lifecycle.py` — полный жизненный цикл от старта сессии до рефлексии с FileStateStore.
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
