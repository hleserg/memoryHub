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
| `core/models/experience.py` | Lived experience, key moments, reframing | `SessionExperience`, `KeyMoment`, `FeltSense`, `ContextHalo`, `ReframingNote`, `EmotionalDepth`, `ReframingNoteAppendResult` |
| `core/models/identity.py` | Agent's self-representation (values, habits, principles, goals, open questions) | `Identity`, `CoreValue`, `Habit`, `Principle`, `Goal`, `OpenQuestion`, `IdentitySnapshot`, `HelpfulnessLevel` |
| `core/models/narrative.py` | Self-narrative document (CORE/RECENT/THREADS) and eigenstate | `NarrativeDocument`, `NarrativeLayer`, `NarrativeThread`, `Eigenstate` (`schema_version`, optional `identity_id`), `LayerType` |
| `core/models/session.py` | Session runtime models: context, events, key moment input, result, active listing | `SessionContext`, `SessionEvent`, `KeyMomentInput`, `SessionResult`, `ActiveSessionSummary` |
| `core/models/reflection.py` | Reflection processes, patterns, health assessment (Jahoda criteria) | `ReflectionLevel`, `PatternCandidate`, `PatternStatus`, `PatternType`, `ReflectionEvent`, `HealthAssessment`, `JahodaCriterion`, `CriterionAssessment` |
| `core/models/governance.py` | Governance decisions for core narrative mutations | `GovernanceDecision`, `GovernanceMode` |

### 1.2. Ports / interfaces (`src/atman/core/ports/`)

| File | Purpose | Contracts |
|------|---------|-----------|
| `core/ports/memory_backend.py` | Factual memory interface | `FactualMemory` (ABC) |
| `core/ports/clock.py` | Domain clock for reproducibility | `ClockPort` (Protocol) |
| `core/ports/state_store.py` | Storage for experience/identity/narrative | `StateStore`, `ExperienceQuery`, `SessionExperienceQuery`, `ValuesTouchedQuery`, `DepthQuery`, `DateRangeQuery` |
| `core/ports/reflection.py` | Reflection Engine dependencies | `ExperienceRepository`, `IdentityRepository`, `NarrativeRepository`, `ReflectionModel`, `PatternStore`, `ReflectionEventStore`, `HealthAssessmentStore`, `ReflectionEventPersistenceObserver`, `NarrativeWriteAuditPort` |

### 1.3. Services (`src/atman/core/services/`)

| File | Purpose | Classes |
|------|---------|---------|
| `core/services/experience_service.py` | Experience lifecycle: create, query, reframe, salience | `ExperienceService` |
| `core/services/identity_service.py` | Identity lifecycle: bootstrap, update, snapshot | `IdentityService` |
| `core/services/narrative_service.py` | Narrative document: create, update, archive, validate | `NarrativeService` |
| `core/services/narrative_revision.py` | Narrative updates during reflection with concurrency control | `NarrativeRevisionService` |
| `core/services/session_manager.py` | Session runtime: start, record events/key moments, finish with eigenstate (thread-safe registry, optional `max_active_sessions`) | `SessionManager`, `MAX_EIGENSTATE_ITEMS`; session errors live in `core/exceptions.py` |
| `core/services/reflection_service.py` | Three reflection levels: micro, daily, deep | `MicroReflectionService`, `DailyReflectionService`, `DeepReflectionService` |
| `core/services/principle_advisor.py` | Distinguish habit vs principle; advise on principle revision | `PrincipleRevisionAdvisor` |

### 1.4. Core utilities

