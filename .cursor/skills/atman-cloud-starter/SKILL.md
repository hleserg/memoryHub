---
name: atman-cloud-starter
description: Practical setup, run, and testing guide for Cursor Cloud agents working in the Atman repository.
---

# Atman Cloud agent starter

Use this skill when a Cloud agent needs to run, test, or extend this repository. It consolidates `AGENTS.md`, `README.md`, `MANIFEST.md`, `docs/architecture/SYSTEM.md`, `docs/development/DEVELOPMENT_STANDARD.md`, the current Python package config, implementation docs, and the Cursor issue workflow.

## 1. Reality check first

- `AGENTS.md` still says the repo is documentation-only and has no tests or dependencies. Treat that as historical context, then verify the current tree.
- Current runnable code exists: `pyproject.toml`, `src/atman/`, `tests/`, `src/demo.py`, `src/test_cli.sh`, and `src/full_demo.sh`.
- Project goal: Atman is a psychological layer for AI agents, not a task runner. It is meant to preserve identity, lived experience, reflection, skills, and narrative continuity across sessions.
- Main implemented area today: Factual Memory Adapter v0.1.0.
- Primary documentation language is English. Keep paired Russian docs in sync only for paired files listed in `AGENTS.md`: `README.md` / `README-ru.md`, `docs/architecture/SYSTEM.md` / `docs/architecture/SYSTEM-ru.md`, `MANIFEST.md` / `MANIFEST-ru.md`.

## 2. Cloud setup and login

- No application login is needed for local runs.
- In Cursor Cloud, `gh` is usually already authenticated for read-only inspection. Use it for viewing PRs, issues, and workflow logs only.
- Do not require mem0, OpenClaw, real LLM providers, API keys, internet, or external services for tests.
- For GitHub Actions Cursor issue intake, the workflow expects `CURSOR_API_KEY` in repository secrets and installs Cursor CLI inside Actions. Local Cloud agents should not try to create or rotate that secret.
- Python requirement: `>=3.12`.

Setup commands:

```bash
python3 --version
python3 -m pip install -e ".[dev]"
```

If `uv` is available, this is also valid:

```bash
uv pip install -e ".[dev]"
```

## 3. Environment, feature flags, and mocks

- Implemented tests should run with in-memory or file adapters.
- If mem0 is missing, use file/in-memory storage in dev or return an explicit degraded status.
- If an LLM is missing, skip reflection work but preserve session results.
- Planned runtime config names from the development standard: `ATMAN_ENV`, `ATMAN_LOG_LEVEL`, `ATMAN_STATE_URL`, `ATMAN_MEMORY_BACKEND`, `ATMAN_LLM_PROVIDER`, `ATMAN_EMBEDDING_PROVIDER`.
- These environment variables are architectural guidance; do not assume every variable is wired in current code.
- Personality state does not belong in `.env`: identity, narrative, principles, relationships, and uncertainty are domain state.
- Required fake components for future modules: `InMemoryMemoryBackend`, `InMemoryStateStore`, `FakeLLMProvider`, `FrozenClock`, `FakeIntegrationAdapter`.

## 4. Codebase areas and workflows

### Factual Memory core and adapters

Area:

- `src/atman/core/models/fact.py`
- `src/atman/core/ports/memory_backend.py`
- `src/atman/adapters/memory/in_memory_backend.py`
- `src/atman/adapters/memory/file_backend.py`
- `tests/test_models.py`, `tests/test_in_memory_backend.py`, `tests/test_file_backend.py`, `tests/test_backend_interface.py`

What exists:

- `FactRecord` and `Relation`.
- `FactualMemory` port.
- In-memory backend for unit tests.
- JSONL file backend for local persistence.
- No emotional coloring, identity, habits, principles, skills, or reflection in this package.

Test workflow:

```bash
python3 -m pytest tests/test_models.py tests/test_in_memory_backend.py tests/test_file_backend.py tests/test_backend_interface.py -v
```

Use this workflow after touching models, ports, search behavior, relations, immutability, or JSONL persistence.

### CLI and local manual smoke checks

Area:

- `src/atman/cli.py`
- `src/demo.py`
- `src/test_cli.sh`
- `src/full_demo.sh`

Run the CLI:

```bash
python3 -m atman.cli
```

Manual CLI commands:

```text
add "User asked to implement factual memory" session_1 task request
search "User" --tags task
recent 5
exit
```

Non-interactive smoke checks:

```bash
PYTHONPATH=src python3 src/demo.py
bash src/test_cli.sh
```

Use a temporary file or `/tmp` path when testing `FileBackend`. The CLI default is `~/.atman/facts.jsonl`; avoid committing or relying on that local state.

### GitHub Actions Cursor issue intake

Area:

- `.github/workflows/cursor-issue-intake.yml`
- `tests/test_cursor_issue_intake_workflow.py`

What it does:

- Runs when an issue is labeled `cursor-ready` or via `workflow_dispatch`.
- Resolves issue context, builds a Cursor prompt, installs Cursor CLI, runs `agent -p --trust --force`, uploads the patch, then finalizes in a trusted job.
- The trusted finalization creates branch `cursor/issue-${ISSUE_NUMBER}-${RUN_ID}`, commits, pushes, opens a PR, and comments on the issue.
- Tests assert checkout credential handling, tokenized origin setup before push, and `CURSOR_API_KEY` scoping.

Test workflow:

```bash
python3 -m pytest tests/test_cursor_issue_intake_workflow.py -v
```

Use this workflow after editing the workflow YAML or issue-intake automation.

### Architecture and development docs

Area:

