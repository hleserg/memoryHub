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
| `core/models/experience.py` | Lived experience, key moments (with `id: UUID` for independent storage), reframing, session closure metadata (E22.7: `close_reason`, `restart_reason`, `user_language`) | `SessionExperience`, `KeyMoment`, `FeltSense`, `ContextHalo`, `ReframingNote`, `EmotionalDepth`, `ReframingNoteAppendResult` |
| `core/models/identity.py` | Agent's self-representation (values, habits, principles, goals, open questions) | `Identity`, `CoreValue`, `Habit`, `Principle`, `Goal`, `OpenQuestion`, `IdentitySnapshot`, `HelpfulnessLevel` |
| `core/models/narrative.py` | Self-narrative document (CORE/RECENT/THREADS) and eigenstate | `NarrativeDocument`, `NarrativeLayer`, `NarrativeThread`, `Eigenstate` (`schema_version`, optional `identity_id`), `LayerType` |
| `core/models/session.py` | Session runtime models: context, events, key moment input, result, active listing | `SessionContext`, `SessionEvent`, `KeyMomentInput`, `SessionResult`, `ActiveSessionSummary` |
| `core/models/reflection.py` | Reflection processes, patterns, health assessment (Jahoda criteria), structured LLM/mock outputs (MODEL-01 / #146), **PostgreSQL reflections persistence** (E27) | `ReflectionLevel`, `PatternCandidate`, `PatternStatus`, `PatternType`, `ReflectionEvent`, `HealthAssessment`, `JahodaCriterion`, `CriterionAssessment`, `ReframingNoteOutput`, `PatternDetectionOutput`, `NarrativeUpdateOutput`, `HealthCriterionOutput`, **`ReflectionRecord`** |
| `core/models/governance.py` | Governance decisions for core narrative mutations | `GovernanceDecision`, `GovernanceMode` |

### 1.2. Ports / interfaces (`src/atman/core/ports/`)

| File | Purpose | Contracts |
|------|---------|-----------|
| `core/ports/memory_backend.py` | Factual memory interface | `FactualMemory` (ABC) |
| `core/ports/clock.py` | Domain clock for reproducibility | `ClockPort` (Protocol) |
| `core/ports/state_store.py` | Storage for experience/identity/narrative/eigenstate/key moments | `StateStore` (with `create_key_moment`, `list_key_moments`, `get_key_moment`), `ExperienceQuery`, `SessionExperienceQuery`, `ValuesTouchedQuery`, `DepthQuery`, `DateRangeQuery`, `FactRefsContainsQuery` |
| `core/ports/reflection.py` | Reflection Engine dependencies; `ReflectionModel` returns structured DTOs (#146) | `ExperienceRepository`, `IdentityRepository`, `NarrativeRepository`, `ReflectionModel`, `PatternStore`, `ReflectionEventStore`, `HealthAssessmentStore`, `ReflectionEventPersistenceObserver`, `NarrativeWriteAuditPort` |
| `core/ports/embedding.py` (E24.6) | Text embedding generation for semantic similarity | `EmbeddingPort` (Protocol) |
| `core/ports/memory_middleware.py` (E24) | Memory surfacing context wrapping | `MemoryMiddlewarePort` (Protocol), `MemoryContext` |
| `core/ports/memory_usage_log.py` (E24.10) | Audit log for surfaced/used memory items | `MemoryUsageLog` (ABC), `MemoryUsageRecord`, `UsageType` |
| `core/ports/reflection_store.py` (E27) | PostgreSQL `reflections` table interface | `ReflectionStore` (ABC): `add`, `get`, `list_by_session`, `list_recent`, `list_by_level`, `list_by_experience` |

### 1.3. Services (`src/atman/core/services/`)

| File | Purpose | Classes |
|------|---------|---------|
| `core/services/experience_service.py` | Experience lifecycle: create, query, reframe, salience | `ExperienceService` |
| `core/services/identity_service.py` | Identity lifecycle: bootstrap, update, snapshot | `IdentityService` |
| `core/services/narrative_service.py` | Narrative document: create, update, archive, validate | `NarrativeService` |
| `core/services/narrative_revision.py` | Narrative updates during reflection with concurrency control | `NarrativeRevisionService` |
| `core/services/session_manager.py` | Session runtime: start, `record_event` (optional async **AffectDetector** hook + **value refusal auto-recording**), `append_key_moment` / `append_key_moment_input`, finish with eigenstate (thread-safe registry, optional `max_active_sessions`, optional `affect_workspace` + `AffectDetectorConfig`, **optional `workspace` for JSONL session journals, inter-process journal locks, and orphan recovery**, **silent refusal detection via `RefusalDetectorConfig`**) | `SessionManager`, `MAX_EIGENSTATE_ITEMS`; session errors live in `core/exceptions.py` |
| `core/services/reflection_service.py` | Three reflection levels: micro, daily, deep | `MicroReflectionService`, `DailyReflectionService`, `DeepReflectionService` |
| `core/services/principle_advisor.py` | Distinguish habit vs principle; advise on principle revision | `PrincipleRevisionAdvisor` |
| `core/services/conflict_detector.py` (E24.5) | Detect contradictions between active facts; produces small cognitive tension signals | `ConflictDetector`, `FactConflict` |
| `core/services/emotional_echo.py` (E24.7) | Build historical emotional context from recent experiences (recency × intensity) | `EmotionalEcho`, `EchoItem` |
| `core/services/passive_memory_injector.py` (E24.6, E24.8) | Surface relevant facts/experiences via embedding similarity + 1-hop graph expansion | `PassiveMemoryInjector`, `SurfacedMemory` |
| `core/services/session_working_memory.py` (E24.9) | In-session LRU cache of surfaced facts/experiences to avoid duplicate surfacing | `SessionWorkingMemory`, `CachedItem` |

### 1.4a. Affect detector (`src/atman/affect/`, E21)

| File | Purpose | Public surface |
|------|---------|----------------|
| `affect/models.py` | DTOs for metrics, detector output, agent self-report | `AffectMetrics`, `AffectRecord`, `AgentMemoryReport` (optional `emotional_depth` → `KeyMoment.how_i_felt.depth`), `TriggerReason` |
| `affect/metrics.py` | Eight behavioural floats + sincerity heuristic over tokens | `nrc_emotion_score`, density helpers, `min_length_gate`, `sincerity_score`, … |
| `affect/baseline.py` | Rolling z-scores + `{workspace}/affect_baseline.jsonl` persistence | `RollingBaseline` |
| `affect/detector.py` | Language sniff, trigger logic (anomaly / random sample / divergence / self-report), `KeyMoment` writes via callback | `AffectDetector`, `AffectDetectorConfig`; CLI `python -m atman.affect.detector --demo` |
| `affect/refusal_detector.py` | Text-only value refusal detection (no LLM required) — three layers: (1) morphology via pymorphy3 (refusal verbs + negated modals), (2) NRC emotion semantic context (disgust/anger density for moral framing), (3) capability exclusion (technical inability vs ethical stance); optional LLM fallback for uncertain zone | `is_value_refusal`, `score_refusal`, `RefusalDetectorConfig`, `RefusalScore` |
| `affect/emolex/` | Vendored NRC Emotion Lexicon (ru/en) + pymorphy3 lemmatisation | `emotion_score`, `tokenize`, JSON lexicons |

### 1.4. Core utilities

| File | Purpose |
|------|---------|
| `config.py` | Pydantic settings (`EmbeddingSettings`, `LLMSettings`, `MemorySettings`), **`OpenAILLMConfig`** (base_url, api_key, model, timeout, max_retries with validation ≥1), **`AnthropicLLMConfig`** (api_key, model, max_tokens), `build_memory_backend()` factory, **`build_embedding_adapter()` factory** (selects FlagEmbedding/Ollama/Mock backend), `validate_embedding_dimension()` (startup dimension check); defaults: embedding backend=`ollama` with `bge-m3`/1024d (FlagEmbedding backend uses `flag_model="BAAI/bge-m3"`, with FP16/batch_size/max_length settings), LLM=`gemma3:27b-it-qat`, factual memory=`FileBackend`; supports `ATMAN_MEMORY_BACKEND=postgres|file|inmemory`, `EMBEDDING_BACKEND=ollama|flag|mock`; **legacy env var fallback**: `OLLAMA_HOST`→`EMBEDDING_OLLAMA_HOST`, `OLLAMA_EMBED_MODEL`→`EMBEDDING_MODEL`, `ATMAN_OLLAMA_BASE_URL`→`LLM_OLLAMA_HOST`, `ATMAN_OLLAMA_MODEL`→`LLM_MODEL` |
| `core/exceptions.py` | `AtmanError`, `GovernanceRejectedError`, `NarrativePersistenceConflictError`, `SessionNotFoundError`, `SessionAlreadyFinishedError`, `TooManyActiveSessionsError` |
| `core/clock_impl.py` | `SystemClock`, `FrozenClock` |
| `core/narrative_write_audit.py` | Narrative commit audit hooks |
| `core/reflection_event_audit.py` | Reflection event persistence observers |
| `core/reflection_run_keys.py` | Deterministic reflection run keys |

### 1.5. Adapters (`src/atman/adapters/`)

| File | Implements port | Behavior |
|------|-----------------|----------|
| `adapters/memory/in_memory_backend.py` (`InMemoryBackend`) | `FactualMemory` | no persistence |
| `adapters/memory/file_backend.py` (`FileBackend`) | `FactualMemory` | JSONL + file locking |
| `adapters/memory/postgres_backend.py` (`PostgresFactualMemory`) | `FactualMemory` | PostgreSQL `public.facts` / `public.fact_relations`, RLS via `ATMAN_CURRENT_AGENT`, optional `EmbeddingPort` with `ILIKE` fallback |
| `adapters/memory/mock_embedding.py` (`MockEmbeddingAdapter`) | `EmbeddingPort` | deterministic SHA-256-seeded 1024-dim embeddings; no external deps; for tests/CI |
| `adapters/memory/bm25_embedding.py` (`BM25EmbeddingAdapter`) | `EmbeddingPort` | local BM25 sparse vectors via fixed-dimension feature hashing (Unicode-aware tokenizer); corpus stats from `embed_batch`/`embed_with_corpus` are reused by later `embed` calls |
| `adapters/memory/ollama_embedding.py` (`OllamaEmbeddingAdapter`) | `EmbeddingPort` | Ollama HTTP `/api/embeddings`; defaults: `bge-m3`/1024d; env: `EMBEDDING_MODEL`, `EMBEDDING_OLLAMA_HOST` (legacy: `OLLAMA_EMBED_MODEL`, `OLLAMA_HOST`); configurable timeout |
| `adapters/memory/flag_embedding.py` (`FlagEmbeddingAdapter`) | `EmbeddingPort` | Native FlagEmbedding SDK (BGEM3FlagModel) via PyTorch; lazy model loading (~570MB to `~/.cache/huggingface/`); supports dense (1024d) + sparse (lexical) + ColBERT via `embed_batch_full()`; configurable FP16, batch_size, max_length, device; no external process required; defaults: `BAAI/bge-m3`; env: `EMBEDDING_FLAG_MODEL`, `EMBEDDING_USE_FP16`, `EMBEDDING_BATCH_SIZE`, `EMBEDDING_MAX_LENGTH` |
| `adapters/memory/in_memory_usage_log.py` (`InMemoryUsageLog`) | `MemoryUsageLog` | in-memory append-only list with filtering by item/usage_type/time (no eviction) |
| `adapters/storage/in_memory_experience_store.py` (`InMemoryExperienceStore`) | `StateStore` | in-memory (partial: experience only; KeyMoment/Identity/Narrative ops raise `NotImplementedError`) |
| `adapters/storage/jsonl_experience_store.py` (`JsonlExperienceStore`) | `StateStore` | JSONL for experience (partial: experience only; KeyMoment/Identity/Narrative ops raise `NotImplementedError`) |
| `adapters/storage/in_memory_state_store.py` (`InMemoryStateStore`) | `StateStore` | full in-memory implementation with deep copies (experience + identity + narrative + eigenstate + key moments dict) |
| `adapters/storage/file_state_store.py` (`FileStateStore`) | `StateStore` | JSON files (experience + identity + narrative + eigenstate) + `key_moments.jsonl` (append-only JSONL with corruption recovery) |
| `adapters/storage/in_memory_reflection_store.py` | `PatternStore`, `ReflectionEventStore`, `HealthAssessmentStore` | reflection output stores |
|| **`adapters/state/postgres_state_store.py`** (`PostgresStateStore`) | **`StateStore`** | **PostgreSQL implementation** (KeyMoment operations only, psycopg3; other StateStore methods raise `NotImplementedError`) |
| **`adapters/storage/in_memory_postgres_reflection_store.py`** (`InMemoryReflectionStore`) | **`ReflectionStore`** | **E27**: in-memory with BIGSERIAL + RLS simulation |
| `adapters/storage/reflection_persistence_helper.py` | — | **E27**: helper functions for persisting reflections (`persist_micro_reflection`, `persist_daily_reflection`, `persist_deep_reflection`) |
| `adapters/reflection/mock_reflection_model.py` (`MockReflectionModel`) | `ReflectionModel` | deterministic mock |
| **`adapters/reflection/openai_reflection_model.py`** (**`OpenAIReflectionModel`**) | **`ReflectionModel`** | **Generic OpenAI-compatible adapter** with `OpenAILLMConfig` (base_url, api_key, model, timeout, configurable retries); **`adapters/reflection/__init__.py`** exports **`get_reflection_model()`** factory (env `ATMAN_REFLECTION_BACKEND=openai|anthropic|mock`, default: `openai`) |
| `adapters/reflection/fixture_loader.py` | — | load fixtures for demos |
| `adapters/agent/config.py` (`ModelConfig`, `AgentConfig`) | — | Pydantic AI model + agent runtime config: context window limits, session timeout, free-time toggle, monologue visibility, **memory injection mode** (`assistant_message`/`user_message`/`system_prompt` for universal memory context delivery) (E22.1, E26-R1, E26-R2, E26-R4) |
| `adapters/agent/deps.py` (`AtmanDeps`, `AtmanDeps.from_config`) | — | frozen DI container wiring `SessionManager`, `IdentityService`, `ExperienceService`, `MicroReflectionService`, `StateStore`; `from_config` factory transfers validated limits from `AgentConfig`; optional `injected_context` field for `system_prompt` injection mode |
|| `adapters/agent/memory_injection.py` (`inject_memory`, `MemoryInjectionMode`) | — | Universal memory injection with three modes: (1) `assistant_message` — inserts `ModelResponse` at history start (default; OpenAI/Ollama compatible), (2) `user_message` — wraps memory as user turn (Anthropic-compatible), (3) `system_prompt` — sets `deps.injected_context` for `build_instructions` to append (legacy pydantic-ai system-prompt path) |
| `adapters/agent/instructions.py` (`build_instructions`, `build_memory_context`) | — | `build_instructions`: builds behavioral rules (how agent uses tools, commitments); identity/narrative moved to `build_memory_context()` for delivery via `inject_memory()`; when `memory_injection_mode == "system_prompt"`, appends `deps.injected_context` |
| `adapters/agent/tools.py` (`record_key_moment` async, `log_experience`, `restart_session`, `wait_session`) | — | Pydantic AI tools: `record_key_moment` → `AffectDetector.submit_self_report` when `SessionManager` is configured with affect; `log_experience` redirect stub; `restart_session` / `wait_session` return sentinel strings for session control (E22.4) |
| `adapters/agent/factory.py` (`build_deps`) | — | Assembles `AtmanDeps`, `SessionManager`, `FileStateStore`, services, optional `AffectDetector` from workspace + `AgentConfig`; bootstraps missing identity/narrative for new runner workspaces and wires `SessionManager(workspace=...)` so crash journals are active |
| `adapters/agent/runner.py` (`AtmanRunner`, `chat`, `_force_finish`, `_check_restart_requested`, `_do_restart`, `_build_restart_package`, `_check_token_usage`, `_start_stdin_reader`, `_stop_stdin_reader`, `_handle_menu_mode`, `_handle_free_time_mode`) | — | Signal-aware session lifecycle wrapper with restart loop, token monitoring, and timeout/menu (E22.2, E22.3, E22.5, E22.6); token monitoring: progressive warnings at 70/80/90%, force-close at 95% (`_check_token_usage`); queue-based stdin reader (no race on timeout); restart detection: sentinel → finish session with `close_reason="restart"` → build package (key moments + reason + tail) → new session with updated `AtmanDeps`; session timeout → menu mode (reflect/wait/sleep/save_to_memory/free_time); SIGTERM/KeyboardInterrupt/EOFError/SystemExit → graceful `_force_finish()`; creates minimal `KeyMoment` if empty; preserves exit codes |
| `agents_registry.py` (`AgentsRegistry`) | — | PostgreSQL-backed registry of agent instances (app/admin DB URLs); used by `src/run_agent.py` |

### 1.5b. Optional local coding agent (**not** in core wheel — `atman_agent_cli/`)

| Path | Notes |
|------|--------|
| `atman_agent_cli/src/atman/agent_cli/` | Coding-agent Textual/RAG surface layered on adapters when wired. Sources live beside core; Hatch ships only [`src/atman`](#). Use `PYTHONPATH=atman_agent_cli/src:src`, `pip install -e ".[agent-cli]"`; prep tooling `scripts/agent_cli/`, docs `atman_agent_cli/RUNBOOK.md`. Listed core namespaces must not import **`atman.agent_cli`** — **`.importlinter` contract `no-core-to-optional-agent-cli`**. |

### 1.6. CLI / TUI / Web / Demos

| File | Category | Purpose |
|------|----------|---------|
| `cli.py` | CLI | Factual memory REPL |
| `cli_experience.py` | CLI | Experience Store |
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
| `eval/migrations/alembic.ini`, `eval/migrations/env.py` | eval storage | Alembic configuration for the isolated PostgreSQL `eval` schema |
| `eval/migrations/versions/0010_*` ... `0040_*` | eval storage | idempotent eval schema, benchmark run tables, supporting tables, and trend materialized view |
| `scripts/eval/partition_manager.py` | operations | creates future partitions, detaches old partitions, and reports `eval.benchmark_runs` partition status |

---

## 2. Integrations

Connections between two or more parts. These are seams that may break independently of the underlying logic.

### 2.1. Service ↔ port

| Connection | Files | Type |
|-----------|-------|------|
| `ExperienceService` ↔ `StateStore` | `core/services/experience_service.py` → `core/ports/state_store.py` | DI |
| `IdentityService` ↔ `StateStore` | `core/services/identity_service.py` → `core/ports/state_store.py` | DI |
| `NarrativeService` ↔ `StateStore` | `core/services/narrative_service.py` → `core/ports/state_store.py` | DI |
| `SessionManager` ↔ `StateStore` | `core/services/session_manager.py` → `core/ports/state_store.py` | loads identity/narrative at start; `IdentitySnapshot` on start; deterministic `SessionExperience.id` (uuid5 of `session_id`) for idempotent `finish_session`; active journals hold an advisory lock so another `SessionManager` does not recover a live session; session journals include full `KeyMoment` payloads so orphan recovery can restore missing moment rows instead of creating dangling references; `finish_session` calls `get_key_moment` + `create_key_moment` per moment for idempotent retry; computes `unexamined_fact_refs` (facts in `_facts_read` but not in any key moment `fact_refs`); eigenstate load scoped by `identity_id`; recent narrative update uses `save_narrative(..., expected_updated_at=...)` |
| `NarrativeRevisionService` ↔ `NarrativeRepository` | `core/services/narrative_revision.py` → `core/ports/reflection.py` | optimistic locking |
| `MicroReflectionService` ↔ `ExperienceRepository` + `NarrativeRepository` | `core/services/reflection_service.py` | reads experience, updates recent layer |
| `DailyReflectionService` ↔ `ExperienceRepository` + `PatternStore` + `ReflectionEventStore` | `core/services/reflection_service.py` | pattern detection |
| `DeepReflectionService` ↔ all reflection ports | `core/services/reflection_service.py` | health + identity + narrative update |
| `PrincipleRevisionAdvisor` ↔ `PatternCandidate` + `Identity` | `core/services/principle_advisor.py` | analyzes patterns in identity context |
| `ConflictDetector` ↔ `FactualMemory` | `core/services/conflict_detector.py` → `core/ports/memory_backend.py` | DI; lightweight contradiction scan over ACTIVE candidates returned by `search()` |
| `EmotionalEcho` ↔ `StateStore` | `core/services/emotional_echo.py` → `core/ports/state_store.py` | DI; `lookback_days` window via `search_experiences` |
| `PassiveMemoryInjector` ↔ `EmbeddingPort` + `FactualMemory` + `StateStore` | `core/services/passive_memory_injector.py` → `core/ports/embedding.py`, `core/ports/memory_backend.py`, `core/ports/state_store.py` | DI; top-K similarity + 1-hop associative graph expansion; optional `SessionWorkingMemory` cache |

### 2.2. Adapter ↔ port

| Adapter | Implements |
|---------|------------|
| `InMemoryBackend`, `FileBackend`, `PostgresFactualMemory` | `FactualMemory` |
| `InMemoryExperienceStore`, `JsonlExperienceStore`, `FileStateStore`, `PostgresStateStore` | `StateStore` |
| `MockReflectionModel`, **`OpenAIReflectionModel`** | `ReflectionModel` |
| `InMemoryPatternStore`, `InMemoryReflectionEventStore`, `InMemoryHealthAssessmentStore` | corresponding ports |
| `MockEmbeddingAdapter`, `BM25EmbeddingAdapter`, `OllamaEmbeddingAdapter`, `FlagEmbeddingAdapter` | `EmbeddingPort` |
| `InMemoryUsageLog` | `MemoryUsageLog` |
| `InMemoryReflectionStore` (`adapters/storage/in_memory_postgres_reflection_store.py`) | `ReflectionStore` (E27) |

### 2.2a. Agent adapter ↔ services

| Connection | Files | Type |
|-----------|-------|------|
| `AtmanDeps` ↔ `SessionManager`, `IdentityService`, `ExperienceService`, `MicroReflectionService`, `StateStore` | `adapters/agent/deps.py` | DI container (frozen dataclass); optional `injected_context` for `system_prompt` memory injection mode |
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

### 2.4. Demo ↔ real objects

| Demo | Chain |
|------|-------|
| `demo.py` | `InMemoryBackend` + `FileBackend` for `FactualMemory` |
| `demo_experience_store.py` | `JsonlExperienceStore` → `ExperienceService` |
| `demo_identity.py` | `FileStateStore` → `IdentityService` + `NarrativeService` |
| `demo_session_manager.py` | `FileStateStore` → `SessionManager` (loads identity/narrative, records events/moments, stores experience/eigenstate) |
| `demo_reflection.py` | mocks + fixture_loader → `MicroReflectionService` → `DailyReflectionService` → `DeepReflectionService` |
| `demo_full_corpus.py` | `e2e` session JSON → `FileStateStore` + `SessionManager` + `StateStore*Adapter` → micro → daily (per UTC day) → deep; `DeterministicReflectionModel` |

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
MicroReflectionService — reads ExperienceRepository
  ↓ updates
NarrativeRepository (recent layer) — optimistic locking
  ↓
DailyReflectionService — reads experience for the UTC day, detects patterns
  ↓ stores
PatternStore + ReflectionEventStore
  ↓
DeepReflectionService — reads all repositories, assesses health,
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
| current PR | SIGTERM before the first key moment was force-finished as normal completion instead of `interrupted` | covered (`tests/test_runner.py::test_atman_runner_sigterm_empty_session_persists_interrupted`) |
| current PR | BGE-M3 default produced 1024-dim embeddings while PostgreSQL schemas/deploy defaults/search casts still used old vector assumptions, breaking embedded fact writes, re-embedding, or semantic search | covered (`tests/test_postgres_migration_security.py::test_facts_migration_matches_bge_m3_embedding_dimension`, `tests/test_postgres_migration_security.py::test_agent_schema_matches_bge_m3_embedding_dimension`, `tests/test_postgres_migration_security.py::test_embedding_migration_rebuilds_schema_before_writing_vectors`, `tests/test_postgres_backend.py::test_search_uses_halfvec_literal_for_semantic_ordering`, `tests/test_deploy_package.py::test_deploy_schema_matches_bge_m3_fact_embedding_dimension`, `tests/test_deploy_package.py::test_deploy_defaults_match_bge_m3_embedding_dimension`, `tests/test_deploy_package.py::test_inline_setup_schemas_match_bge_m3_fact_embedding_dimension`) |
| current PR | Pydantic AI test agent factory passed unsupported `base_url` / `api_key` kwargs and the `agent` package was omitted from wheels | covered (`tests/agent/test_atman_agent.py::test_agent_can_be_constructed_without_llm_endpoint`, `tests/agent/test_atman_agent.py::test_agent_package_is_included_in_wheel`) |

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

- 24 test modules in `tests/` + 1 integration module.
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
