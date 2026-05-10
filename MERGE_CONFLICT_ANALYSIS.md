# Merge Conflict Analysis: PR #390 ← `origin/main`

**Date**: 2026-05-10  
**Branch**: `devin/1778385933-e0-2-benchmark-runs` (PR #390)  
**Target**: `origin/main` (latest commit: `f380ed9`)

## Executive Summary

**Total conflicts**: 1  
**Simple conflicts**: 1  
**Complex conflicts**: 0  

All conflicts can be automatically resolved.

---

## Conflict Details

### 1. `pyproject.toml` — Lines 43-50 (eval dependencies)

**Classification**: ⚠️ **Intent conflict with clear technical resolution**

#### Context

The conflict involves Python package dependencies for the `[eval]` extra:

**Current branch (HEAD)**:
```toml
"sqlalchemy[postgresql]>=2.0.0",
"psycopg[binary]>=3.2",
"click>=8.1",
```

**origin/main**:
```toml
"sqlalchemy>=2.0.0",
"psycopg2-binary>=2.9.0",
```

#### Root Cause

1. PR #388 originally introduced the eval subsystem with **psycopg3** (`psycopg[binary]>=3.2`)
2. After PR #388 was merged to main, commit `cad8871` rolled back to **psycopg2** due to install concerns:
   > "psycopg2-binary should be installed separately; [postgresql] extra pulls source psycopg2 which requires pg_config at install time."
3. PR #390 branched from the psycopg3 version and continues using it
4. Current branch uses `postgresql+psycopg://` connection string syntax (psycopg3-specific) in `eval/migrations/env.py`

#### Technical Analysis

- **psycopg[binary]>=3.2** uses pre-compiled binaries and **does not require pg_config** at install time
- **psycopg3** is the modern, actively maintained version
- The rollback concern about `[postgresql]` extra requiring pg_config applies to source builds, not binary distributions
- Migration code in PR #390 uses psycopg3 syntax: `postgresql+psycopg://` (not `postgresql+psycopg2://`)

#### Resolution

**Keep HEAD version** (psycopg3):
```toml
"sqlalchemy[postgresql]>=2.0.0",
"psycopg[binary]>=3.2",
"click>=8.1",
```

**Rationale**:
1. `psycopg[binary]` solves the pg_config installation issue
2. psycopg3 is the recommended version for new code
3. Migration infrastructure in PR #390 depends on psycopg3 APIs
4. `click>=8.1` is a new dependency required by eval CLI tooling

---

## Additional Changes in Merge

**Non-conflicting changes** (auto-merged):
- Deleted `MERGE_CONFLICTS_REPORT.md` (temporary file from previous merge)
- Deleted `MERGE_STATUS.md` (temporary file from previous merge)

---

## Recommended Actions

1. ✅ **Resolve** `pyproject.toml` conflict by keeping HEAD version (psycopg3)
2. ✅ **Commit** the resolved merge
3. ✅ **Run** full test suite to confirm psycopg3 compatibility
4. ✅ **Update** PR description to note the dependency evolution
5. ℹ️ **Document** in commit message why psycopg3 supersedes the rollback

---

## Risk Assessment

**Risk level**: 🟢 **Low**

- Change is a dependency upgrade with backward-compatible API
- Binary distribution eliminates pg_config requirement that motivated the rollback
- Migration code explicitly uses psycopg3 connection syntax
- Full test suite will validate compatibility

---

## Validation Checklist

After merge resolution:
- [ ] `ruff check src/ tests/` — 0 errors
- [ ] `ruff format --check src/ tests/` — all files formatted
- [ ] `pyright src/ tests/` — 0 errors
- [ ] `bandit -c pyproject.toml -r src/atman/` — 0 issues
- [ ] `pytest tests/ -v --cov=atman --cov-fail-under=90` — pass ≥90%
- [ ] Migration test: `alembic -c eval/migrations/alembic.ini upgrade head` against pgvector/pg16
