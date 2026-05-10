# Merge Conflict Analysis Report
## Branch: `feature/E27-core-reflections-schema` ← `origin/main`

**Date**: 2026-05-10 08:40 UTC  
**Status**: Phase 1 Complete (Simple conflicts resolved) — Phase 2 requires human decisions

---

## Executive Summary

**Total conflicts**: 21 files  
**Simple conflicts resolved**: 8 files ✅  
**Complicated conflicts remaining**: 13 files ⚠️

### Root Cause

Two major epics were developed in parallel:
- **E27 (Core Reflections Schema)** — this branch
- **E24 (Living Memory)** + **E26 (Pydantic AI Wrapper)** — merged to main

Both epics independently added embedding support, memory tracking, and related infrastructure, resulting in **conflicting implementations** of the same features.

---

## ✅ RESOLVED: Simple Conflicts (Phase 1)

### 1. Documentation (2 files) — ✅ RESOLVED
- `docs/architecture/SYSTEM_MAP.md`
- `docs/architecture/SYSTEM_MAP-ru.md`

**Resolution**: Merged both sets of entries, keeping E24's more detailed descriptions with epic references.

### 2. Build Configuration (2 files) — ✅ RESOLVED
- `pyproject.toml` — Both dependencies included
- `uv.lock` — Accepted from main (will regenerate later)

**Resolution**: 
```python
dependencies = [
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",  # From E27
    "pydantic-ai>=1.88.0,<2.0",  # From E24/E26
    ...
]
```

### 3. Identical Service Files (4 files) — ✅ RESOLVED
- `src/atman/core/services/conflict_detector.py`
- `src/atman/core/services/emotional_echo.py`
- `src/atman/core/services/passive_memory_injector.py`
- `src/atman/core/services/session_working_memory.py`

**Resolution**: Accepted versions from E24 (`git checkout --theirs`).

---

## ⚠️ REMAINING: Complicated Conflicts (Phase 2)

**13 files require human decision before resolution**

---

### 🔴 Critical Path: Embedding API Divergence (6 files)

#### Files:
1. `src/atman/core/ports/embedding.py` (AA)
2. `src/atman/adapters/memory/mock_embedding.py` (AA)
3. `src/atman/adapters/memory/ollama_embedding.py` (AA)
4. `src/atman/adapters/memory/bm25_embedding.py` (AA)
5. `src/atman/adapters/memory/in_memory_usage_log.py` (AA)

#### Conflict Details:

| Aspect | HEAD (E27) | main (E24) |
|--------|------------|------------|
| **Mock algorithm** | hash-based LCG | SHAKE-128 (SHA-3) |
| **Mock dimension** | 768 | 128 |
| **`EmbeddingPort` API** | Has `model_name()` | Has `similarity()` |
| **Design goal** | Match production (Ollama) | Lightweight testing |

#### Why This Is Complicated:

1. **API Incompatibility**: Code using `model_name()` won't work with E24's port; code using `similarity()` won't work with E27's port.
2. **Downstream Breakage**: Services (`passive_memory_injector.py`, `session_manager.py`) import and use `EmbeddingPort`.
3. **Test Expectations**: Both test suites expect different method signatures.

#### Human Decisions Required:

**Option A** (Recommended): **Extend API with both methods**
```python
class EmbeddingPort(Protocol):
    def embed(self, text: str) -> list[float]: ...
    def model_name(self) -> str: ...          # E27
    def similarity(self, v1, v2) -> float: ... # E24
```
- ✅ Backward compatible
- ⚠️ Requires implementing both methods in all adapters

**Option B**: **Choose one API version**
- E27's `model_name()`: Simpler, matches Ollama
- E24's `similarity()`: More feature-complete, recent review
- ⚠️ Breaks code expecting the other method

**Option C**: **Refactor to separate ports**
- `EmbeddingPort` for embedding generation
- `SimilarityPort` for similarity calculation
- ⚠️ Major refactoring, affects many files

**DECISION NEEDED**: Which option to pursue?

