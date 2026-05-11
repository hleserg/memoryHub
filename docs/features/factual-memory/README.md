# Factual Memory Adapter

> **Russian:** [README-ru.md](README-ru.md)

Minimal, runnable **factual memory** layer for an Atman agent: one port for storing, reading, and searching **verifiable facts** without interpretations.

## One-command demo

From the repository root (after `pip install -e ".[dev]"`):

```bash
make demo-factual
```

Equivalent: `python3 src/demo.py`. Runs in-memory and file-backed (`/tmp/atman_demo_facts.jsonl`) demos; the temp file is removed at the end. Does not use `~/.atman` for the file demo.

`make demo-factual` sets short pauses between steps by default (`ATMAN_DEMO_PACE=1`). For instant output: `make demo-factual-fast` or `ATMAN_DEMO_PACE=off python3 src/demo.py`. Console UX uses **Rich** via `atman.term` (see **`AGENTS.md`**).

Interactive CLI (default facts file `~/.atman/facts.jsonl`): `python3 -m atman.cli` or console script `atman` if installed.

## Overview

The Factual Memory adapter is the foundation of Atman’s memory stack. It:

- Stores **only facts and relations** (no emotional coloring)
- Keeps `fact.content` separate from any interpretation
- Validates non-empty `content` and `source`
- Runs local-first with file/in-memory backends, and can use PostgreSQL when a
  deployment needs RLS and semantic search

## Requirements

Python ≥ 3.12

## Installation

```bash
git clone https://github.com/hleserg/atman.git
cd atman
uv venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
uv pip install -e ".[dev]"
# Run tools without activating: uv run pytest tests/ -v
# or: pip install -e ".[dev]"
```

