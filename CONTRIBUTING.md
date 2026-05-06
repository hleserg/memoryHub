# Contributing to Atman

Thanks for your interest in the project. This document is the entry point for humans and agents who want to propose changes.

## Where the rules live

| Topic | Document |
|--------|----------|
| Vulnerability reporting, supported lines | [`SECURITY.md`](SECURITY.md) |
| Repo layout, demos, Rich, `uv`, CI commands | [`AGENTS.md`](AGENTS.md) |
| GitHub Actions, dependency audit, proposed automation | [`docs/development/GITHUB_AUTOMATIONS.md`](docs/development/GITHUB_AUTOMATIONS.md) |
| Terminology, core vs adapters, Definition of Demo | [`docs/development/DEVELOPMENT_STANDARD.md`](docs/development/DEVELOPMENT_STANDARD.md) |
| Architecture | [`docs/architecture/SYSTEM.md`](docs/architecture/SYSTEM.md) |
| Local Cursor agents | [`.cursor/local-agent-master-prompt.md`](.cursor/local-agent-master-prompt.md) |

Follow [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) in all interactions (issues, PRs, discussions).

## Environment

- **Python** ≥ 3.12 (see `pyproject.toml`).
- **Install (editable + dev):** `pip install -e ".[dev]"` or, with **uv**, `uv venv` → `source .venv/bin/activate` → `uv pip install -e ".[dev]"` (or `uv run …` without activating).

## Before you open a PR

1. **Scope:** Prefer focused changes. Match existing style, types, and boundaries (domain logic stays out of presentation-only layers; see `DEVELOPMENT_STANDARD.md`).
2. **Checks:** From the repo root, `make check` must pass (lint, format, typecheck, security, tests with coverage ≥ 90% for `atman`).
   - Individual targets: `make lint`, `make format`, `make typecheck`, `make security`, `make test` (see `Makefile`).
3. **User-visible behavior:** If you add or change CLI, demos, or a feature-sized behavior, follow *Definition of Demo* in `DEVELOPMENT_STANDARD.md` (feature docs under `docs/features/<slug>/`, runnable demo, fixtures if needed, tests).
4. **Docs language:** Canonical docs are **English**. Keep `README-ru.md`, `MANIFEST-ru.md`, `SYSTEM-ru.md`, and paired `README-ru.md` under `docs/features/` in sync when you change the English sources (see `AGENTS.md`).
5. **PR description:** Use [`.github/pull_request_template.md`](.github/pull_request_template.md) as a checklist.

## Commits and messages

- **Commit messages:** English, imperative mood, scoped to what the commit does.

## Questions

Use [README.md](README.md) → **Contact** (email / Telegram) or GitHub issues for project-specific questions.