---

### 🔴 Memory Backend Extensions (3 files)

#### Files:
6. `src/atman/core/ports/memory_backend.py` (UU)
7. `src/atman/adapters/memory/file_backend.py` (UU)
8. `src/atman/adapters/memory/in_memory_backend.py` (UU)

#### Conflict Details:

Both branches extended memory backends:
- **E27**: Added reflection-related integration points
- **E24**: Added `FactStatus` enum, salience tracking, `decay_salience()` method

#### Why This Is Complicated:

- **Interleaved changes**: Can't simply pick one side — both feature sets are needed
- **Test dependencies**: Tests expect specific method signatures from both branches

#### Resolution Strategy:

Carefully merge both sets of changes:
1. ✅ Include all E24.1 `FactStatus` lifecycle fields
2. ✅ Include all E27 reflection integration hooks
3. ✅ Ensure method signatures remain backward-compatible

**ACTION REQUIRED**: Manual 3-way merge of these files.

---

### 🔴 Core Data Model (1 file)

#### File:
9. `src/atman/core/models/fact.py` (UU)

#### Conflict Details:

Both branches extended `FactRecord` Pydantic model:
- **E27**: Reflection-related fields
- **E24**: `FactStatus`, `salience`, `confirmation_count`, validators

#### Why This Is Complicated:

- **Pydantic schema**: Field order matters for serialization
- **Validators**: Multiple validators may conflict
- **Database impact**: Schema changes affect PostgreSQL migrations
- **Golden schema tests**: `test_golden_schema.py` expects specific field structure

#### Resolution Strategy:

1. Merge all fields from both branches
2. Ensure Pydantic validators don't conflict
3. Update `test_golden_schema.py` fixture
4. Verify serialization round-trip tests pass

**ACTION REQUIRED**: Manual merge + update golden schema test.

---

### 🔴 Session Manager (1 file)

#### File:
10. `src/atman/core/services/session_manager.py` (UU)

#### Conflict Details:

Both branches modified session lifecycle:
- **E27**: Added reflection checkpoints
- **E24**: Added memory usage tracking, `_facts_read` field in `SessionResult`

#### Why This Is Complicated:

- **Runtime state conflicts**: Different fields in `SessionResult`
- **Lifecycle hooks**: Both added callbacks at session end
- **Type safety**: Pyright errors if fields mismatch

#### Resolution Strategy:

Merge both enhancements:
1. Include `_facts_read` tracking from E24
2. Include reflection checkpoint logic from E27
3. Ensure both can coexist in session lifecycle

**ACTION REQUIRED**: Manual merge of session lifecycle logic.

---

### 🔴 CLI Integration (1 file)

#### File:
11. `src/atman/cli.py` (UU)

#### Conflict Details:

Both branches extended CLI:
- **E27**: Added reflection commands
- **E24**: Added salience decay commands, embedding configuration

#### Why This Is Complicated:

- **Command name collisions**: Potential overlap in command names
- **Help text**: Both modified same regions
- **Config handling**: Different env var expectations

#### Resolution Strategy:

Merge all CLI commands:
1. Ensure no command name collisions
2. Merge help text consistently
3. Make all config options available

**ACTION REQUIRED**: Manual merge of CLI commands.

---

### 🔴 Test Suites (2 files)

#### Files:
12. `tests/test_file_backend.py` (UU)
13. `tests/test_in_memory_backend.py` (UU)

#### Conflict Details:

Both branches added tests for new features:
- **E27**: Reflection integration tests
- **E24**: Salience decay tests, fact lifecycle tests

#### Why This Is Complicated:

- **Fixture conflicts**: Both may modify shared fixtures
- **Assertion conflicts**: Tests expect different return values
- **Coverage**: Both target 90%+, must maintain after merge

#### Resolution Strategy:

Merge all tests:
1. Ensure no duplicate test names
2. Merge fixtures to support both test sets
3. Run full test suite to verify
4. Ensure coverage remains ≥90%

