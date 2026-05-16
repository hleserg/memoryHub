# Atman System Map

> Created in response to [issue #125](https://github.com/hleserg/atman/issues/125).
> Purpose — a structured inventory of the codebase to plan test coverage:
> modules, integrations, user scenarios, edge cases, and known regressions.
>
> **Maintenance:** this map is a living document. Any code change that adds, removes,
> or rewires modules, ports, adapters, services, CLI/TUI/web entrypoints, demos, or
> end-to-end flows MUST update both `SYSTEM_MAP.md` and `SYSTEM_MAP-ru.md` in the
> same PR. New tests should be cross-referenced to the relevant section of this map
> (see `docs/development/DEVELOPMENT_STANDARD.md` §26).

All paths are absolute relative to the repository root.

---

## 1. Modules

### 1.1. Domain models (`src/atman/core/models/`)

| File | Purpose | Public classes |
|------|---------|----------------|
| `core/models/fact.py` | Verifiable facts and links between them | `FactRecord`, `Relation` |
| `core/models/experience.py` | Lived experience, key moments (with `id: UUID` for independent storage), reframing, session closure metadata (E22.7: `close_reason`, `restart_reason`, `user_language`); **v2**: `KeyMoment` is a first-class standalone record with `session_id`, `salience`, `salience_at`, `last_accessed_at`, `access_count`, `importance`, `incomplete_coloring`, `recorded_by`, `identity_snapshot_id`, `structured_markers`, `structured_markers_version`, `schema_version="2.0.0"`; `mark_accessed()` and `calculate_current_salience()` methods on `KeyMoment`; `SessionExperience` kept as read-only view for Reflection compat | `SessionExperience`, `KeyMoment`, `FeltSense`, `ContextHalo`, `ReframingNote`, `EmotionalDepth`, `ReframingNoteAppendResult` |
| `core/models/identity.py` | Agent's self-representation (values, habits, principles, goals, open questions) | `Identity`, `CoreValue`, `Habit`, `Principle`, `Goal`, `OpenQuestion`, `IdentitySnapshot`, `HelpfulnessLevel` |
| `core/models/narrative.py` | Self-narrative document (CORE/RECENT/THREADS) and eigenstate | `NarrativeDocument`, `NarrativeLayer`, `NarrativeThread`, `Eigenstate` (`schema_version`, optional `identity_id`), `LayerType` |
| `core/models/session.py` | Session runtime models: context, events, key moment input, result, active listing; **v2**: `Session` persistence model with `close_reason`, `agent_recap`, `restart_reason`, `user_language`, `overall_tone`, `key_insight`, `unexamined_fact_refs` | `SessionContext`, `SessionEvent`, `KeyMomentInput`, `SessionResult`, `ActiveSessionSummary`, **`Session`** |
| `core/models/entity.py` | Entity Registry domain models: entity types, aliases, relations, stances, and link tables for facts and key moments | `Entity`, `EntityAlias`, `EntityRelation`, `EntityStance`, `EntityType`, `FactEntityLink`, `KeyMomentEntityLink`, `ResolutionMethod` |
| `core/models/validation.py` | Observability models: validation findings (data quality) and divergence events (thinking vs message gap detection) | `ValidationFinding`, `FindingSeverity`, `FindingType`, `DivergenceEvent`, `DivergenceSeverity`, `DivergenceType` |
| `core/models/maintenance.py` | Maintenance queue models for background/cron jobs (salience decay, memory guardian) | `MaintenanceJob`, `JobName`, `JobStatus` |
| `core/models/reflection.py` | Reflection processes, patterns, health assessment (Jahoda criteria), structured LLM/mock outputs (MODEL-01 / #146), **PostgreSQL reflections persistence** (E27) | `ReflectionLevel`, `PatternCandidate`, `PatternStatus`, `PatternType`, `ReflectionEvent`, `HealthAssessment`, `JahodaCriterion`, `CriterionAssessment`, `ReframingNoteOutput`, `PatternDetectionOutput`, `NarrativeUpdateOutput`, `HealthCriterionOutput`, **`ReflectionRecord`** |
| `core/models/governance.py` | Governance decisions for core narrative mutations | `GovernanceDecision`, `GovernanceMode` |
| `core/models/self_applied_change.py` (R11.5) | Audit row for identity/narrative changes reflection applies on its own (rationale, supporting moment ids, before-snapshot) | `SelfAppliedChange`, `SelfChangeSource`, `SelfChangeTargetKind`, `SelfChangeActor` |
| `core/models/pending_human_review.py` (R11.7) | Inbox items for changes reflection is not confident enough to self-apply | `PendingReview`, `PendingReviewDraft`, `PendingReviewKind`, `Priority`, `Resolution` |
| `core/models/reflection_request.py` (R12) | Agent-driven `request_reflection` queue entry | `ReflectionRequest`, `ReflectionRequestLevel` |

### 1.2. Ports / interfaces (`src/atman/core/ports/`)

| File | Purpose | Contracts |
|------|---------|-----------|
| `core/ports/memory_backend.py` | Factual memory interface; **v2**: `add_fact_with_entities` + `find_facts_by_entity` for entity-link tables | `FactualMemory` (ABC) |
| `core/ports/entity_relations.py` | Binary relation extraction (mREBEL / rules) | `EntityRelationExtractor` (ABC), `ExtractedRelation` |
| `core/ports/clock.py` | Domain clock for reproducibility | `ClockPort` (Protocol) |
| `core/ports/state_store.py` | Storage for experience/identity/narrative/eigenstate/key moments; **v2**: extended with sessions API (`create_session`, `get_session`, `update_session`, `list_recent_sessions`) and standalone KeyMoment API (`store_key_moment` idempotent upsert, `mark_moment_accessed`, `update_moment_structured_markers`, `find_moments_by_entity`) | `StateStore` (with `create_key_moment`, `store_key_moment`, `list_key_moments`, `get_key_moment`, `mark_moment_accessed`, `update_moment_structured_markers`, `find_moments_by_entity`, `create_session`, `get_session`, `update_session`, `list_recent_sessions`), `ExperienceQuery`, `SessionExperienceQuery`, `ValuesTouchedQuery`, `DepthQuery`, `DateRangeQuery`, `FactRefsContainsQuery` |
| `core/ports/entity_registry.py` | Entity Registry — resolve-or-create pattern with L1/L2/L3 tiers (alias exact → cosine similarity → new entity) | `EntityRegistry` (ABC): `resolve_or_create`, `get_entity`, `find_by_name`, `add_alias`, `merge_entities`, `update_last_seen`, `list_entities`, `flag_disambiguation` |
| `core/ports/linguistic.py` | Linguistic analysis: NER + zero-shot classification at user-message (U), agent-message (A), and key-moment (K) analysis points | `LinguisticAnalyzer` (ABC), `AmbientAnchor`, `DetectedEntity`, `UserMessageAnalysis`, `AgentMessageAnalysis`, `KeyMomentAnalysis` |
| `core/ports/memory_reranker.py` | Cross-encoder reranker for RAG candidates (ambient memory surfacing) | `MemoryReranker` (ABC): `rerank(query, candidates, top_n)`, `SurfacedMemory` |
| `core/ports/entity_stance.py` | Agent's stance toward known entities — supersession chain | `EntityStanceStore` (ABC): `get_current_stance`, `get_stance_history`, `write_stance`, `supersede_stance`, `list_active_stances` |
| `core/ports/maintenance_queue.py` | DB-backed cron queue for background maintenance jobs; SKIP LOCKED semantics, run_key idempotency | `MaintenanceQueue` (ABC): `enqueue`, `claim_batch`, `mark_done`, `mark_failed`, `mark_skipped`, `list_jobs` |
| `core/ports/salience_decay.py` | Salience decay service — exponential decay with λ by emotional depth | `SalienceDecayService` (ABC): `decay_pass`, `mark_accessed`, `calculate_lambda` |
| `core/ports/memory_guardian.py` | Memory quality scanning and finding persistence | `MemoryGuardian` (ABC): `scan_orphan_entities`, `scan_merge_candidates`, `scan_stale_moments`, `scan_embedding_gaps`, `write_finding`, `get_unresolved`, `resolve_finding` |
| `core/ports/reflection.py` | Reflection Engine dependencies; `ReflectionModel` returns structured DTOs (#146) | `ExperienceRepository`, `IdentityRepository`, `NarrativeRepository`, `ReflectionModel`, `PatternStore`, `ReflectionEventStore`, `HealthAssessmentStore`, `ReflectionEventPersistenceObserver`, `NarrativeWriteAuditPort` |
| `core/ports/embedding.py` (E24.6) | Text embedding generation for semantic similarity | `EmbeddingPort` (Protocol) |
| `core/ports/memory_middleware.py` (E24) | Memory surfacing context wrapping | `MemoryMiddlewarePort` (Protocol), `MemoryContext` |
| `core/ports/memory_usage_log.py` (E24.10) | Audit log for surfaced/used memory items | `MemoryUsageLog` (ABC), `MemoryUsageRecord`, `UsageType` |
| `core/ports/reflection_store.py` (E27) | PostgreSQL `reflections` table interface | `ReflectionStore` (ABC): `add`, `get`, `list_by_session`, `list_recent`, `list_by_level`, `list_by_experience` |
| `core/ports/session_repository.py` (R1) | Reflection-side view of sessions + key moments + reframing notes; planned replacement for `ExperienceRepository` per Этап 18 (REFLECTION_FUTURE.md §3) | `SessionRepository` (Protocol): `get_session`, `list_recent_sessions`, `get_sessions_in_range`, `get_key_moments_for_session`, `get_key_moments_in_range`, `add_reframing_note` |
| `core/ports/self_applied_changes.py` (R11.5) | Audit store for reflection self-applied changes (append + revert) | `SelfAppliedChangeStore` (Protocol) |
| `core/ports/pending_human_review.py` (R11.7) | Pending-review inbox for low-confidence reflection proposals | `PendingHumanReviewInbox` (Protocol) |
| `core/ports/reflection_request_queue.py` (R12) | Queue for agent-driven reflection requests | `ReflectionRequestQueue` (Protocol) |
| `core/ports/reflection_overload_alert.py` (R13) | Sink for reflection-cadence alerts (recalibration signal, not auto-fix) | `ReflectionOverloadAlertSink` (Protocol), `OverloadAlert`, `AlertSeverity` |
| `core/ports/skill_manager.py` (WP-08 v2) | Skill-loop interface consumed by all code outside `atman.skills`; `SkillManagerPort` is satisfied by both real `SkillManager` and `NoopSkillManager` | `SkillManagerPort` (runtime_checkable Protocol): `list_pinned`, `list_available`, `trigger_router`, `invoke`, `mark_result`, `capture`, `get_skill`, `process_session_skills` |

### 1.3. Services (`src/atman/core/services/`)

| File | Purpose | Classes |
|------|---------|---------|
| `core/services/experience_service.py` | Experience lifecycle: create, query, reframe, salience | `ExperienceService` |
| `core/services/identity_service.py` | Identity lifecycle: bootstrap, update, snapshot; **R11.5** reflection self-apply (`apply_self_change` / `revert_self_change`) for identity list fields and `self_description` with audit via optional `SelfAppliedChangeStore` | `IdentityService` |
| `core/services/narrative_service.py` | Narrative document: create, update, archive, validate | `NarrativeService` |
| `core/services/narrative_revision.py` | Narrative updates during reflection with concurrency control; **R11.5** `apply_self_layer_update` / `revert_self_change` for core/recent layers with audit via optional `SelfAppliedChangeStore` | `NarrativeRevisionService` |
| `core/services/session_manager.py` | Session runtime: start, `record_event` (optional async **AffectDetector** hook + **value refusal auto-recording**), `append_key_moment` / `append_key_moment_input`, finish with eigenstate (thread-safe registry, optional `max_active_sessions`, optional `affect_workspace` + `AffectDetectorConfig`, **optional `workspace` for JSONL session journals, inter-process journal locks, and orphan recovery**, **silent refusal detection via `RefusalDetectorConfig`**); **v2**: persists `Session` row via `state_store.create_session` at start and `update_session` at finish (best-effort, debug fallback for legacy stores) | `SessionManager`, `MAX_EIGENSTATE_ITEMS`; session errors live in `core/exceptions.py` |
| `core/services/reflection_service.py` | Three reflection levels: micro, daily, deep; **WP-08 v2**: `MicroReflectionService.__init__` accepts optional `skill_manager: SkillManagerPort | None`; `reflect(session_id, agent_id=None)` — calls `skill_manager.process_session_skills(agent_id, session_id)` at end if both are provided; errors are caught and logged, never surfaced to callers | `MicroReflectionService`, `DailyReflectionService`, `DeepReflectionService` |
| `core/services/session_experience_view.py` (R3) | Bridge helper that synthesises a virtual `SessionExperience` from a `Session` + `list[KeyMoment]` so `ReflectionModel` prompts keep working after `DailyReflectionService` migrated off `ExperienceRepository`; obsolete once `ReflectionModel` consumes `(Session, moments)` directly | `build_session_experience` |
| `core/services/reflection_overload_monitor.py` (R13) | Inspects `ReflectionEventStore` for abnormal cadence (Daily >1/day×3d → WARNING, Deep >1/3d → CRITICAL); emits alerts via sink; never auto-fixes — overload is a recalibration signal | `ReflectionOverloadMonitor` |
| `core/services/principle_advisor.py` | Distinguish habit vs principle; advise on principle revision | `PrincipleRevisionAdvisor` |
| `core/services/conflict_detector.py` (E24.5) | Detect contradictions between active facts; produces small cognitive tension signals | `ConflictDetector`, `FactConflict` |
| `core/services/emotional_echo.py` (E24.7) | Build historical emotional context from recent experiences (recency × intensity) | `EmotionalEcho`, `EchoItem` |
| `core/services/passive_memory_injector.py` (E24.6, E24.8) | Surface relevant facts/experiences via embedding similarity + 1-hop graph expansion; **v2**: ambient mode with optional `LinguisticAnalyzer` + `MemoryReranker` — entity anchors + parallel queries + reranking when both configured; falls back to dense search otherwise; `surface_key_moments_for_context()` using standalone key moments; **opt-2**: `build_rag_context(candidates, budget)` caps RAG output to `budget` tokens returning `RagContext(items, tokens_used)`; **v3 (semantic recall fix)**: `surface_for_context()` pulls candidates with `query=None` (substring filter bypassed) and a salience-ordered `candidate_pool_size` (default `max(top_k*10, 50)`); optional `bm25: EmbeddingPort` enables Reciprocal Rank Fusion (k=60) lifting exact lexical matches; cross-encoder reranker applied to facts in ambient mode (symmetric to key moments); associative neighbors get a real embedding similarity score capped at 0.5; `estimate_tokens` uses UTF-8 bytes/3 (Cyrillic-aware) | `PassiveMemoryInjector`, `SurfacedMemoryItem`, `RagContext`, `build_rag_context`, `estimate_tokens` |
| `core/services/session_cache.py` | Per-session entity resolution + RAG result cache; lives exactly one session; `invalidate_rag(entity_id)` drops stale results when a new fact/moment is written for that entity; `is_rag_cached()` for fast guard; `stats()` for debug logging | `SessionCache` |
| `core/services/reflection_input_builder.py` | Pre-summarize KeyMoments before deep reflection to prevent unbounded prompt growth; sorts by salience desc, caps at `max_moments`, groups by `session_id` into `SessionSummary(top_3, marker_counts, total_count)`; excess moments returned in `remaining_moments` for next cycle | `prepare_reflection_input`, `ReflectionInput`, `SessionSummary` |
| `core/services/key_moment_builder.py` | Build `KeyMoment` from `KeyMomentInput` + linguistic analysis + entity links | `KeyMomentBuilder` |
| `core/services/divergence_detector.py` | Rules-based divergence detection between agent thinking and message layers | `DivergenceDetector` |
| `core/services/salience_decay_service.py` | Exponential salience decay with λ parameterised by `EmotionalDepth`; `InMemorySalienceDecayService` for unit tests | `InMemorySalienceDecayService` |
| `core/services/maintenance_worker.py` | Claim and dispatch maintenance jobs (salience decay, memory guardian scan) from `MaintenanceQueue` | `MaintenanceWorker` |
| `core/services/post_write_scheduler.py` | Fire-and-forget enqueue of enrichment jobs (mREBEL, lingvo) keyed by `(job_name, key_moment_id)`; sync + asyncio-task variants | `PostWriteScheduler` |
| `core/services/session_working_memory.py` (E24.9) | In-session LRU cache of surfaced facts/experiences to avoid duplicate surfacing | `SessionWorkingMemory`, `CachedItem` |

### 1.4a. Affect detector (`src/atman/affect/`, E21)

| File | Purpose | Public surface |
|------|---------|----------------|
| `affect/models.py` | DTOs for metrics, detector output, agent self-report | `AffectMetrics`, `AffectRecord`, `AgentMemoryReport` (optional `emotional_depth` → `KeyMoment.how_i_felt.depth`), `TriggerReason` (incl. **`STRUCTURAL_MARKER`** for linguistic boundary events) |
| `affect/metrics.py` | Eight behavioural floats + sincerity heuristic over tokens | `nrc_emotion_score`, density helpers, `min_length_gate`, `sincerity_score`, … |
| `affect/baseline.py` | Rolling z-scores + `{workspace}/affect_baseline.jsonl` persistence | `RollingBaseline` |
| `affect/detector.py` | Language sniff, trigger logic (anomaly / random sample / divergence / self-report), `KeyMoment` writes via callback; **v2**: optional `LinguisticAnalyzer` DI for structured markers enrichment | `AffectDetector`, `AffectDetectorConfig`; CLI `python -m atman.affect.detector --demo` |
| `affect/refusal_detector.py` | Text-only value refusal detection (no LLM required) — three layers: (1) morphology via pymorphy3 (refusal verbs + negated modals), (2) NRC emotion semantic context (disgust/anger density for moral framing), (3) capability exclusion (technical inability vs ethical stance); optional LLM fallback for uncertain zone | `is_value_refusal`, `score_refusal`, `RefusalDetectorConfig`, `RefusalScore` |
| `affect/emolex/` | Vendored NRC Emotion Lexicon (ru/en) + pymorphy3 lemmatisation | `emotion_score`, `tokenize`, JSON lexicons |

### 1.4. Core utilities

| File | Purpose |
|------|---------|
| `config.py` | Pydantic settings (`EmbeddingSettings`, `LLMSettings`, `MemorySettings`), **`SkillsSettings`** (WP-08 v2: `enabled`, `skills_root`, `auto_pin_threshold_uses`, `auto_pin_threshold_sessions`, `auto_downgrade_sessions`, `min_confidence`), **`OpenAILLMConfig`** (base_url, api_key, model, timeout, max_retries with validation ≥1), **`AnthropicLLMConfig`** (api_key, model, max_tokens), `build_memory_backend()` factory, **`build_embedding_adapter()` factory** (selects FlagEmbedding/Ollama/Mock backend), `validate_embedding_dimension()` (startup dimension check); defaults: embedding backend=`ollama` with `bge-m3`/1024d (FlagEmbedding backend uses `flag_model="BAAI/bge-m3"`, with FP16/batch_size/max_length settings), LLM=`gemma3:27b-it-qat`, factual memory=`FileBackend`; supports `ATMAN_MEMORY_BACKEND=postgres|file|inmemory`, `EMBEDDING_BACKEND=ollama|flag|mock`; **legacy env var fallback**: `OLLAMA_HOST`→`EMBEDDING_OLLAMA_HOST`, `OLLAMA_EMBED_MODEL`→`EMBEDDING_MODEL`, `ATMAN_OLLAMA_BASE_URL`→`LLM_OLLAMA_HOST`, `ATMAN_OLLAMA_MODEL`→`LLM_MODEL`; **opt-2**: `EmbeddingSettings.cache_size` (default 4096, 0=disabled) passed to both FlagEmbedding and Ollama adapters |
| `core/exceptions.py` | `AtmanError`, `GovernanceRejectedError`, `NarrativePersistenceConflictError`, `SessionNotFoundError`, `SessionAlreadyFinishedError`, `TooManyActiveSessionsError` |
| `core/clock_impl.py` | `SystemClock`, `FrozenClock` |
| `core/narrative_write_audit.py` | Narrative commit audit hooks |
| `core/reflection_event_audit.py` | Reflection event persistence observers |
| `core/reflection_run_keys.py` | Deterministic reflection run keys |

### 1.5. Adapters (`src/atman/adapters/`)

| File | Implements port | Behavior |
|------|-----------------|----------|
| `adapters/memory/in_memory_backend.py` (`InMemoryBackend`) | `FactualMemory` | no persistence; `search()` returns results sorted by salience DESC (so `limit` truncation keeps the most important facts) |
| `adapters/memory/file_backend.py` (`FileBackend`) | `FactualMemory` | JSONL + file locking; `search()` sorted by salience DESC like InMemoryBackend |
| `adapters/memory/postgres_backend.py` (`PostgresFactualMemory`) | `FactualMemory` | PostgreSQL `public.facts` / `public.fact_relations`, RLS via `ATMAN_CURRENT_AGENT`, optional `EmbeddingPort` with `ILIKE` fallback |
| `adapters/memory/mock_embedding.py` (`MockEmbeddingAdapter`) | `EmbeddingPort` | deterministic SHA-256-seeded 1024-dim embeddings; no external deps; for tests/CI |
| `adapters/memory/bm25_embedding.py` (`BM25EmbeddingAdapter`) | `EmbeddingPort` | local BM25 sparse vectors via fixed-dimension feature hashing (Unicode-aware tokenizer); corpus stats from `embed_batch`/`embed_with_corpus` are reused by later `embed` calls |
| `adapters/memory/ollama_embedding.py` (`OllamaEmbeddingAdapter`) | `EmbeddingPort` | Ollama HTTP `/api/embeddings`; defaults: `bge-m3`/1024d; env: `EMBEDDING_MODEL`, `EMBEDDING_OLLAMA_HOST` (legacy: `OLLAMA_EMBED_MODEL`, `OLLAMA_HOST`); configurable timeout; **opt-2**: per-instance `lru_cache(maxsize=cache_size)` on `embed()` — repeated entity mentions skip HTTP round-trip; `cache_size=0` disables; `embedding_cache_info()` returns hit stats |
| `adapters/memory/flag_embedding.py` (`FlagEmbeddingAdapter`) | `EmbeddingPort` | Native FlagEmbedding SDK (BGEM3FlagModel) via PyTorch; lazy model loading (~570MB to `~/.cache/huggingface/`); supports dense (1024d) + sparse (lexical) + ColBERT via `embed_batch_full()`; configurable FP16, batch_size, max_length, device; no external process required; defaults: `BAAI/bge-m3`; env: `EMBEDDING_FLAG_MODEL`, `EMBEDDING_USE_FP16`, `EMBEDDING_BATCH_SIZE`, `EMBEDDING_MAX_LENGTH`; **opt-2**: per-instance `lru_cache(maxsize=cache_size)` on `embed()` — skips model inference on repeated texts; `embedding_cache_info()` for monitoring |
| `adapters/memory/in_memory_usage_log.py` (`InMemoryUsageLog`) | `MemoryUsageLog` | in-memory append-only list with filtering by item/usage_type/time (no eviction) |
| `adapters/storage/in_memory_experience_store.py` (`InMemoryExperienceStore`) | `StateStore` | in-memory (partial: experience only; KeyMoment/Identity/Narrative ops raise `NotImplementedError`) |
| `adapters/storage/jsonl_experience_store.py` (`JsonlExperienceStore`) | `StateStore` | JSONL for experience (partial: experience only; KeyMoment/Identity/Narrative ops raise `NotImplementedError`) |
| `adapters/storage/in_memory_state_store.py` (`InMemoryStateStore`) | `StateStore` | full in-memory implementation with deep copies; **v2**: sessions dict + standalone key_moments + `store_key_moment` (idempotent upsert), `mark_moment_accessed`, `update_moment_structured_markers`, `create_session`/`get_session`/`update_session`/`list_recent_sessions` |
| `adapters/storage/file_state_store.py` (`FileStateStore`) | `StateStore` | JSON files (experience + identity + narrative + eigenstate) + `key_moments.jsonl`; **v2**: `list_key_moments(session_id)` filtering support |
| `adapters/memory/in_memory_entity_registry.py` (`InMemoryEntityRegistry`) | `EntityRegistry` | L1 (alias exact, case-insensitive) + L2 (pure-Python cosine ≥ 0.85) + L3 (create new); thread-safe with Lock; `clear()`/`count()` test helpers |
| `adapters/memory/postgres_entity_registry.py` (`PostgresEntityRegistry`) | `EntityRegistry` | Same L1/L2/L3 over `agent_N.entities` + `agent_N.entity_aliases`; `halfvec` cosine for L2; psycopg3 guarded import |
| `adapters/memory/in_memory_entity_stance.py` (`InMemoryEntityStanceStore`) | `EntityStanceStore` | supersession chain; thread-safe |
| `adapters/memory/postgres_entity_stance.py` (`PostgresEntityStanceStore`) | `EntityStanceStore` | supersession chain in `agent_N.entity_stance`; serial_id resolution per agent; psycopg3 |
| `adapters/memory/in_memory_memory_guardian.py` (`InMemoryMemoryGuardian`) | `MemoryGuardian` | scan_orphan_entities + scan_merge_candidates + scan_stale_moments + scan_embedding_gaps + finding lifecycle (write/get_unresolved/resolve) |
| `adapters/memory/noop_reranker.py` (`NoOpReranker`) | `MemoryReranker` | passthrough — returns candidates sorted by existing score; deploy without reranker model |
| `adapters/memory/bge_reranker.py` (`BgeReranker`) | `MemoryReranker` | `BAAI/bge-reranker-v2-m3` via FlagEmbedding; lazy load; guarded imports; transparent fallback to original score order on inference failure |
| `adapters/linguistic/noop_adapter.py` (`NoOpLinguisticAnalyzer`) | `LinguisticAnalyzer` | returns empty-but-valid analysis objects; default when `LINGUISTIC_ENABLED=false` |
| `adapters/linguistic/gliner_minilm_adapter.py` (`GLiNERPlusMiniLMAdapter`) | `LinguisticAnalyzer` | GLiNER (`urchade/gliner_multi-v2.1`) + MiniLM NLI (`MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli`); lazy model load; guarded imports; Russian divergence heuristics; requires `pip install -e ".[linguistic]"`; **opt-2**: session-scoped SHA-256 cache on `analyze_user_message()` — repeated mentions skip GLiNER+MiniLM inference; `clear_session_cache()` called by runner on session end |
| `adapters/maintenance/in_memory_queue.py` (`InMemoryMaintenanceQueue`) | `MaintenanceQueue` | run_key idempotency; atomic `claim_batch`; all status transitions |
| `adapters/maintenance/postgres_queue.py` (`PostgresMaintenanceQueue`) | `MaintenanceQueue` | SKIP LOCKED `claim_batch` via CTE on `public.maintenance_jobs`; run_key idempotency; psycopg3 |
| `adapters/linguistic/mrebel_adapter.py` (`MRebelRelationAdapter`) | `EntityRelationExtractor` | `Babelscape/mrebel-large` via transformers `text2text-generation`; lazy load; REBEL triplet parser; guarded imports |
| `adapters/reflection/state_store_session_repository.py` (`StateStoreSessionRepository`) | `SessionRepository` | thin adapter over any `StateStore` (InMemory / File / Postgres v2); default `agent_id` constructor slot for single-agent deployments + explicit three-arg form for multi-agent registries; foundation for R3+R4 (Daily/Deep reflection migration) |
| `adapters/storage/in_memory_reflection_store.py` | `PatternStore`, `ReflectionEventStore`, `HealthAssessmentStore` | reflection output stores |
| `adapters/storage/in_memory_self_applied_changes.py` (R11.5) | `SelfAppliedChangeStore` | append-only audit; supports revert by walking back to before-snapshot |
| `adapters/storage/postgres_self_applied_changes.py` (R11.5) | `SelfAppliedChangeStore` | `agent_{N}.self_applied_changes`; bound to one `agent_id` at construction |
| `adapters/storage/in_memory_pending_human_review.py` (R11.7) | `PendingHumanReviewInbox` | priority-first / oldest-first ordering; resolution sets resolved_at + applied_change_id |
| `adapters/storage/postgres_pending_human_review.py` (R11.7) | `PendingHumanReviewInbox` | `agent_{N}.pending_human_review`; enqueues `agent_id` into `context` |
| `reflection/store.py` (`ReflectionStore`) | — | PostgreSQL `agent_{N}.reflections` via `AgentSchemaResolver` (no RLS) |
| `adapters/storage/postgres_agent_schema.py` | — | `agent_id` → `agent_{serial_id}` schema resolution for subjective Postgres adapters |
| `adapters/storage/in_memory_reflection_request_queue.py` (R12) | `ReflectionRequestQueue` | idempotent within UTC hour bucket via `agent_driven_run_key(reason, hour)` |
| `adapters/observability/in_memory_overload_alert_sink.py` (R13) | `ReflectionOverloadAlertSink` | captures alerts in-memory; sink failures suppressed so monitor cannot crash callers |
| `adapters/agent/pending_reviews_context.py` (R11.7) | — | `format_pending_reviews_block` helper: priority-first, oldest-first, context truncation |
| **`adapters/state/postgres_state_store.py`** (`PostgresStateStore`) | **`StateStore`** | **PostgreSQL v2** — per-agent schemas (`agent_N.sessions`, `agent_N.key_moments`); full Session API (`create_session`, `get_session`, `update_session`, `list_recent_sessions`) and v2 KeyMoment API (`create_key_moment`, `store_key_moment` upsert, `mark_moment_accessed`, `update_moment_structured_markers`, `find_moments_by_entity`); schema resolution via fixed `serial_id` or cached `public.agents` lookup; Identity/Narrative/Eigenstate still `NotImplementedError` (served by `FileStateStore`) |
| **`adapters/storage/in_memory_postgres_reflection_store.py`** (`InMemoryReflectionStore`) | **`ReflectionStore`** | **E27**: in-memory with BIGSERIAL + RLS simulation |
| `adapters/storage/reflection_persistence_helper.py` | — | **E27**: helper functions for persisting reflections (`persist_micro_reflection`, `persist_daily_reflection`, `persist_deep_reflection`) |
| `adapters/reflection/mock_reflection_model.py` (`MockReflectionModel`) | `ReflectionModel` | deterministic mock |
| **`adapters/reflection/openai_reflection_model.py`** (**`OpenAIReflectionModel`**) | **`ReflectionModel`** | **Generic OpenAI-compatible adapter** with `OpenAILLMConfig` (base_url, api_key, model, timeout, configurable retries); **`adapters/reflection/__init__.py`** exports **`get_reflection_model()`** factory (env `ATMAN_REFLECTION_BACKEND=openai|anthropic|mock`, default: `openai`) |
| `adapters/reflection/fixture_loader.py` | — | load fixtures for demos |
| `adapters/agent/config.py` (`ModelConfig`, `AgentConfig`) | — | Pydantic AI model + agent runtime config: context window limits, session timeout, free-time toggle, monologue visibility, **memory injection mode** (`assistant_message`/`user_message`/`system_prompt` for universal memory context delivery) (E22.1, E26-R1, E26-R2, E26-R4); **opt-2**: `rag_token_budget` (default 2000 tokens), `enable_prompt_caching` (stable/dynamic context split), `max_moments_per_reflection` (default 30) |
| `adapters/agent/deps.py` (`AtmanDeps`, `AtmanDeps.from_config`) | — | frozen DI container wiring `SessionManager`, `IdentityService`, `ExperienceService`, `MicroReflectionService`, `StateStore`; `from_config` factory transfers validated limits from `AgentConfig`; optional `injected_context` field for `system_prompt` injection mode; **R11.7/R12** optional `pending_review_inbox` and `reflection_request_queue` fields gating tool registration; **opt-2** optional `passive_memory_injector` field; **WP-08 v2** optional `skill_manager: SkillManagerPort | None = None` |
|| `adapters/agent/memory_injection.py` (`inject_memory`, `MemoryInjectionMode`) | — | Universal memory injection with three modes: (1) `assistant_message` — inserts `ModelResponse` at history start (default; OpenAI/Ollama compatible), (2) `user_message` — wraps memory as user turn (Anthropic-compatible), (3) `system_prompt` — sets `deps.injected_context` for `build_instructions` to append (legacy pydantic-ai system-prompt path) |
| `adapters/agent/instructions.py` (`build_instructions`, `build_memory_context`) | — | `build_instructions`: builds behavioral rules (how agent uses tools, commitments); identity/narrative moved to `build_memory_context()` for delivery via `inject_memory()`; when `memory_injection_mode == "system_prompt"`, appends `deps.injected_context`; **WP-08 v2**: `_build_pinned_skills_section(deps)` injects pinned skills list when `deps.skill_manager` is not None; `_build_self_awareness_section(deps)` injects Atman self-description (memory, skills, reflection); errors are caught → empty string fallback |
| `adapters/agent/tools.py` (`record_key_moment` async, `log_experience`, `restart_session`, `wait_session`, `resolve_pending_review`, `request_reflection`) | — | Pydantic AI tools: `record_key_moment` → `AffectDetector.submit_self_report` when `SessionManager` is configured with affect; `log_experience` redirect stub; `restart_session` / `wait_session` return sentinel strings for session control (E22.4); **R11.7** `resolve_pending_review` → `PendingHumanReviewInbox.resolve` (registered only when inbox is wired); **R12** `request_reflection` → `ReflectionRequestQueue.enqueue` with idempotent hour-bucket key (registered only when queue is wired) |
| `adapters/agent/factory.py` (`build_deps`) | — | Assembles `AtmanDeps`, `SessionManager`, `FileStateStore`, services, optional `AffectDetector` from workspace + `AgentConfig`; bootstraps missing identity/narrative for new runner workspaces and wires `SessionManager(workspace=...)` so crash journals are active; **opt-2**: conditionally instantiates `PassiveMemoryInjector` (embedding + factual_memory + state_store + zero-dep `BM25EmbeddingAdapter` for RRF fusion) when `ATMAN_LINGUISTIC_ENABLED=true`; failure is non-fatal (logs warning, RAG stays disabled); **WP-08 v2**: if `settings.skills.enabled`, builds `PostgresSkillStore` → `SkillRetriever` → `SkillManager` and passes to `AtmanDeps`; any exception → `skill_manager=None` (non-fatal fallback) |
| `adapters/agent/runner.py` (`AtmanRunner`, `chat`, `_force_finish`, `_check_restart_requested`, `_do_restart`, `_build_restart_package`, `_check_token_usage`, `_start_stdin_reader`, `_stop_stdin_reader`, `_handle_menu_mode`, `_handle_free_time_mode`) | — | Signal-aware session lifecycle wrapper with restart loop, token monitoring, and timeout/menu (E22.2, E22.3, E22.5, E22.6); token monitoring: progressive warnings at 70/80/90%, force-close at 95% (`_check_token_usage`); queue-based stdin reader (no race on timeout); restart detection: sentinel → finish session with `close_reason="restart"` → build package (key moments + reason + tail) → new session with updated `AtmanDeps`; session timeout → menu mode (reflect/wait/sleep/save_to_memory/free_time); SIGTERM/KeyboardInterrupt/EOFError/SystemExit → graceful `_force_finish()`; creates minimal `KeyMoment` if empty; preserves exit codes; **R11.7** at session start surfaces top unresolved `PendingHumanReviewInbox` items as the first system message and conditionally registers `resolve_pending_review` / `request_reflection` tools when their backing dependencies are present in `AtmanDeps`; **opt-2**: initialises `SessionWorkingMemory` + `SessionCache` per session; calls `surface_for_context()` + `build_rag_context(budget=rag_token_budget)` before each `agent.run()`; clears all session caches in `finally` block; calls `la.clear_session_cache()` on `LinguisticAnalyzer` if present |
| `agents_registry.py` (`AgentsRegistry`) | — | PostgreSQL-backed registry of agent instances (app/admin DB URLs); used by `src/run_agent.py` |

### 1.5b. Optional local coding agent (**not** in core wheel — `atman_agent_cli/`)

| Path | Notes |
|------|--------|
| `atman_agent_cli/src/atman/agent_cli/` | Coding-agent Textual/RAG surface layered on adapters when wired. Sources live beside core; Hatch ships only [`src/atman`](#). Use `PYTHONPATH=atman_agent_cli/src:src`, `pip install -e ".[agent-cli]"`; prep tooling `scripts/agent_cli/`, docs `atman_agent_cli/RUNBOOK.md`. Listed core namespaces must not import **`atman.agent_cli`** — **`.importlinter` contract `no-core-to-optional-agent-cli`**. |

### 1.5c. Skills package (`src/atman/skills/`, WP-08 v2)

Fully optional, disableable via `atman.skills.enabled = false`. Only imported from `factory.py` (conditionally) and CLI — no global side-effects anywhere else.

| File | Purpose | Public surface |
|------|---------|----------------|
| `skills/__init__.py` | Public re-exports | `Skill`, `SkillInvocation`, `SkillKind`, `SkillOrigin`, `SkillStatus`, `SkillSuggestion`, `SkillManagerPort`, `NoopSkillManager`, `SkillsDisabledError` |
| `skills/models.py` | Domain models (frozen dataclasses + StrEnums) | `SkillKind`, `SkillStatus`, `SkillOrigin`, `Skill`, `SkillInvocation`, `SuggestionStrength`, `SkillSuggestion`; `Skill.is_pinned`, `Skill.description_short` properties |
| `skills/manifest.py` | SKILL.md parser and writer (YAML frontmatter + markdown body) | `SkillManifest`, `parse_skill_md(path) -> SkillManifest`, `write_skill_md(manifest, path)` |
| `skills/port.py` | `SkillManagerPort` Protocol (runtime_checkable) | `SkillManagerPort`: 8 methods — `list_pinned`, `list_available`, `trigger_router`, `invoke`, `mark_result`, `capture`, `get_skill`, `process_session_skills` |
| `skills/noop.py` | Silent no-op implementation for disabled mode | `SkillsDisabledError`, `NoopSkillManager` (read-only methods return empty; write methods raise `SkillsDisabledError`; `process_session_skills` is silent no-op) |
| `skills/store.py` | `SkillStore` Protocol — storage interface | `SkillStore`: `save_skill`, `get_skill_by_name`, `get_skill_by_id`, `list_pinned`, `list_by_status`, `list_active_on_demand`, `update_skill_status`, `update_pinning`, `update_stats`, `bump_sessions_since_use`, `set_revision_needed`, `reset_sessions_since_use`, `create_invocation`, `set_preliminary_status`, `write_agent_marker`, `append_behavioral_hint`, `append_user_feedback_hint`, `get_unprocessed_invocations`, `set_final_status`, `mark_processed` |
| `skills/in_memory_store.py` | In-memory `SkillStore` implementation (tests) | `InMemorySkillStore` |
| `skills/postgres_store.py` | PostgreSQL `SkillStore` over `public.skills` + `public.skill_invocations` (psycopg3 + dict_row + RLS) | `PostgresSkillStore` |
| `skills/retriever.py` | Skill trigger router: keyword match + embedding cosine similarity | `SkillRetriever.suggest(message, agent_id, session_id) -> list[SkillSuggestion]`; `_cosine_similarity(a, b)`; reads `SKILL.md` for per-skill `min_confidence` and `triggers_keywords`; substring match for Cyrillic morphology |
| `skills/projection.py` | `ProjectionAdapter` Protocol + no-op MVP | `ProjectionAdapter`, `PydanticAgentProjector` (no-op: skills registered via tools, not filesystem) |
| `skills/manager.py` | Real `SkillManager` implementation | `SkillManager`: full lifecycle — invoke (subprocess entry script, preliminary_status), mark_result, capture (creates SKILL.md + entity + row), `process_session_skills` (finalise invocations, update stats, auto-pin/downgrade, mark processed) |
| `skills/agent_tools.py` | 4-tool Pydantic AI API for agent skill interaction | `make_skill_tools(skill_manager, agent_id, session_id) -> list` — returns 4 tools: `atman_skills_list_available`, `atman_skills_invoke`, `atman_skills_mark_result`, `atman_skills_capture`; returns `[]` if `skill_manager` is None |
| `skills/cli.py` | CLI skill management (entry point `atman-skills`) | `list`, `show`, `disable`, `enable`, `pin`, `unpin`, `archive`, `inspect-invocations`, `force-revise`; read-only commands work when `enabled=false` |

**DB migration**: `migrations/versions/0015_skills.sql` — `public.skills` (RLS by `agent_id`, indexes on status + pinning) + `public.skill_invocations` (RLS, partial index on `processed_at IS NULL`); always created regardless of `skills.enabled`.

### 1.6. CLI / TUI / Web / Demos

| File | Category | Purpose |
|------|----------|---------|
| `cli.py` | CLI | Factual memory REPL |
| `cli_experience.py` | CLI | Experience Store |
| `cli_maintenance.py` | CLI | Maintenance queue: `run` (claim+dispatch batch), `list` (show jobs), `enqueue` (schedule job); subcommands `run`, `list`, `enqueue`; entry point `atman-maintenance` |
| `src/atman/skills/cli.py` | CLI | Skill management: `list`, `show`, `disable`, `enable`, `pin`, `unpin`, `archive`, `inspect-invocations`, `force-revise`; read-only commands work when `skills.enabled=false`; entry point `atman-skills` |
| `cli_identity.py` | CLI | Identity Store |
| `cli_reflection.py` | CLI | Reflection Engine (micro/daily/deep) |
| `term.py` | utility | Rich output for CLI/demos |
| `tui/app.py` | TUI | Textual app entrypoint (Tests / Features / Docs) |
| `tui/tests_tab.py`, `tui/features_tab.py`, `tui/docs_tab.py` | TUI | tabs |
| `tui/features_registry.py` | TUI | feature registry |
| `tui/pytest_utils.py`, `tui/runner.py`, `tui/repo_root.py` | TUI | subprocess + repo root detection |
| `web_dashboard/app.py` | web | Streamlit home page |
| `web_dashboard/pages/1_Tests.py`, `web_dashboard/pages/2_Docs.py` | web | Streamlit pages |
| `web_dashboard/utils/cmd.py`, `web_dashboard/utils/runner.py` | web | subprocess helpers |
| `src/demo.py` | demo | factual memory demo |
| `src/demo_experience_store.py` | demo | Experience Store walkthrough |
| `src/demo_identity.py` | demo | identity bootstrap + narrative render |
| `src/demo_session_manager.py` | demo | session lifecycle: start, record events/key moments, finish with eigenstate |
| `src/demo_reflection.py` | demo | micro→daily→deep with fixtures |
| `src/demo_full_corpus.py` | demo | all `e2e/fixtures/sessions/*` → SessionManager → micro/daily/deep + Rich summary ([issue #158](https://github.com/hleserg/atman/issues/158)) |
| `src/demo_web_dashboard.py` | demo | web dashboard launch hint |
| `src/demo_eval_runner.py` | demo | E1 Evaluation Runner walkthrough: registry list → RunnerCore + JsonlReporter → noop benchmark → idempotent rerun |
| `src/run_agent.py` | entrypoint | Agent REPL via `AgentsRegistry` + `AtmanRunner` (`DATABASE_URL` from env / `.env`) |
| `agent/atman_agent.py`, `agent/config.py` | test agent | Pydantic AI test-user factory (`create_agent`) with OpenAI-compatible provider config (`AgentLLMConfig`); packaged in wheels via Hatch |
| `scripts/migrate_embeddings.py` | ops | PostgreSQL facts embedding migration from 2560-dim Qwen vectors to 1024-dim BGE-M3; rebuilds `facts.embedding` schema/index and re-embeds inside one transaction |
| `e2e/generate_fixtures.py` | e2e | LLM-backed session JSON fixture generator (`python -m e2e.generate_fixtures`); default 20 `en/` + 20 `ru/` corpora with parallel locale runs; Anthropic tool_use, two-pass skeleton + per-session; `--corpus-policy strict|soft`, `--max-corpus-regen N` (strict tail cap); optional extra `[e2e]`; manual/secret-gated automation candidate ([issue #141](https://github.com/hleserg/atman/issues/141)) |
| `e2e/models.py`, `e2e/validation.py`, `e2e/llm.py`, `e2e/prompts.py` | e2e | fixture schema, intra/cross-session validators, API orchestration, prompts |
| `e2e/full_loop.py`, `e2e/__main__.py` | e2e | integration driver over WP-01..05 with session JSON fixtures (`python -m e2e`); optional/manual and suitable for a targeted GitHub Actions smoke job |
| `e2e/scenarios/value_drift_under_pressure.py` | e2e/demo | deterministic E2E scenario for atmanai.dev/demo.html: bootstraps identity with honesty principle, runs Session 1 (value drift + self-correction), micro+daily reflection, identity update, Session 2 (same pressure, clean alignment); writes 11 JSON snapshots to `docs/demo-data/`; `make demo-e2e-scenario` |
| `e2e/scenarios/session_lifecycle_interrupt.py` | e2e | interrupted session & journal recovery: KeyboardInterrupt / SIGTERM / crash, orphaned journal detection, idempotent recovery on next start_session() |
| `e2e/scenarios/session_lifecycle_restart.py` | e2e | context limit & session restart: 70% warning, restart_session(reason=...), new session with restart package |
| `e2e/scenarios/session_lifecycle_timeout.py` | e2e | timeout & free time menu: user inactivity, system-injected free time menu, agent selects command (sleep/reflect/exit) |
| `docs/demo-data/` | website data | 11 JSON files generated by `make demo-e2e-scenario`; consumed by `docs/demo.html` static timeline |
| `docs/demo.html` | website | static E2E walkthrough page; 11-step timeline; bilingual EN/RU; loads JSON from `docs/demo-data/`; no build step, no React |

### 1.7. Evaluation subsystem (`src/atman/eval/`, `eval/`, `scripts/eval/`)

| Path | Category | Purpose |
|------|----------|---------|
| `src/atman/eval/__init__.py` | optional namespace | imports `_deps_check`; `import atman.eval` fails fast without the `eval` extra |
| `src/atman/eval/_deps_check.py` | dependency guard | checks canary deps from `[project.optional-dependencies].eval` and returns a friendly install hint |
| `src/atman/eval/benchmark_runner.py` | CLI module | E1 benchmark runner CLI entrypoint with `list`/`run`; `python -m atman.eval.benchmark_runner list` / `python -m atman.eval.benchmark_runner run <key>` |
| `src/atman/eval/runner_core.py`, `src/atman/eval/run_context.py` | eval runtime | benchmark lifecycle, typed run context, deterministic app-level idempotency keys that include execution-affecting seed, reporter fanout (`on_run_start/on_run_item/on_run_complete`) |
| `src/atman/eval/registry.py`, `src/atman/eval/benchmarks/noop.py` | benchmark registry | decorator-based benchmark registration and lookup (`register`, `get`, `list_benchmarks`) with builtin noop smoke benchmark |
| `src/atman/eval/reporters/base.py`, `src/atman/eval/reporters/jsonl_reporter.py`, `src/atman/eval/reporters/db_reporter.py` | reporting | Reporter ABC + JSONL lifecycle events + PostgreSQL writes to `eval.benchmark_runs` / `eval.run_items` |
| `src/atman/eval/seed_manager.py`, `src/atman/eval/hardware.py` | runtime metadata | deterministic seed management and hardware probe with graceful fallback without NVML/GPU |
| `eval/migrations/alembic.ini`, `eval/migrations/env.py` | eval storage | Alembic configuration for the isolated PostgreSQL `eval` schema |
| `eval/migrations/versions/0010_*` ... `0040_*` | eval storage | idempotent eval schema, benchmark run tables, supporting tables, and trend materialized view |
| `scripts/eval/partition_manager.py` | operations | creates future partitions, detaches old partitions, and reports `eval.benchmark_runs` partition status |
| `scripts/eval/eval_linguistic_quality.py` | offline eval | NER + classification quality eval: 23 NER examples (Russian persons/orgs/places/topics/health), 5 classification examples; computes precision/recall/F1 and accuracy; `--adapter gliner|noop`, `--verbose`; exit 1 on FAIL; target: NER F1 ≥ 0.65, classification accuracy ≥ 0.70 |
| `src/demo_eval_runner.py`, `docs/features/eval-runner/README.md`, `docs/features/eval-runner/README-ru.md` | demo/docs | reproducible E1 runner walkthrough + bilingual usage docs |

---

## 2. Integrations

Connections between two or more parts. These are seams that may break independently of the underlying logic.

### 2.1. Service ↔ port

| Connection | Files | Type |
|-----------|-------|------|
| `ExperienceService` ↔ `StateStore` | `core/services/experience_service.py` → `core/ports/state_store.py` | DI |
| `IdentityService` ↔ `StateStore` | `core/services/identity_service.py` → `core/ports/state_store.py` | DI |
| `NarrativeService` ↔ `StateStore` | `core/services/narrative_service.py` → `core/ports/state_store.py` | DI |
| `SessionManager` ↔ `StateStore` | `core/services/session_manager.py` → `core/ports/state_store.py` | loads identity/narrative at start; `IdentitySnapshot` on start; deterministic `SessionExperience.id` (uuid5 of `session_id`) for idempotent `finish_session`; active journals hold an advisory lock so another `SessionManager` does not recover a live session; session journals include full `KeyMoment` payloads and finish-time metadata (tone, insight, alignment) so orphan recovery can restore missing moment rows and rebuild downstream artifacts without losing the original finish summary; if a crash happens after experience persistence but before eigenstate/narrative writes, recovery completes the missing finish artifacts before deleting the journal; `finish_session` calls `get_key_moment` + `create_key_moment` per moment for idempotent retry; computes `unexamined_fact_refs` (facts in `_facts_read` but not in any key moment `fact_refs`); eigenstate load scoped by `identity_id`; recent narrative update uses `save_narrative(..., expected_updated_at=...)` |
| `NarrativeRevisionService` ↔ `NarrativeRepository` | `core/services/narrative_revision.py` → `core/ports/reflection.py` | optimistic locking |
| `IdentityService` ↔ `SelfAppliedChangeStore` | `core/services/identity_service.py` → `core/ports/self_applied_changes.py` | **R11.5** audit append on every `apply_self_change`; revert reads `before_snapshot` |
| `NarrativeRevisionService` ↔ `SelfAppliedChangeStore` | `core/services/narrative_revision.py` → `core/ports/self_applied_changes.py` | **R11.5** audit append for `apply_self_layer_update` / `revert_self_change` |
| `resolve_pending_review` ↔ `PendingHumanReviewInbox` | `adapters/agent/tools.py` → `core/ports/pending_human_review.py` | **R11.7** tool registered only when inbox is in `AtmanDeps`; runner injects unresolved items as first system message |
| `request_reflection` ↔ `ReflectionRequestQueue` | `adapters/agent/tools.py` → `core/ports/reflection_request_queue.py` | **R12** tool registered only when queue is in `AtmanDeps`; idempotent via `agent_driven_run_key` (UTC hour bucket) |
| `MicroReflectionService` ↔ `SessionRepository` + `NarrativeRepository` | `core/services/reflection_service.py` | reads one session + its key moments, synthesises a virtual `SessionExperience` via `services/session_experience_view.build_session_experience`, updates recent layer (R-Micro — migrated off `ExperienceRepository`) |
| `MicroReflectionService` ↔ `SkillManagerPort` | `core/services/reflection_service.py` | **WP-08 v2** optional hook: if `skill_manager` and `agent_id` are set, calls `process_session_skills(agent_id, session_id)` after narrative update; errors suppressed so reflection cannot be blocked by skill failures |
| `DailyReflectionService` ↔ `SessionRepository` + `PatternStore` + `ReflectionEventStore` | `core/services/reflection_service.py` | pattern detection (R3 — migrated off `ExperienceRepository`; synthesises virtual `SessionExperience` via `services/session_experience_view.build_session_experience`) |
| `DeepReflectionService` ↔ `SessionRepository` + `IdentityRepository` + `NarrativeRepository` + `PatternStore` + `HealthAssessmentStore` + `ReflectionEventStore` | `core/services/reflection_service.py` | health + identity + narrative update (R4 — migrated off `ExperienceRepository`; synthesises virtual `SessionExperience` via `services/session_experience_view.build_session_experience`) |
| `PrincipleRevisionAdvisor` ↔ `PatternCandidate` + `Identity` | `core/services/principle_advisor.py` | analyzes patterns in identity context |
| `ConflictDetector` ↔ `FactualMemory` | `core/services/conflict_detector.py` → `core/ports/memory_backend.py` | DI; lightweight contradiction scan over ACTIVE candidates returned by `search()` |
| `EmotionalEcho` ↔ `StateStore` | `core/services/emotional_echo.py` → `core/ports/state_store.py` | DI; `lookback_days` window via `search_experiences` |
| `PassiveMemoryInjector` ↔ `EmbeddingPort` + `FactualMemory` + `StateStore` + optional `LinguisticAnalyzer` + `MemoryReranker` + optional second `EmbeddingPort` for BM25 | `core/services/passive_memory_injector.py` → `core/ports/embedding.py`, `core/ports/memory_backend.py`, `core/ports/state_store.py`, `core/ports/linguistic.py`, `core/ports/memory_reranker.py` | DI; salience-ordered candidate pool (`query=None` to backend) → dense similarity → optional BM25 RRF fusion → optional reranker → 1-hop associative expansion with real similarity scores; optional `SessionWorkingMemory` cache |
| `MaintenanceWorker` ↔ `MaintenanceQueue` + `SalienceDecayService` + `MemoryGuardian` | `core/services/maintenance_worker.py` → `core/ports/maintenance_queue.py`, `core/ports/salience_decay.py`, `core/ports/memory_guardian.py` | DI; `run_once()` claims batch and dispatches jobs |
| `DivergenceDetector` ↔ `AgentMessageAnalysis` | `core/services/divergence_detector.py` | stateless; maps signal labels from analysis to `DivergenceEvent` list |
| `KeyMomentBuilder` ↔ `KeyMomentInput` + `KeyMomentAnalysis` | `core/services/key_moment_builder.py` | stateless; populates `structured_markers` from analysis |

### 2.2. Adapter ↔ port

| Adapter | Implements |
|---------|------------|
| `InMemoryBackend`, `FileBackend`, `PostgresFactualMemory` | `FactualMemory` |
| `InMemoryExperienceStore`, `JsonlExperienceStore`, `FileStateStore`, `InMemoryStateStore`, `PostgresStateStore` | `StateStore` |
| `MockReflectionModel`, **`OpenAIReflectionModel`** | `ReflectionModel` |
| `InMemoryPatternStore`, `InMemoryReflectionEventStore`, `InMemoryHealthAssessmentStore` | corresponding ports |
| `MockEmbeddingAdapter`, `BM25EmbeddingAdapter`, `OllamaEmbeddingAdapter`, `FlagEmbeddingAdapter` | `EmbeddingPort` |
| `InMemoryUsageLog` | `MemoryUsageLog` |
| `InMemoryReflectionStore` (`adapters/storage/in_memory_postgres_reflection_store.py`) | `ReflectionStore` (E27) |
| `InMemoryEntityRegistry`, `PostgresEntityRegistry` | `EntityRegistry` |
| `InMemoryEntityStanceStore`, `PostgresEntityStanceStore` | `EntityStanceStore` |
| `InMemoryMemoryGuardian` | `MemoryGuardian` |
| `NoOpLinguisticAnalyzer`, `GLiNERPlusMiniLMAdapter` | `LinguisticAnalyzer` |
| `NoOpReranker`, `BgeReranker` | `MemoryReranker` |
| `InMemoryMaintenanceQueue`, `PostgresMaintenanceQueue` | `MaintenanceQueue` |
| `MRebelRelationAdapter` | `EntityRelationExtractor` |
| `StateStoreSessionRepository` (`adapters/reflection/`) | `SessionRepository` (R1 — successor to ExperienceRepository) |
| `InMemorySkillStore` (`skills/in_memory_store.py`), `PostgresSkillStore` (`skills/postgres_store.py`) | `SkillStore` (WP-08 v2) |
| `NoopSkillManager` (`skills/noop.py`), `SkillManager` (`skills/manager.py`) | `SkillManagerPort` (WP-08 v2) |

### 2.2a. Agent adapter ↔ services

| Connection | Files | Type |
|-----------|-------|------|
| `AtmanDeps` ↔ `SessionManager`, `IdentityService`, `ExperienceService`, `MicroReflectionService`, `StateStore` | `adapters/agent/deps.py` | DI container (frozen dataclass); optional `injected_context` for `system_prompt` memory injection mode; **WP-08 v2** optional `skill_manager: SkillManagerPort | None` |
| `record_key_moment` / `log_experience` / `restart_session` / `wait_session` ↔ `AffectDetector.submit_self_report` / `SessionManager` | `adapters/agent/tools.py` → `affect/detector.py` + `core/services/session_manager.py` | Async Pydantic AI tools → affect write gateway (`record_key_moment` requires `affect_workspace` + config on `SessionManager`; `restart_session` / `wait_session` return sentinel strings for E22.5 runner detection) |
| `build_instructions` / `build_memory_context` / `inject_memory` ↔ `StateStore.load_identity` / `load_narrative` | `adapters/agent/instructions.py`, `adapters/agent/memory_injection.py` → `core/ports/state_store.py` | Dynamic system-prompt builder + memory context builder + universal injection (three modes: `assistant_message` / `user_message` / `system_prompt`) |
| `chat` / `_force_finish` / `_do_restart` / `_handle_menu_mode` / `_handle_free_time_mode` ↔ `SessionManager` | `adapters/agent/runner.py` → `core/services/session_manager.py` | Signal handler registration + exception boundary + restart loop + timeout/menu (E22.2, E22.5, E22.6, E22.7); calls `append_key_moment_input()`, `get_active_session()`, `finish_session(..., close_reason=...)` on interruption and restart; restart workflow: finish session with `close_reason="restart"`, build package, start new session, update `AtmanDeps` with new `session_id`; wake-up message injection from last session's `close_reason`; timeout → menu mode (reflect/wait/sleep/save_to_memory/free_time); `AtmanRunner.chat()` installs SIGTERM shutdown into the async input queue |

### 2.3. CLI ↔ service

| CLI | Wiring | File |
|-----|--------|------|
| `cli.py` | `build_memory_backend()` factory (`FileBackend` by default, env-selectable `postgres|file|inmemory`) | `config.py`, `cli.py` |
| `cli_experience.py` | `ExperienceService(JsonlExperienceStore)` | `cli_experience.py:17-29` |
| `cli_identity.py` | `IdentityService(FileStateStore)` + `NarrativeService(FileStateStore)` | `cli_identity.py:15-29` |
| `cli_reflection.py` | `Micro/Daily/DeepReflectionService` + fixture_loader | `cli_reflection.py:18-47` |
| `benchmark_runner.py` (module-only) | `RunnerCore` + `registry` + `reporters` (`jsonl`, optional DB) | `eval/benchmark_runner.py` |

### 2.4. Demo ↔ real objects

| Demo | Chain |
|------|-------|
| `demo.py` | `InMemoryBackend` + `FileBackend` for `FactualMemory` |
| `demo_experience_store.py` | `JsonlExperienceStore` → `ExperienceService` |
| `demo_identity.py` | `FileStateStore` → `IdentityService` + `NarrativeService` |
| `demo_session_manager.py` | `FileStateStore` → `SessionManager` (loads identity/narrative, records events/moments, stores experience/eigenstate) |
| `demo_reflection.py` | mocks + fixture_loader → `MicroReflectionService` → `DailyReflectionService` → `DeepReflectionService` |
| `demo_full_corpus.py` | `e2e` session JSON → `FileStateStore` + `SessionManager` + `StateStore*Adapter` → micro → daily (per UTC day) → deep; `DeterministicReflectionModel` |
| `demo_eval_runner.py` | `list_benchmarks()` → `RunnerCore([JsonlReporter])` + `noop` benchmark → idempotent rerun with same `git_sha` → JSONL artifact |

### 2.5. TUI / Web ↔ subprocesses

| Component | Integration |
|-----------|-------------|
| `tui/tests_tab.py` | runs pytest as subprocess |
| `tui/features_tab.py` | runs demos as subprocesses via `features_registry.FEATURES` |
| `web_dashboard/app.py` | runs demos as subprocesses, uses `FEATURES` |

### 2.6. Reflection service chain

```text
session ends
  ↓
MicroReflectionService — reads one session + its key moments via SessionRepository
  ↓ updates
NarrativeRepository (recent layer) — optimistic locking
  ↓
DailyReflectionService — reads sessions + key moments via SessionRepository for the UTC day, detects patterns
  ↓ stores
PatternStore + ReflectionEventStore
  ↓
DeepReflectionService — reads sessions + key moments via SessionRepository, assesses health,
  updates identity and narrative (with governance)
  ↓ proposes
PrincipleRevisionAdvisor — principle revision
```

### 2.7. parser ↔ model and reflection ↔ identity update

- `adapters/storage/jsonl_experience_store.py:_read_all_experiences()` — JSONL → `ExperienceRecord.model_validate(...)`.
- `adapters/memory/file_backend.py:_read_facts_from_disk()` — JSONL → `FactRecord.model_validate(...)`.
- `DeepReflectionService` → `IdentityService.update_*` with `IdentitySnapshot` creation (idempotent via `reflection_run_key`).

---

## 3. User scenarios

### A. Bootstrap a new agent

Files: `docs/features/identity-store/`, `src/demo_identity.py`, `cli_identity.py`.

1. `IdentityService.bootstrap_identity(agent_id)`.
2. An honestly empty `Identity` is created with open questions.
3. The first `IdentitySnapshot` is created with description "Bootstrap".
4. `python -m atman.cli_identity` displays the identity.

### B. Record experience after a session

Files: `docs/features/experience-store/`, `src/demo_experience_store.py`, `cli_experience.py`.

1. During session — `KeyMoment` + `FeltSense` (valence, intensity, depth).
2. End of session — `SessionExperience`.
3. `ExperienceService.create_experience(...)` → write to JSONL/memory (immutable).
4. Later — `add_reframing_note(experience_id, ...)`.
5. Search by `values_touched`, depth, or date range.

### C. Micro reflection (after-session)

Files: `docs/features/reflection-engine/`, `src/demo_reflection.py`, `cli_reflection.py`.

1. `MicroReflectionService.reflect_micro(...)` takes recent experience + optional eigenstate.
2. `ReflectionModel` (LLM or mock) generates a summary.
3. Updates `NarrativeDocument.recent_layer` checking `expected_updated_at`.
4. `NarrativeWriteAuditPort` records audit.

### D. Daily — pattern detection

1. `DailyReflectionService.reflect_daily(...)` collects experience for the UTC day.
2. `ReflectionModel` returns `list[PatternCandidate]`.
3. Stored in `PatternStore` + `ReflectionEvent(level=DAILY)`.

### E. Deep reflection + health

1. `DeepReflectionService.reflect_deep(...)`: experience + patterns + identity.
2. Computes Jahoda criteria (autonomy, competence, integration, actualization, aspiration, purpose).
3. `ReflectionModel` proposes narrative changes (core/recent).
4. `IdentitySnapshot` created (idempotent via `reflection_run_key`).
5. Identity updated + narrative proposals + `HealthAssessment`.

### F. Factual memory: record and search

Files: `docs/features/factual-memory/`, `src/demo.py`, `cli.py`.

1. `add "..." session_042 task` — `FactRecord` with UUID.
2. `search --tags task` — filter.
3. `link <id1> <id2> "caused_by"` — relation.
4. Facts are immutable; only relations may be added.

### G. Render NARRATIVE.md

Files: `docs/features/identity-store/`, `src/demo_identity.py`, `cli_identity.py`.

1. `NarrativeService.render_narrative_md(identity_id)`.
2. Three layers: CORE / RECENT / THREADS.
3. First-person style validation.

### H. Session lifecycle with first-hand experience

Files: `docs/features/session-manager/`, `src/demo_session_manager.py`, `tests/test_session_manager.py`.

1. `SessionManager.start_session(agent_id)` → loads identity, narrative, eigenstate → `SessionContext`.
2. During session: `record_event(...)` tracks raw events from lower agent and may schedule **AffectDetector** (optional); **value refusals auto-detected via `RefusalDetectorConfig` and silently recorded as key moments** without agent notification.
3. Programmatic moments: `append_key_moment_input(...)` / `append_key_moment(...)`; agent tool `record_key_moment` → `AffectDetector.submit_self_report(...)` with mandatory emotional coloring (valence/intensity/depth).
4. If coloring incomplete → flag `incomplete_coloring=True` (honest about limitation).
5. `finish_session(...)` → creates `SessionExperience` (`recorded_by="session_manager"`) + `Eigenstate`; accepts optional `close_reason`, `restart_reason`, **`user_language`** for wake-up context on next session start.
6. Both stored via `StateStore` (experience immutable, eigenstate for next session).
7. Key invariant: emotional coloring MUST be present (from real experiencing) or explicitly marked incomplete.
8. `KeyMomentInput.recorded_at` is copied to `KeyMoment.when` so timestamps are stable relative to validation/finish ordering.
9. `finish_session(..., alignment_check=False)` requires non-empty `alignment_notes`.
10. `list_active_sessions()` returns `ActiveSessionSummary` (counts + `started_at`) for sessions not mid-finish.

### I. Full corpus replay (all E2E session fixtures)

Files: `docs/features/full-corpus-demo/`, `src/demo_full_corpus.py`, `e2e/full_loop.py`, `tests/test_demo_full_corpus.py`.

1. `load_all_fixture_sessions_sorted(locale)` orders fixtures by `metadata.session_number`.
2. For each fixture: `FrozenClock` advances one UTC day; `run_session_from_fixture(...)` → experience + eigenstate.
3. `MicroReflectionService.reflect(session_id)` then `DailyReflectionService.reflect(day)` on that calendar day.
4. After the loop: `DeepReflectionService.reflect(since, until)` over the full span.
5. Closing Rich table: bootstrap vs accumulated stores, principle touches, mood samples, patterns, reframing, narrative recent layer ([issue #158](https://github.com/hleserg/atman/issues/158)).

---

## 4. Non-standard inputs (edge cases)

### 4.1. Empty / invalid inputs

| Scenario | Where checked | File |
|----------|---------------|------|
| Empty `FactRecord.content` | `@field_validator` → `ValueError` | `core/models/fact.py:31-37` |
| Empty `Relation.relation_type` | `@field_validator` → `ValueError` | `core/models/fact.py:71-77` |
| Empty `Identity.self_description` | `min_length=1` | `core/models/identity.py:30` |
| `CoreValue.confidence` outside 0..1 | `@field_validator` | `core/models/identity.py:52-58` |
| `FeltSense.emotional_valence` outside -1..+1 | `@field_validator` | `core/models/experience.py:57-67` |
| `KeyMomentInput` with zero valence/intensity without `incomplete_coloring` | `SessionManager.append_key_moment_input` → `ValueError` | `core/services/session_manager.py` |
| Deprecated `SessionManager.record_key_moment(...)` | `AttributeError` (message references `AffectDetector`) | `core/services/session_manager.py` |
| `alignment_check=False` with blank `alignment_notes` | `SessionManager.finish_session` → `ValueError` | `core/services/session_manager.py` |
| Second `finish_session` after successful completion | session removed from active map → `SessionNotFoundError` | `core/services/session_manager.py` |
| Concurrent second `finish_session` while first is persisting | `SessionAlreadyFinishedError` | `core/services/session_manager.py` |
| Active session cap | `SessionManager(..., max_active_sessions=n)` → `TooManyActiveSessionsError` on `start_session` | `core/services/session_manager.py` |
| Invalid UUID in CLI | try/except `UUID(...)` | `cli.py:50-54` |
| Missing experience file | `if not json_file.exists()` | `cli_experience.py:40-43` |
| **GAP**: empty `key_moments` in `SessionExperience` | checked in `SessionManager.finish_session` | `core/services/session_manager.py` |
| **GAP**: empty eigenstate (`open_threads`, `dominant_themes`, `unresolved_tensions`) | default empty list | `core/models/narrative.py:50-59` |

### 4.2. Duplicates / idempotency

| Scenario | Behavior | File |
|----------|----------|------|
| Duplicate fact ID | `ValueError` | `adapters/memory/file_backend.py` |
| Duplicate `triggered_by` for reframing note | returns `DUPLICATE_TRIGGERED_BY` (explicit) | `core/models/experience.py` |
| Duplicate experience on `create_experience` | `ValueError` | `adapters/storage/jsonl_experience_store.py:94` |
| `reflection_run_key` collision | deterministic key; `IdentitySnapshot` created once | `core/reflection_run_keys.py` |

### 4.3. JSON / JSONL parsing

| Location | Error handling |
|----------|----------------|
| `FileBackend._read_facts_from_disk()` | ✅ malformed lines are reported via `warnings.warn(RuntimeWarning, ...)` and skipped (`adapters/memory/file_backend.py`); covered by `tests/test_file_backend.py::test_read_facts_skips_malformed_lines_without_data_loss` |
| `JsonlExperienceStore._read_all_experiences()` | `warnings.warn(...)`, continues (`adapters/storage/jsonl_experience_store.py:57-73`) |
| `FileStateStore.get_experience()` / `load_identity()` / etc. | ✅ `_read_json_file` wraps `json.JSONDecodeError` into `ValueError` with file path + line/column context (`adapters/storage/file_state_store.py`); covered by `tests/test_file_state_store.py::test_get_experience_with_corrupted_json_raises_clear_error` and `test_load_identity_with_corrupted_json_raises_clear_error` |
| `cli_experience.py:cmd_add()` | broad `except Exception` (`cli_experience.py:45-56`) |

### 4.4. Governance and concurrency

| Scenario | Mechanism | File |
|----------|-----------|------|
| Core narrative update requires approval | `GovernanceDecision.allows_core_narrative_commit()` | `core/models/governance.py:36-42` |
| Concurrent narrative writes | optimistic locking on `updated_at` | `core/ports/reflection.py:133-147` |
| Write conflict | `NarrativePersistenceConflictError` | `core/exceptions.py:8-14` |
| Narrative audit failure | nested try/except — narrative committed, audit logged as warning | `core/services/narrative_revision.py:73-88` |

### 4.5. What still needs covering (gaps)

- ✅ Empty `key_moments` list in `SessionExperience` — covered by `tests/test_experience_models.py::test_session_experience_rejects_empty_key_moments` (rejected via `min_length=1`).
- ✅ Malformed JSONL in `FileBackend` — fixed (warn-and-skip) and covered by `tests/test_file_backend.py::test_read_facts_skips_malformed_lines_without_data_loss`.
- ✅ `json.JSONDecodeError` in `FileStateStore` — wrapped via `_read_json_file` with file context; covered in `tests/test_file_state_store.py`.
- `confidence > 0.7` validation for patterns in `PatternStore` — partially covered; range bounds (0..1) frozen by `tests/test_reflection_models.py::test_pattern_candidate_confidence_at_boundary_zero_and_one`. Threshold semantics remain a service-level concern (see `DeepReflectionService._generate_core_content`).
- ✅ Empty eigenstate without context — current behaviour frozen by `tests/test_narrative_models.py::test_eigenstate_with_all_empty_collections_is_explicitly_marked` (intentionally allowed; whitespace-only entries normalised).
- ✅ Concurrent identity writes — covered by `tests/test_file_state_store.py::test_save_identity_concurrent_writers_resolve_to_last_writer` (last-writer-wins is documented behaviour). Concurrent narrative writes still rely on optimistic concurrency at the service layer (see `tests/test_narrative_revision.py`).
- ✅ `GovernanceRejectedError` flow — `LOCKED` mode covered by `tests/test_narrative_revision.py::test_governance_mode_locked_raises_governance_rejected_error` (in addition to existing `AUTO` and unapproved `REVIEW` cases).
- ⏳ **Session Manager: recent narrative unbounded growth** — each `finish_session` appends session summary to `recent_layer.content` without eviction; after many sessions (100+), content may exceed token limits or degrade performance. Requires trim/sliding-window logic. Tracked in issue (to be created).

---

## 5. Known bugs / regressions

### 5.1. From git history (last 50 commits)

| Commit | Topic | Status |
|--------|-------|--------|
| `2271b46`, `5e8d6fd`, `909aa5e` | Code review rounds | closed |
| `12e527f` | pre-commit hook + `pip-audit` scope | closed |
| `15bce2d` | Language switcher in docs site | closed |
| `28a2285` | GitHub Pages artifacts | closed |
| `b530f36` | Relation persistence in `FileBackend` — regression test added | covered (`tests/test_file_backend.py`) |
| `e48a060`, `83df039` | ruff lint/format/type fixes | mostly closed |
| `6a9f28f` | Session Manager recent narrative update replaced the whole recent layer instead of appending; regression test added | covered (`tests/test_session_manager.py::test_finish_session_appends_to_recent_narrative_without_erasing_existing_context`) |
| `0ef0587` | Open WebUI setup exposed first-admin registration to LAN by default | covered (`tests/test_deployment_scripts.py`) |
| `b47abcb` | `eval.benchmark_runs` only created a current-month partition, so inserts with `started_at=NOW()` would fail after the month boundary | covered (`tests/test_eval_migrations.py::test_benchmark_runs_migration_creates_default_partition_safety_net`, `tests/test_eval_migrations.py::test_benchmark_runs_migration_rolls_december_partition_to_next_year`, `tests/test_eval_migrations.py::test_benchmark_runs_sql_mirror_documents_default_partition_safety_net`) |
| current PR | PostgreSQL RLS allowed owner-role bypass for `reflections` and exposed `fact_relations` without RLS | covered (`tests/test_postgres_migration_security.py`) |
| current PR | Factual memory CLI defaulted to PostgreSQL and crashed without a local database, violating the no-external-service local path | covered (`tests/test_cli_factual_memory.py`) |
| current PR | Session orphan recovery created `SessionExperience` rows pointing at missing `KeyMoment` rows after crash/interruption | covered (`tests/test_session_manager.py::test_orphan_recovery_restores_journaled_key_moment_payload`) |
| current PR | New `run_agent.py` workspaces created registry rows but crashed before the REPL because identity/narrative files were missing and journals were not wired | covered (`tests/test_runner.py::test_build_deps_bootstraps_state_and_enables_session_journal`) |
| current PR | `PostgresStateStore.create_key_moment()` placeholder session IDs prevented later `store_key_moments()` from associating moments with the real session | covered (`tests/test_postgres_state_store.py::test_store_key_moments_updates_placeholder_session`) |
| current PR | A second `SessionManager` could recover and delete another process's live active-session journal | covered (`tests/test_session_manager.py::test_orphan_recovery_skips_journals_locked_by_another_manager`) |
| current PR | Crash after `SessionExperience` persistence but before eigenstate/narrative writes made orphan recovery delete the last journal without completing continuity artifacts | covered (`tests/test_session_manager.py::test_orphan_recovery_completes_existing_experience_after_crash`) |
| current PR | Crash after `SessionExperience` persistence could recover eigenstate/narrative with default tone and no `key_insight`, silently losing the original finish summary | covered (`tests/test_session_manager.py::test_orphan_recovery_completes_existing_experience_after_crash`) |
| current PR | Eval runner idempotency ignored `seed`, silently skipping distinct seeded benchmark runs in one process | covered (`tests/atman_eval/test_runner_core.py::test_runner_core_runs_distinct_seeds_for_same_git_sha`) |
| current PR | SIGTERM before the first key moment was force-finished as normal completion instead of `interrupted` | covered (`tests/test_runner.py::test_atman_runner_sigterm_empty_session_persists_interrupted`) |
| current PR | BGE-M3 default produced 1024-dim embeddings while PostgreSQL schemas/deploy defaults/search casts still used old vector assumptions, breaking embedded fact writes, re-embedding, or semantic search | covered (`tests/test_postgres_migration_security.py::test_facts_migration_matches_bge_m3_embedding_dimension`, `tests/test_postgres_migration_security.py::test_agent_schema_matches_bge_m3_embedding_dimension`, `tests/test_postgres_migration_security.py::test_embedding_migration_rebuilds_schema_before_writing_vectors`, `tests/test_postgres_backend.py::test_search_uses_halfvec_literal_for_semantic_ordering`, `tests/test_deploy_package.py::test_deploy_schema_matches_bge_m3_fact_embedding_dimension`, `tests/test_deploy_package.py::test_deploy_defaults_match_bge_m3_embedding_dimension`, `tests/test_deploy_package.py::test_inline_setup_schemas_match_bge_m3_fact_embedding_dimension`) |
| current PR | Pydantic AI test agent factory passed unsupported `base_url` / `api_key` kwargs and the `agent` package was omitted from wheels | covered (`tests/agent/test_atman_agent.py::test_agent_can_be_constructed_without_llm_endpoint`, `tests/agent/test_atman_agent.py::test_agent_package_is_included_in_wheel`) |
| WP-08 v2 | Skills layer redesign: full skill-loop (models, manifest, store, retriever, manager, agent tools, CLI, reflection hook, bootstrap injection) implemented and isolated behind `SkillManagerPort`; 79 new tests | covered (`tests/test_skill_models.py`, `tests/test_skill_noop.py`, `tests/test_skill_store.py`, `tests/test_skill_retriever.py`, `tests/test_skill_manager.py`, `tests/test_skill_reflection_hook.py`, `tests/test_skill_bootstrap.py`) |

### 5.2. From code inspection

| Issue | Location | Impact |
|-------|----------|--------|
| Narrative commit audit doesn't block write on failure | `core/services/narrative_revision.py:73-88` | low — narrative committed, audit message lost |
| Silent skip of malformed JSONL | `adapters/memory/file_backend.py` | low (dev) |
| No model schema migration | all models have schema versions, no migration logic | medium (future) |
| `expected_updated_at` is optional | `core/ports/reflection.py` | medium — depends on caller discipline |

### 5.3. Test coverage gaps

| Area | Status | Location |
|------|--------|----------|
| `FileBackend` with malformed JSONL | ✅ closed | `tests/test_file_backend.py::test_read_facts_skips_malformed_lines_without_data_loss` |
| Concurrent identity writes | ✅ closed (last-writer-wins frozen) | `tests/test_file_state_store.py::test_save_identity_concurrent_writers_resolve_to_last_writer` |
| Concurrent narrative write (true thread race) | open — only mocked optimistic-locking covered | `tests/test_narrative_revision.py::test_repo_update_rejects_stale_concurrency_token` |
| `reflection_run_key` idempotency | ✅ closed | `tests/test_reflection_services.py::test_deep_reflection_repeated_run_does_not_duplicate_snapshot`, `test_daily_reflection_repeated_run_does_not_duplicate_snapshot` |
| Empty eigenstate | ✅ closed | `tests/test_narrative_models.py::test_eigenstate_with_all_empty_collections_is_explicitly_marked` |
| `GovernanceRejectedError` flow | ✅ closed | `tests/test_narrative_revision.py::test_governance_mode_locked_raises_governance_rejected_error` (+ pre-existing AUTO / REVIEW-without-approval tests) |
| End-to-end §3 lifecycle | ✅ closed | `tests/test_system_e2e_lifecycle.py::test_bootstrap_to_deep_reflection_full_lifecycle` |
| Session → experience → reflection invariants (E2E-02, #145) | ✅ closed | `tests/integration/test_full_lifecycle.py::test_full_lifecycle_session_experience_reflection_invariants` |
| CLI surface (factual memory / experience / identity / reflection) | ✅ closed | `tests/test_cli_factual_memory.py`, `tests/test_cli_experience.py`, `tests/test_cli_identity.py`, `tests/test_cli_reflection.py` |
| Demo entrypoints (smoke) | ✅ closed | `tests/test_demo_smoke.py`, `tests/test_demo_full_corpus.py` |
| **Full lifecycle integration (E2E-02)** | ✅ closed | `tests/integration/test_full_lifecycle.py` — verifies (1) experience immutability after session finish, (2) reframing notes from reflection appear on experiences, (3) narrative.recent_layer updates after micro reflection, (4) identity_snapshot_id propagates session → experience → reflection |
| Open WebUI LAN exposure default | ✅ closed | `tests/test_deployment_scripts.py` |

### 5.4. TODO / FIXME

No explicit `TODO`/`FIXME`/`HACK` markers in source. Known limitations are recorded in `reports/IMPLEMENTATION_REPORT.md`:

- ⏳ Embedded vector search — not implemented.
- ⏳ Graph DB support — not implemented.
- ⏳ Session Manager (WP-05) — queued.

---

## 6. Architecture summary

### Seven system components (per `README.md` and `docs/architecture/SYSTEM.md`)

1. **Factual Memory Adapter** ✅ (WP-01) — `adapters/memory/` + `core/ports/memory_backend.py`.
2. **Experience Store** ✅ (WP-02) — `core/models/experience.py` + `adapters/storage/`.
3. **Identity Store** ✅ (WP-03) — `core/models/identity.py` + `core/services/identity_service.py`.
4. **Reflection Engine** ✅ (WP-04) — `core/services/reflection_service.py`.
5. **Self-Narrative** ✅ — `core/models/narrative.py` + `core/services/narrative_service.py`.
6. **Eigenstate** ✅ — `core/models/narrative.py` (`Eigenstate`).
7. **Session Manager** ⏳ (WP-05) — queued.

### Two modes

- **⚡ During session:** the agent operates and captures experience.
- **🌑 Between sessions:** background reflection (micro → daily → deep) updates identity and narrative.

### Tests

- 31 test modules in `tests/` + 1 integration module (includes 7 skill-loop test modules, 79 tests).
- Integration tests: `tests/integration/test_full_lifecycle.py` — full lifecycle from session start to reflection with FileStateStore.
- Target ≥90% coverage.
- CLI excluded from coverage (see `pyproject.toml`).

### Dependencies

- Pydantic, Python ≥3.12, Rich, Textual, Streamlit, pytest, Pyright, hatchling, uv, bandit, pip-audit.

---

## 7. Suggested order of test work

Per issue #125:

1. **Modules** → unit tests for the happy path, edge cases, and errors — for everything that takes input and transforms data.
2. **Integrations** → integration tests for every link in §2 (service↔port, CLI↔service, demo↔real objects, reflection chain).
3. **Scenarios** → system/e2e tests for A–G in §3.
4. **Edge cases** → close the gaps in §4.5.
5. **Regressions** → freeze the issues from §5.2 and §5.3 with tests.

---

## 8. How to keep this map up to date

Treat the map as part of the code: it goes out of date the moment a PR forgets to update it. Concrete rules:

1. **When you add a module / port / adapter / service / CLI command / TUI tab / web page / demo** — add a row to the relevant table in §1 with the file path, purpose, and public API.
2. **When you wire a service to a new port, or add a new CLI/demo entrypoint** — add a row to §2 (which subsection depends on the kind of seam).
3. **When you add or change an end-to-end flow** — add or revise the scenario in §3, with file references.
4. **When you add input validation, a duplicate guard, or a JSON parse handler** — record it in §4.1–4.3 and remove the corresponding "GAP" if it is now closed.
5. **When you fix a regression** — add a row to §5.1 (commit hash + topic) and add a regression test in `tests/`.
6. **When you write new tests** — link them to the section of this map they cover (§1 → unit, §2 → integration, §3 → system/e2e, §4 → edge cases, §5 → regressions). The PR description should make this mapping explicit.
7. **Bilingual sync** — `SYSTEM_MAP.md` is the canonical (English) version; update it first, then sync `SYSTEM_MAP-ru.md`. Same rule as for `README.md`/`README-ru.md`, `MANIFEST.md`/`MANIFEST-ru.md`, `SYSTEM.md`/`SYSTEM-ru.md`.
