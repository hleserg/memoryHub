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

## The contract

### Install profiles

| Profile      | Command                       | What you get                            |
|--------------|-------------------------------|-----------------------------------------|
| Production   | `pip install atman`           | Core runtime: ~10 deps                  |
| Eval         | `pip install "atman[eval]"`   | Core + ~15 eval-only deps               |
| Dev          | `pip install "atman[dev]"`    | Core + dev tooling                      |
| Everything   | `pip install "atman[all]"`    | Core + eval + dev                       |

### Module layout

```
src/atman/
├── factual_memory/          # production
├── experience_store/        # production
├── reflection_engine/       # production
├── identity_store/          # production
├── skill_loop/              # production
├── session_manager/         # production
├── reality_anchor/          # production
├── proactive_engine/        # production
├── affective_regulation/    # production
└── eval/                    # NOT production — guarded by lazy import
    ├── __init__.py          # imports _deps_check; raises ImportError without [eval]
    ├── _deps_check.py
    ├── runner/              # filled by epic E1
    ├── judge/               # filled by epic E2
    ├── benchmarks/          # filled by epics E5-E20
    └── dashboard/           # filled by epic E4
```

### Migration trees

```
migrations/                  # main app schema
└── versions/

eval/migrations/             # eval.* schema only
├── alembic.ini
├── env.py
└── versions/                # filled by epic E0
```

Apply main migrations: `alembic upgrade head`
Apply eval migrations: `make eval-db-init`

These are independent. `alembic_version` and `alembic_version_eval` tables coexist.

### Docker

```
docker-compose.yml           # production services (postgres, qdrant, ollama)
docker-compose.eval.yml      # eval-only services (currently empty placeholder)
```

Apply both: `make eval-up` (runs `docker compose -f docker-compose.yml -f docker-compose.eval.yml up -d`)

### One-way dependency rule

**Allowed:**
- `atman.eval.benchmarks.g1` imports from `atman.identity_store` (eval reads prod)
- `atman.eval.runner` imports from `atman.factual_memory` (eval uses prod)

**Forbidden:**
- `atman.factual_memory` imports from `atman.eval.judge` (prod uses eval) — **NO**
- `atman.skill_loop` imports from `atman.eval.benchmarks` — **NO**

Enforced by `import-linter` (configuration in `.importlinter`). CI runs
`lint-imports` on every PR.

## How to add a new module — decision tree

```
Is it needed at runtime by an agent talking to a user?
├── YES → it's production
│         place under src/atman/<name>/
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
- New persona feature for live agents? → `src/atman/personas/`
- Streamlit visualization? → `src/atman/eval/dashboard/`
- Better embedding cache for production? → `src/atman/factual_memory/`

## How to add a new dependency

```
Is the dep needed at runtime by an agent talking to a user?
├── YES → [project.dependencies]
│         (be careful — production deps stay forever)
│
└── NO  → [project.optional-dependencies] eval = [...]
          (or `dev` for tooling)
```

After adding, regenerate the lock files:
```bash
pip install -e . && pip freeze > requirements-prod.txt
pip install -e ".[eval]" && pip freeze > requirements-eval.txt
```

Commit both. CI uses these to detect accidental drift.

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

