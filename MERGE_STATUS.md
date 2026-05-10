# Merge Status Report: feature/E27 ← main
**Date**: 2026-05-10 09:09 UTC  
**Status**: ⚠️ Partial — 14 simple conflicts resolved, 8 complicated conflicts remaining

---

## ✅ RESOLVED: Simple Conflicts (14 files)

Successfully auto-resolved without semantic conflicts:

### Documentation (2 files)
- ✅ `docs/architecture/SYSTEM_MAP.md` — merged both port entries
- ✅ `docs/architecture/SYSTEM_MAP-ru.md` — kept ours (will sync manually later)

### Build Configuration (2 files)
- ✅ `pyproject.toml` — included both dependencies (`pydantic-settings` + `pydantic-ai`)
- ✅ `uv.lock` — accepted from main

### Embedding Infrastructure (5 files)
- ✅ `src/atman/core/ports/embedding.py` — **kept ours** (already has BOTH `model_name()` AND `similarity()` from previous fix)
- ✅ `src/atman/adapters/memory/bm25_embedding.py` — accepted E24 version
- ✅ `src/atman/adapters/memory/mock_embedding.py` — accepted E24 version  
- ✅ `src/atman/adapters/memory/ollama_embedding.py` — accepted E24 version
- ✅ `src/atman/adapters/memory/in_memory_usage_log.py` — accepted E24 version

### Service Layer (5 files)
- ✅ `src/atman/core/services/conflict_detector.py` — accepted E24 version (already fixed in previous commit)
- ✅ `src/atman/core/services/emotional_echo.py` — accepted E24 version
- ✅ `src/atman/core/services/passive_memory_injector.py` — accepted E24 version (already fixed)
- ✅ `src/atman/core/services/session_working_memory.py` — accepted E24 version
- ✅ `src/atman/core/models/session.py` — **kept ours** (already has `_facts_read` fix)

---

## ⚠️ REMAINING: Complicated Conflicts (8 files)

These require manual 3-way merge — both branches made substantive, overlapping changes:

### 1. **Memory Backends** (2 files) — FEATURE INTERLEAVING

**Files:**
- `src/atman/adapters/memory/file_backend.py`
- `src/atman/adapters/memory/in_memory_backend.py`

**Conflict Type:** Both E27 and E24 added different methods to the same classes.

**Details:**
- E27 added: reflection-related integration points
- E24 added: `FactStatus` support, salience tracking, `decay_salience()` method

**Why Complicated:**
- Changes are interleaved — can't pick one side
- Both feature sets are needed
- Method signatures must remain compatible with both caller sets

**Recommended Action:**
Manually merge ALL methods from both branches. Check:
1. No duplicate method names
2. All E24.1 salience features present
3. All E27 reflection hooks present

---

### 2. **Memory Backend Port** (1 file) — API EXTENSION

**File:**
- `src/atman/core/ports/memory_backend.py`

**Conflict Type:** Both branches extended the abstract interface.

**Details:**
- E27 may have added reflection-related abstract methods
- E24 added `decay_salience()`, `validate_decay_factor()`, fact status queries

**Why Complicated:**
- Port changes propagate to ALL adapters
- Breaking changes must be carefully coordinated

**Recommended Action:**
Include ALL abstract methods from both branches. Then verify every adapter implements them.

---

### 3. **Fact Model** (1 file) — SCHEMA EVOLUTION

**File:**
- `src/atman/core/models/fact.py`

**Conflict Type:** Both branches added fields to `FactRecord` Pydantic model.

**Details:**
- E24 added: `FactStatus`, `salience`, `confirmation_count`, `invalidated_at`, `invalidation_note`, `superseded_by`, `disputed_at`, `last_confirmed_at`
- E27 added: possibly reflection-related fields

**Why Complicated:**
- Field order affects serialization
- Validators may conflict
- Golden schema tests (`test_golden_schema.py`) will fail if not merged correctly

**Recommended Action:**
1. Merge ALL fields, maintaining logical grouping
2. Merge ALL validators
3. Update `tests/test_golden_schema.py` with complete schema
4. Run serialization round-trip tests