Project docs recommend **[uv](https://github.com/astral-sh/uv)** for venv, installs, and `uv run` — see root **`AGENTS.md`** (*uv — рекомендуемый workflow*).

## Quick start

### CLI (interactive)

```bash
atman
# or: python3 -m atman.cli
```

Examples:

```text
atman> add "User asked to implement memory" session_1 task request
atman> search "user" --tags task
atman> recent 5
atman> help
```

### In-memory backend (tests)

```python
from atman.adapters.memory import InMemoryBackend
from atman.core.models import FactRecord

memory = InMemoryBackend()
fact = memory.add_fact(
    FactRecord(
        content="User asked to implement factual memory",
        source="session_2024_01_15",
        tags=["task", "request"],
    )
)
retrieved = memory.get_fact(fact.id)
results = memory.search(query="user")
results = memory.search(tags=["task"])
memory.link(fact.id, other_id, "led_to")
recent = memory.list_recent(limit=10)
```

### File backend (JSONL)

```python
from pathlib import Path

from atman.adapters.memory import FileBackend
from atman.core.models import FactRecord

storage_path = Path.home() / ".atman" / "facts.jsonl"
memory = FileBackend(storage_path)
memory.add_fact(FactRecord(content="Fact", source="test"))
```

### Backend selection

The CLI and shared entrypoints call `atman.config.build_memory_backend()`.
Default selection is the file backend (`~/.atman/facts.jsonl`) so local runs and
tests do not require PostgreSQL.

| Value | Class | Use when |
|-------|-------|----------|
| `file` | `FileBackend` | Local development and demos without external services |
| `inmemory` | `InMemoryBackend` | Fast unit tests and prototypes |
| `postgres` | `PostgresFactualMemory` | Deployments or integration tests that need RLS and SQL storage |

Override for a process:

```bash
ATMAN_MEMORY_BACKEND=postgres DATABASE_URL=postgresql://atman_app:...@localhost:5432/atman atman
```

When constructing the adapter directly, `PostgresFactualMemory` reads the
database URL from the `db_url` argument, `ATMAN_DB_URL`, `DATABASE_URL`, or its
local default, in that order.

### PostgreSQL backend

`PostgresFactualMemory` implements the same `FactualMemory` port using
PostgreSQL, `psycopg3`, `pgvector`, and `pg_trgm`.

Requirements:

- PostgreSQL with `vector` and `pg_trgm` extensions.
- `psycopg[binary]` installed (included in `.[dev]` / `.[eval]`; add it to a
  deployment profile if PostgreSQL is used in production).
- Main factual-memory migration applied:
  `migrations/versions/0002_create_facts_table.sql`.
- Application connections should use the non-superuser `atman_app` role created
  by the migration so row-level security is enforced.

Semantic search is optional:

```python
from atman.adapters.memory.postgres_backend import PostgresFactualMemory
from atman.adapters.memory.ollama_embedding import OllamaEmbeddingAdapter

with PostgresFactualMemory(
    db_url="postgresql://atman_app:...@localhost:5432/atman",
    embedding=OllamaEmbeddingAdapter(),
) as memory:
    results = memory.search(query="concise answers", limit=5)
```

If an `EmbeddingPort` is provided and succeeds, the adapter stores/searches
`halfvec(2560)` embeddings with a cosine HNSW index. If embedding generation is
missing or fails, the adapter emits a warning and falls back to `ILIKE` text
search; facts are still stored.

Row-level security is scoped by `agent_id`. Set `ATMAN_CURRENT_AGENT` before
queries so the adapter can set the PostgreSQL `atman.current_agent` session
variable.

## Architecture

### Models

**FactRecord** — verifiable fact: `id`, `content`, `source`, `tags`, `relations`, `created_at`, `metadata`.

**Relation** — link to another fact: `target_id`, `relation_type`, `created_at`, `metadata`.

### Port `FactualMemory`

```python
class FactualMemory(ABC):
    def add_fact(record: FactRecord) -> FactRecord
    def get_fact(fact_id: UUID) -> FactRecord | None
    def search(query: str | None, tags: list[str] | None, limit: int) -> list[FactRecord]
    def link(source_id: UUID, target_id: UUID, relation_type: str) -> bool
    def list_recent(limit: int) -> list[FactRecord]
```

### Adapters

- **InMemoryBackend** — dict-backed, not persistent; ideal for unit tests (`clear()`, `count()`).
- **FileBackend** — JSON Lines file, load on start, persist on change; no external services.
- **PostgresFactualMemory** — PostgreSQL + RLS; optional embeddings with text-search fallback.

## Testing

```bash
pytest tests/ -v
pytest tests/test_models.py tests/test_in_memory_backend.py tests/test_file_backend.py tests/test_backend_interface.py
pytest tests/integration/test_postgres_facts.py -v  # requires PostgreSQL test URLs
pytest --cov=atman --cov-report=html
```

Key areas: CRUD, search by text/tags, links, `list_recent`, validation, immutability of returned data, FileBackend persistence.

## Scope

**In scope:** facts and relations; validation; tags and metadata; local-first storage.

**Out of scope:** emotional coloring, habits/principles/skills, identity, reflection, mem0/LLM (other work packages build on this layer).

## Extensibility

Future adapters may add graph stores or mem0-backed implementations. Core keeps
depending only on the `FactualMemory` port; optional capabilities such as
PostgreSQL vector search stay behind adapter boundaries.

## Related work packages

Downstream: Experience Store, Identity Store, Reflection Engine, Session Manager — see [`../../development/work-packages/`](../../development/work-packages/).

## Design principles

1. Small, explicit API
2. No dependency on other Atman runtime components
3. New backends implement one port
4. Fully testable without network or API keys
5. Facts ≠ interpretations

## Layout (excerpt)

```text
src/atman/
  cli.py
  core/models/fact.py
  core/ports/memory_backend.py
  adapters/memory/in_memory_backend.py
  adapters/memory/file_backend.py
  adapters/memory/postgres_backend.py
  config.py
migrations/versions/0002_create_facts_table.sql
tests/test_models.py
tests/test_in_memory_backend.py
tests/test_file_backend.py
tests/test_backend_interface.py
tests/integration/test_postgres_facts.py
```

## Related documentation

- Work package: [`../../development/work-packages/01-factual-memory-adapter.md`](../../development/work-packages/01-factual-memory-adapter.md)
- Architecture: [`../../architecture/SYSTEM.md`](../../architecture/SYSTEM.md)
- Development standard: [`../../development/DEVELOPMENT_STANDARD.md`](../../development/DEVELOPMENT_STANDARD.md)

## License

See the repository root.

---

**Status:** MVP ready
**Version:** 0.1.0