**ACTION REQUIRED**: Manual merge + run test suite.

---

## Recommended Resolution Process

### Phase 2: Resolve Embedding API (Critical Path)

**BLOCKER**: All other conflicts depend on this decision.

1. **Human decision**: Choose Option A, B, or C for `EmbeddingPort` API
2. **Implement chosen option**:
   - If Option A: Extend API, implement in all adapters
   - If Option B: Choose one API version, update consuming code
   - If Option C: Refactor to separate ports
3. **Update imports** in:
   - `passive_memory_injector.py`
   - `session_manager.py`
   - Test files
4. **Run tests**: `pytest tests/test_*embedding* -v`

### Phase 3: Merge Data Models & Backends

5. Manually merge `fact.py` (all fields from both branches)
6. Update `test_golden_schema.py`
7. Manually merge `memory_backend.py` (all methods)
8. Manually merge `file_backend.py` and `in_memory_backend.py`
9. Run: `pytest tests/test_*backend* -v`

### Phase 4: Services & CLI

10. Manually merge `session_manager.py` (all lifecycle hooks)
11. Manually merge `cli.py` (all commands, no collisions)
12. Run: `pytest tests/test_session* tests/test_cli* -v`

### Phase 5: Integration Testing

13. Run full test suite: `make check`
14. Verify coverage ≥90%
15. Fix any type errors: `pyright src/ tests/`
16. Commit merge: `git commit -m "Merge main into E27 — resolve E24/E27 conflicts"`

---

## Risk Assessment

### 🔴 High Risk:
- **EmbeddingPort API change** will break existing code if not handled carefully
- **SessionResult schema change** may break serialization

### 🟡 Medium Risk:
- CLI command collisions
- Test fixture conflicts
- Type checking errors due to API changes

### 🟢 Low Risk:
- Documentation merges (✅ resolved)
- Dependency additions (✅ resolved)
- Identical add/add files (✅ resolved)

---

## Current Status

```
✅ Phase 1 Complete (8/21 files)
⚠️ Phase 2 Blocked: Awaiting human decision on EmbeddingPort API
```

**Files staged for commit** (simple conflicts resolved):
- `docs/architecture/SYSTEM_MAP.md`
- `docs/architecture/SYSTEM_MAP-ru.md`
- `pyproject.toml`
- `uv.lock`
- `src/atman/core/services/conflict_detector.py`
- `src/atman/core/services/emotional_echo.py`
- `src/atman/core/services/passive_memory_injector.py`
- `src/atman/core/services/session_working_memory.py`

**Files requiring manual resolution** (13 remaining):
- `src/atman/core/ports/embedding.py` ⚠️ **BLOCKER**
- `src/atman/adapters/memory/mock_embedding.py`
- `src/atman/adapters/memory/ollama_embedding.py`
- `src/atman/adapters/memory/bm25_embedding.py`
- `src/atman/adapters/memory/in_memory_usage_log.py`
- `src/atman/core/ports/memory_backend.py`
- `src/atman/adapters/memory/file_backend.py`
- `src/atman/adapters/memory/in_memory_backend.py`
- `src/atman/core/models/fact.py`
- `src/atman/core/services/session_manager.py`
- `src/atman/cli.py`
- `tests/test_file_backend.py`
- `tests/test_in_memory_backend.py`

---

## Next Steps

**IMMEDIATE ACTION REQUIRED:**

1. **Human decision**: Choose EmbeddingPort API resolution strategy (Option A/B/C)
2. **Notify team**: E24 and E27 have conflicting implementations — coordination needed
3. **Consider**: Should E27 be rebased on E24 first, then re-applied?

**ALTERNATIVE**: Abort this merge, rebase E27 on latest main, resolve conflicts in smaller chunks.

---

**Report generated by**: Cloud Agent  
**Timestamp**: 2026-05-10 08:40 UTC  
**Branch**: `feature/E27-core-reflections-schema`  
**Target**: `origin/main` (commits `12f947d`, `2453a9f`)
