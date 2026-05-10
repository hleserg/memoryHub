# PLAYBOOK Markers Convention

This document defines the syntax and usage rules for **PLAYBOOK markers** — special annotations that AI agents add to source files when they introduce a generalizable engineering pattern.

Markers are automatically extracted by `scripts/extract_playbook.py` and synced to `agent-playbook/raw/extracted-from-atman.md` on every push to `main`.

---

## Purpose

When an AI agent implements code or writes documentation that introduces a pattern applicable beyond this project, it adds a PLAYBOOK marker at the implementation site. The marker travels with the code, not in a separate tracking document.

This approach is designed for a workflow where:
- **Agents write the code** and recognize patterns at the moment of invention
- **The author reviews results asynchronously** and doesn't have time to extract patterns manually
- **Patterns must not require a separate ritual** — they are captured automatically on push

---

## Format for Markdown Files

Use an HTML comment block so the marker does not appear in rendered documentation:

```html
<!-- PLAYBOOK
id: idempotent-long-running-operations
category: design-patterns
title: Idempotent Long-Running Operations via Deterministic Run Keys
status: refined
extends: 06
since: 2026-04-15

Pattern: compute a deterministic run_key from the operation's input parameters.
Before executing side effects, check whether a terminal success event with this
key already exists. If yes — return the existing result. If no — execute and
persist the success event. The operation becomes safe to retry and replay.

Why generalizable: any scheduled job, batch processor, or async pipeline needs
this. Exception-based "just retry" loses context; mutable "update a flag"
creates race conditions. Deterministic keys solve both without distributed locks.
-->
```

Place the comment **immediately before the section** that describes or implements the pattern.

---

## Format for Python Files

Use a `# PLAYBOOK-START` / `# PLAYBOOK-END` block:

```python
# PLAYBOOK-START
# id: optimistic-concurrency-text-documents
# category: design-patterns
# title: Optimistic Concurrency for Text-Layer Updates
# status: draft
#
# Pattern: instead of locking the document on write, callers pass a token
# (last seen updated_at timestamp). On write, compare token to current state;
# on mismatch, return OUTCOME=conflict with current state. Caller decides
# retry or merge.
#
# Why generalizable: locking long-running text edits creates serialization
# stalls in async pipelines. Optimistic concurrency + explicit conflict
# handling is more robust and requires no distributed lock infrastructure.
#
# Trade-offs: callers must handle conflict explicitly (no silent retry).
# PLAYBOOK-END
def update_recent_layer(
    self,
    narrative_id: UUID,
    content: str,
    last_seen_updated_at: datetime,
) -> NarrativeUpdateResult:
    ...
```

Place the block **immediately above** the function, class, or module-level code that implements the pattern.

---

## Field Reference

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Kebab-case unique identifier. Must be unique across all markers in the repo. |
| `category` | Yes | One of: `design-patterns` / `process-patterns` / `architecture-decisions` / `failure-modes` / `templates` |
| `title` | Yes | Human-readable title (used in generated output) |
| `status` | Yes | One of: `draft` / `refined` / `deprecated` |
| `extends` | No | Pattern number this marker extends (e.g. `06` for pattern 06) |
| `since` | No | Date the pattern was first identified (YYYY-MM-DD) |

### Field Values

**`category`:**
- `design-patterns` — technical design decisions: data models, concurrency, idempotency, testing strategies
- `process-patterns` — workflow and coordination patterns (task assignment, review, handoffs)
- `architecture-decisions` — structural choices about component boundaries, ports, adapters
- `failure-modes` — anti-patterns and how to recognize/prevent them
- `templates` — reusable document or code structures

**`status`:**
- `draft` — identified but not yet validated as generalizable; needs author review
- `refined` — validated, well-described, ready for promotion to `patterns/`
- `deprecated` — was a pattern, no longer recommended; kept for historical reference

---

## Where to Place Markers

**Rule:** Place the marker **at the implementation site** — the file and location where the pattern is actually applied. Not in a separate tracking document.

| File type | Placement | Example |
|-----------|-----------|---------|
| Python `.py` | `# PLAYBOOK-START` block immediately above the implementing function or class | Above `def finish_session(...)` in `session_manager.py` |
| Markdown `.md` | HTML comment immediately before the section that describes the pattern | Before `### Operational Contracts` in `reflection-engine/README.md` |

---

## Generalizable vs Project-Specific: the Substitution Test

Before adding a marker, apply the **substitution test**: rewrite the pattern description replacing all project-specific terms (component names, domain concepts). If the result still makes sense as a general engineering practice — it is generalizable. Add a marker.

### Examples that DESERVE a marker

- "Compute a deterministic run key from operation inputs; skip if terminal success event exists"
- "Original records immutable; derived perspectives accumulated in separate append-only list"
- "Abstract LLM calls behind a port; test against deterministic mock that returns template responses"
- "Capture emotional context at event time; mark `incomplete` rather than guessing retrospectively"
- "Structured outcome field instead of exception for predictable non-error results"

### Examples that DO NOT deserve a marker

- "Service uses asyncio" — standard library, not a pattern
- "Tests use pytest fixtures" — framework usage, not a pattern
- "Function returns Pydantic model" — idiomatic, not a pattern
- "`ReflectionEvent` has `identity_snapshot_id` field" — project-specific data model
- Pure refactoring that moves code without introducing new conceptual structure

### When in doubt

Add a marker with `status: draft`. The author will review and either promote to `status: refined` or remove. **Erring on the side of more markers is preferred over missing real patterns.** The author's review filters false positives.

---

## Validation

Run locally:

```bash
make playbook-check
```

This validates all markers without writing any output. Returns exit code 1 if any marker has validation errors (missing required fields, unknown category/status, duplicate IDs).

Run extraction (writes to `../agent-playbook/raw/extracted-from-atman.md`):

```bash
make playbook-extract
```

---

## Setup for Automatic Synchronization

The GitHub Action `.github/workflows/playbook-sync.yml` runs `scripts/extract_playbook.py` on every push to `main` that touches `src/`, `docs/`, or `scripts/extract_playbook.py`. It then commits the updated `extracted-from-atman.md` to `agent-playbook/raw/`.

To enable automatic sync:

1. Go to [github.com/settings/tokens](https://github.com/settings/tokens) and create a **Personal Access Token** (classic) with scope `repo` (write access to `agent-playbook`).
2. In **atman** repo settings → **Secrets and variables** → **Actions** → create a secret named `PLAYBOOK_SYNC_TOKEN` with the token value.
3. Done. On the next push to `main`, markers will be extracted and synced automatically.

If the secret is not set, the workflow step will fail silently (the extraction step succeeds; only the push to `agent-playbook` fails). No code in `atman` is affected.

---

## Periodic Audit (Optional)

To check whether agents have missed adding markers to recent code changes:

```bash
make playbook-audit
```

This runs `scripts/suggest_playbook.py`, which analyzes recent commits through an LLM and suggests where markers should be added. Output is printed to stdout; no files are modified. Default provider: Ollama (free, local). See `scripts/suggest_playbook.py --help` for options.

This is a **manual, on-demand check** — not scheduled. Run it when you want to verify coverage, not as a regular ritual.

---

## Reference: Candidates Awaiting Markers

See `reports/playbook-candidates.md` for the full list of patterns identified in the initial audit but not yet bootstrapped with markers. When working on a listed component, check if the pattern still applies and add a marker at the implementation site.