| File | Purpose |
|------|---------|
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
| `adapters/storage/in_memory_experience_store.py` (`InMemoryExperienceStore`) | `StateStore` | in-memory |
| `adapters/storage/jsonl_experience_store.py` (`JsonlExperienceStore`) | `StateStore` | JSONL for experience |
| `adapters/storage/file_state_store.py` (`FileStateStore`) | `StateStore` | JSON files (experience + identity + narrative + eigenstate) |
| `adapters/storage/in_memory_reflection_store.py` | `PatternStore`, `ReflectionEventStore`, `HealthAssessmentStore` | reflection output stores |
| `adapters/reflection/mock_reflection_model.py` (`MockReflectionModel`) | `ReflectionModel` | deterministic mock |
| `adapters/reflection/fixture_loader.py` | — | load fixtures for demos |

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
| `e2e/generate_fixtures.py` | e2e | LLM-backed session JSON fixture generator (`python -m e2e.generate_fixtures`); default 20 `en/` + 20 `ru/` corpora with parallel locale runs; Anthropic tool_use, two-pass skeleton + per-session; `--corpus-policy strict|soft`, `--max-corpus-regen N` (strict tail cap); optional extra `[e2e]`; manual/secret-gated automation candidate ([issue #141](https://github.com/hleserg/atman/issues/141)) |
| `e2e/models.py`, `e2e/validation.py`, `e2e/llm.py`, `e2e/prompts.py` | e2e | fixture schema, intra/cross-session validators, API orchestration, prompts |
| `e2e/full_loop.py`, `e2e/__main__.py` | e2e | integration driver over WP-01..05 with session JSON fixtures (`python -m e2e`); optional/manual and suitable for a targeted GitHub Actions smoke job |

---

## 2. Integrations

Connections between two or more parts. These are seams that may break independently of the underlying logic.

### 2.1. Service ↔ port

| Connection | Files | Type |
|-----------|-------|------|
| `ExperienceService` ↔ `StateStore` | `core/services/experience_service.py` → `core/ports/state_store.py` | DI |
| `IdentityService` ↔ `StateStore` | `core/services/identity_service.py` → `core/ports/state_store.py` | DI |
| `NarrativeService` ↔ `StateStore` | `core/services/narrative_service.py` → `core/ports/state_store.py` | DI |
| `SessionManager` ↔ `StateStore` | `core/services/session_manager.py` → `core/ports/state_store.py` | loads identity/narrative at start; `IdentitySnapshot` on start; deterministic `SessionExperience.id` (uuid5 of `session_id`) for idempotent `finish_session`; eigenstate load scoped by `identity_id`; recent narrative update uses `save_narrative(..., expected_updated_at=...)` |
| `NarrativeRevisionService` ↔ `NarrativeRepository` | `core/services/narrative_revision.py` → `core/ports/reflection.py` | optimistic locking |
| `MicroReflectionService` ↔ `ExperienceRepository` + `NarrativeRepository` | `core/services/reflection_service.py` | reads experience, updates recent layer |
| `DailyReflectionService` ↔ `ExperienceRepository` + `PatternStore` + `ReflectionEventStore` | `core/services/reflection_service.py` | pattern detection |
| `DeepReflectionService` ↔ all reflection ports | `core/services/reflection_service.py` | health + identity + narrative update |
| `PrincipleRevisionAdvisor` ↔ `PatternCandidate` + `Identity` | `core/services/principle_advisor.py` | analyzes patterns in identity context |

### 2.2. Adapter ↔ port

| Adapter | Implements |
|---------|------------|
| `InMemoryBackend`, `FileBackend` | `FactualMemory` |
| `InMemoryExperienceStore`, `JsonlExperienceStore`, `FileStateStore` | `StateStore` |
| `MockReflectionModel` | `ReflectionModel` |
| `InMemoryPatternStore`, `InMemoryReflectionEventStore`, `InMemoryHealthAssessmentStore` | corresponding ports |

### 2.3. CLI ↔ service

| CLI | Wiring | File |
|-----|--------|------|
| `cli.py` | `FileBackend` directly as `FactualMemory` | `cli.py:14-24` |
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
2. During session: `record_event(...)` tracks raw events from lower agent.
3. `record_key_moment(...)` captures significant moments with mandatory emotional coloring (valence/intensity/depth).
4. If coloring incomplete → flag `incomplete_coloring=True` (honest about limitation).
5. `finish_session(...)` → creates `SessionExperience` (`recorded_by="session_manager"`) + `Eigenstate`.
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
| `KeyMomentInput` with zero valence/intensity without `incomplete_coloring` | `SessionManager.record_key_moment` → `ValueError` | `core/services/session_manager.py` |
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
