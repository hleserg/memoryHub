# Production / Eval Boundary

This document describes the architectural contract that keeps Atman's evaluation
subsystem isolated from production code, and how to maintain that contract as
the project evolves.

## Why this boundary exists

Atman is a library that other people will install and run. Production users
should pay zero cost for the evaluation infrastructure that benchmarks the
project. Streamlit dashboards, HuggingFace datasets, OpenAI fallback judges,
benchmark harnesses, GPU CI glue — none of it belongs in the runtime an agent
ships with.

But eval also can't be a separate repo: it is too tightly coupled to the
production schema, identity model, and APIs to live elsewhere without
duplicating types and slowing down iteration.

The compromise: **one repo, two install profiles**.

<!-- PLAYBOOK
id: optional-subsystem-isolation
category: architecture-decisions
title: Optional Subsystem Isolation with Extras and Import Boundaries
status: draft
since: 2026-05-11

Pattern: keep a heavy non-runtime subsystem in the same repository but outside
the production dependency graph. Put its dependencies behind an optional extra,
route its code through a clearly named namespace, and enforce one-way imports
with a static boundary check plus install-profile smoke test.

Why generalizable: benchmark, analytics, admin, and migration tooling often need
production schemas without belonging in runtime installs. Optional extras plus
import contracts keep iteration close to the code while avoiding dependency
creep for users.
-->
## The contract

### Install profiles

| Profile | Command | What you get |
|---------|---------|--------------|
| Production | `pip install atman` | Core runtime dependencies from `[project.dependencies]`; no eval canary deps |
| Eval | `pip install "atman[eval]"` | Core + Alembic/SQLAlchemy/PostgreSQL eval storage tooling and future benchmark deps |
| Dev | `pip install "atman[dev]"` | Core + local development tooling and test dependencies |
| Everything | `pip install "atman[all]"` | Core + dev + eval + web/API/e2e extras |

### Module layout

Current production modules use the `core/` + `adapters/` layout. The eval
namespace is intentionally small and optional today; planned benchmark, judge,
runner, and dashboard packages should stay under `src/atman/eval/`.

```
src/atman/
├── core/                    # production domain models, ports, services
├── adapters/                # production adapters for memory, storage, agent, reflection
├── cli*.py                  # production CLI entrypoints
├── tui/                     # development UI entrypoint
├── web_dashboard/           # optional web UI entrypoint
└── eval/                    # NOT production — guarded by lazy import
    ├── __init__.py          # imports _deps_check; raises ImportError without [eval]
    └── _deps_check.py       # canary dependency check
```

### Migration trees

```
migrations/                  # main app schema
└── versions/
    └── 0002_create_facts_table.sql

eval/migrations/             # eval.* schema only
├── alembic.ini
├── env.py
└── versions/
    ├── 0010_create_eval_schema.py
    ├── 0020_create_benchmark_runs.py
    ├── 0030_create_supporting_tables.py
    └── 0040_create_benchmark_trends.py

scripts/eval/
└── partition_manager.py     # partition lifecycle helper for eval.benchmark_runs
```

Apply main migrations with the deployment-specific database procedure; factual
PostgreSQL schema currently lives in `migrations/versions/0002_create_facts_table.sql`.
Apply eval migrations with `make eval-db-init`.

These are independent. Eval Alembic state lives in `alembic_version_eval` and
does not own the production `public` schema.

### Docker

```
docker-compose.yml           # production services (postgres, qdrant, ollama)
docker-compose.eval.yml      # eval-only services (currently empty placeholder)
```

Apply both: `make eval-up` (runs `docker compose -f docker-compose.yml -f docker-compose.eval.yml up -d`)

### One-way dependency rule

**Allowed:**
- `atman.eval.benchmarks.g1` imports from `atman.core.models.identity` (eval reads prod)
- `atman.eval.runner` imports from `atman.adapters.memory.postgres_backend` (eval uses prod)

**Forbidden:**
- `atman.core.services.session_manager` imports from `atman.eval.judge` (prod uses eval) — **NO**
- `atman.adapters.memory.postgres_backend` imports from `atman.eval.benchmarks` — **NO**

Enforced by `import-linter` (configuration in `.importlinter`). `make check`
runs `lint-boundary`, and CI runs `make check` on Python 3.12 PR checks.

## How to add a new module — decision tree

```
Is it needed at runtime by an agent talking to a user?
├── YES → it's production
│         place under src/atman/core/ for domain logic,
│         src/atman/adapters/ for external integrations,
│         or a production entrypoint package/module
│         deps go in [project.dependencies]
│         freely import from other prod modules
│         do NOT import from atman.eval.*
│
└── NO  → it's eval
          place under src/atman/eval/<name>/
          deps go in [project.optional-dependencies] eval = [...]
          may import from atman.* freely
          will not be installed in production
```

Examples:
- New benchmark? → `src/atman/eval/benchmarks/<name>.py`
- New domain service for live agents? → `src/atman/core/services/<name>.py`
- Streamlit visualization? → `src/atman/eval/dashboard/`
- Better embedding cache for production? → `src/atman/adapters/memory/`

## How to add a new dependency

```
Is the dep needed at runtime by an agent talking to a user?
├── YES → [project.dependencies]
│         (be careful — production deps stay forever)
│
└── NO  → [project.optional-dependencies] eval = [...]
          (or `dev` for tooling)
```

After adding a dependency, update `pyproject.toml` and verify the relevant
install profile:

```bash
uv pip install -e .
uv pip install -e ".[eval]"
```

## CI enforcement

Every PR runs:
1. `lint-imports` — verifies prod modules don't import `atman.eval`
2. `make verify-prod-isolation` — installs `atman` in a clean venv, asserts
   no eval deps got pulled, verifies `import atman.eval` fails

Both must pass for merge.

## Local verification

```bash
# Lint check (fast)
make lint-boundary

# Full verification (creates a clean venv, installs, checks)
make verify-prod-isolation

# Eval storage smoke test (requires a PostgreSQL URL accepted by the test env)
make eval-db-test
```

## Known limitations

1. **Lazy/dynamic imports bypass the linter.** If someone writes
   `importlib.import_module("atman.eval.judge")` from a prod module, the
   linter won't catch it. We accept this; reviewer judgment compensates.

2. **Optional-deps don't prevent runtime imports if eval IS installed.**
   If a user did `pip install "atman[eval]"` and then production code
   imports from `atman.eval`, it works at runtime — only the linter catches
   the violation. CI must be the gate.

3. **A single repo can't isolate as strongly as two repos can.** If
   absolute isolation becomes critical (e.g., security audit requires it),
   a future "Variant B" migration to a separate `atman-eval` repo is
   possible. For now, single-repo + linter is the pragmatic balance.

## When to revisit

- Eval grows past ~30% of the codebase by line count → consider splitting to separate repo.
- Eval-deps create install-time conflicts with production deps → split.
- Security/compliance demands cryptographic isolation → split.

Until then, this boundary is the right tool.