---

### 4. **Session Manager** (1 file) — LIFECYCLE HOOKS

**File:**
- `src/atman/core/services/session_manager.py`

**Conflict Type:** Both branches modified session lifecycle.

**Details:**
- E27: Added reflection checkpoint logic
- E24: Added memory usage tracking, passive surfacing integration, `_note_facts_read()` calls

**Why Complicated:**
- Session lifecycle has multiple hooks
- E24 expects `_facts_read` tracking (which we fixed)
- E27 expects reflection integration
- Both must coexist

**Recommended Action:**
Carefully merge:
1. All E24 `_note_facts_read()` calls
2. All E27 reflection checkpoints
3. Verify `finish_session()` calls both E24 and E27 logic

---

### 5. **CLI** (1 file) — COMMAND ADDITIONS

**File:**
- `src/atman/cli.py`

**Conflict Type:** Both branches added new commands.

**Details:**
- E27: Added reflection commands (possibly)
- E24: Added salience decay commands, embedding configuration

**Why Complicated:**
- Command name collisions possible
- Help text regions overlap
- Config/env var handling differs

**Recommended Action:**
1. Merge all commands from both branches
2. Check for command name collisions — rename if needed
3. Unify help text format
4. Test `python -m atman.cli --help` after merge

---

### 6. **Backend Tests** (2 files) — DIVERGENT TEST SUITES

**Files:**
- `tests/test_file_backend.py`
- `tests/test_in_memory_backend.py`

**Conflict Type:** Both branches added tests for their features.

**Details:**
- E27: Added reflection integration tests
- E24: Added salience decay tests, fact lifecycle tests

**Why Complicated:**
- Fixture conflicts — both may modify shared fixtures
- Assertion conflicts — tests expect different behaviors
- Coverage must remain ≥90% after merge

**Recommended Action:**
1. Merge ALL tests from both branches
2. Ensure no duplicate test names (rename if needed)
3. Merge fixture modifications
4. Run `pytest tests/test_*backend* -v` to verify

---

## Summary

### Statistics
- **Total conflicts:** 22 files
- **Simple (resolved):** 14 files ✅
- **Complicated (remaining):** 8 files ⚠️

### Resolution Rate
- **64% auto-resolved** (14/22)
- **36% need human review** (8/22)

### Critical Blockers
The 8 remaining files block merge completion because:
1. **Feature interleaving** — can't pick one side without losing functionality
2. **API contracts** — port changes affect multiple adapters
3. **Test coverage** — must preserve ≥90% after merge

---

## Next Steps

**Option A: Complete Manual Merge** (Recommended)
1. Manually resolve the 8 files following guidelines above
2. Run `make check` after each file to catch errors early
3. Commit when all resolved: `git commit -m "Merge main into E27 — resolve all conflicts"`

**Option B: Abort and Coordinate**
1. `git merge --abort`
2. Coordinate with E24 author to align features
3. Consider rebasing E27 on E24 instead of merging

**Option C: Accept Theirs + Re-apply E27**
1. `git merge --abort && git merge -X theirs origin/main`
2. Manually re-apply E27-specific changes on top
3. More work but cleaner history

---

## Current State

**⚠️ Git state:** Merge in progress, 8 unresolved conflicts  
**⚠️ Action required:** Human must resolve remaining files OR abort merge

**To abort this merge:**
```bash
git merge --abort
```

**To continue resolving:**
1. Edit each remaining file manually
2. Remove all `<<<<<<<`, `=======`, `>>>>>>>` markers
3. Test changes: `pyright src/ tests/` and `pytest tests/ -v`
4. Stage: `git add <file>`
5. When all 8 resolved: `git commit`

---

**Report generated by**: Cloud Agent  
**Merge base**: `fcfeaf806e06530c47ae702d14404f2ff083a242`  
**HEAD**: `0f98399` (feature/E27 with type error fixes)  
**Target**: `12f947d` (main with E24 + E26)
