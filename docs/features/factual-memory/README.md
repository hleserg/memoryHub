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
- Stays extensible toward embeddings / graph memory (without requiring them today)

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

```
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

## Testing

```bash
pytest tests/ -v
pytest tests/test_models.py tests/test_in_memory_backend.py tests/test_file_backend.py tests/test_backend_interface.py
pytest --cov=atman --cov-report=html
```

Key areas: CRUD, search by text/tags, links, `list_recent`, validation, immutability of returned data, FileBackend persistence.

## Scope

**In scope:** facts and relations; validation; tags and metadata; local-first storage.

**Out of scope:** emotional coloring, habits/principles/skills, identity, reflection, mem0/LLM (other work packages build on this layer).

## Extensibility

Future adapters may add vector search (`FactualMemory` subclass), graph stores, or mem0-backed implementations — Core keeps depending only on the port.

## Related work packages

Downstream: Experience Store, Identity Store, Reflection Engine, Session Manager — see [`../../development/work-packages/`](../../development/work-packages/).

## Design principles

1. Small, explicit API  
2. No dependency on other Atman runtime components  
3. New backends implement one port  
4. Fully testable without network or API keys  
5. Facts ≠ interpretations  

## Layout (excerpt)

```
src/atman/
  cli.py
  core/models/fact.py
  core/ports/memory_backend.py
  adapters/memory/in_memory_backend.py
  adapters/memory/file_backend.py
tests/test_models.py
tests/test_in_memory_backend.py
tests/test_file_backend.py
tests/test_backend_interface.py
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