- `MANIFEST.md`, `MANIFEST-ru.md`, `MANIFEST.en.md`
- `docs/architecture/SYSTEM.md`, `docs/architecture/SYSTEM-ru.md`, related drafts
- `docs/development/DEVELOPMENT_STANDARD.md`
- `docs/development/work-packages/`
- `docs/research/`, `docs/ideas/`

Key rules from the docs:

- Keep Core independent from mem0, OpenClaw, specific LLMs, schedulers, and concrete workspace layouts.
- Core contains domain models, transitions, snapshots, lifecycle, governance, audit, and migrations.
- Adapters translate between Core and external systems such as mem0, OpenClaw, Cursor, Docker, HTTP APIs, or LLM providers.
- Minimal runtime path has priority: `start_session -> build_personality_snapshot -> deliver_snapshot_to_agent -> agent work -> capture_session_events -> end_session -> write_eigenstate -> update_recent_narrative -> next start_session uses updated narrative first`.
- Do not mix Fact, Experience, Reflection, Identity, Skill, Habit, Principle, Narrative, Summary, or Adapter responsibilities.
- Persistable structures need `schema_version`.
- Tests must not require real API keys, mem0 server, OpenClaw workspace, or internet.
- New architecture decisions need an ADR if they add mandatory services, change storage boundaries, change session/reflection lifecycle, change `PersonalitySnapshot`, introduce breaking persistent schema changes, or alter deployment.
- Research docs are context, not direct implementation orders. Current research frames Atman as Facts + Reflection + Skills + Identity continuity, with separate factual, reflective, skill, and identity loops.
- Ideas docs capture future operational blocks such as Control Room, observability/audit, governance, sandboxing, onboarding, relationships, benchmarks, and disaster recovery.

Docs-only test workflow:

```bash
git diff --check
```

If docs describe runnable behavior, also run the relevant command from the documented area.

### GitHub metadata and templates

Area:

- `.github/pull_request_template.md`
- `.github/ISSUE_TEMPLATE/bug_report.md`
- `.github/ISSUE_TEMPLATE/feature_request.md`
- `.github/DISCUSSION_TEMPLATE/general.yml`

Workflow:

- Use the PR template sections: what changed, type of change, checklist, notes.
- Mark documentation changes as `Новая возможность / документация`.
- Keep issue/discussion templates aligned with the repository's bilingual documentation style when editing them.

Test workflow:

```bash
git diff --check -- .github
python3 -m pytest tests/test_cursor_issue_intake_workflow.py -v
```

Use the pytest command only when workflow automation behavior changes.

### Reports and session notes

Area:

- `reports/sessions/TEMPLATE.md`
- `reports/sessions/README.md`
- `reports/IMPLEMENTATION_REPORT.md`

Workflow:

- Use filenames like `YYYY-MM-DD_HHMM_session-<session-id>.md`.
- Include timestamp, session id/key, topic, key metrics, decisions, and follow-ups.
- Track metrics such as time to resolution, corrected errors, context retained without reminder, premature conclusions, and practical action ratio.
- Use reports for structured session outcomes. Do not place implementation reports in the repository root.

Test workflow:

```bash
git diff --check -- reports
```

## 5. Whole-repo validation

**Mandatory checks before completing any coding task** (all must pass with zero errors):

```bash
ruff check src/ tests/                                    # lint
ruff format --check src/ tests/                           # format
pyright src/ tests/                                       # type check (standard mode)
bandit -c pyproject.toml -r src/atman/                    # security
python3 -m pytest tests/ -v --cov=atman --cov-fail-under=90  # tests + coverage ≥90%
```

Do not commit code that fails any of these checks. If a check produces a false positive on an intentional pattern, add an exception to `pyproject.toml` configuration rather than ignoring the error.

For faster test runs during development, use parallel execution:

```bash
pytest tests/ -n auto
```

All checks can be run at once with `make check`. For a full run including dependency audit: `make all`.

Additional validation:

```bash
git diff --check
```

Optional demonstration path for the implemented adapter:

```bash
PYTHONPATH=src python3 src/demo.py
bash src/test_cli.sh
```

`src/full_demo.sh` is useful as a human-facing demo, but it uses commands such as `tree`, `find`, and `grep`; prefer the focused commands above for Cloud-agent validation.

## 6. Before implementing a new module

Answer these in the PR body or working notes:

- Which domain object changes?
- Is it Core or Adapter?
- Which ports are used?
- Which persistent structures appear?
- What is the `schema_version`?
- Which invariants are protected by tests?
- How does it run without external services?
- What is the degraded mode?
- Is audit needed?
- Is a governance decision needed?
- How does it affect deployment?

Recommended implementation order:

1. Core models, ports, and fake adapters.
2. `PersonalitySnapshot` builder.
3. Minimal session start/end.
4. Narrative recent layer update.
5. File/local `StateStore` with schema versions.
6. `MemoryBackend` adapter boundary, then mem0 adapter.
7. CLI doctor/health/export/import.
8. OpenClaw integration adapter.
9. Micro reflection.
10. Audit trail.
11. Identity snapshots.
12. Daily/deep reflection.
13. Reality/Affect.
14. Skill Manager.
15. Ambient/Proactive.
16. Admin/Control Room.

## 7. Updating this skill

Update this file whenever a Cloud agent discovers a repeatable setup or testing trick:

- Add the exact command that worked.
- Name the codebase area it applies to.
- Mention required environment variables, secrets, or mocks.
- Record failures that indicate missing external services separately from real code failures.
- Keep instructions minimal and immediately executable.
- If `AGENTS.md`, README files, architecture docs, or development docs change, re-check this skill for drift in the same PR.
