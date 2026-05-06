# GitHub automations

Atman can use GitHub automation again. Automation should protect the prototype without
turning every PR into an expensive or secret-dependent run.

## Enabled now

### CI (`.github/workflows/ci.yml`)

Runs on pull requests targeting `main`, pushes to `main`, and manual dispatch:

1. checks out the repository;
2. installs Python 3.12 and `uv`;
3. installs `.[dev,e2e]` so `make check` can type-check the optional E2E package;
4. runs the required local gate: `make check`.

This covers Ruff linting, Ruff format checks, Pyright, Bandit, and the pytest suite with
coverage enforcement.

### Dependency audit (`.github/workflows/dependency-audit.yml`)

Runs on pull requests targeting `main`, pushes to `main`, weekly schedule, and manual dispatch:

1. installs the project with development dependencies;
2. runs `make audit`, which generates an installed runtime dependency snapshot and checks it
   with `pip-audit`.

The audit now runs in PRs and on `main` so dependency risk is visible before merge and
after landing; the weekly schedule still catches newly disclosed vulnerabilities even without code
changes.

### Dependabot (`.github/dependabot.yml`)

Creates weekly pull requests targeting `main` for:

- GitHub Actions version updates;
- Python dependency metadata in `pyproject.toml`.

## Recommended next automations

1. **Docs/site smoke check** — on changes under `docs/`, `README*`, `MANIFEST*`, or
   `docs/architecture/SYSTEM*`, run `make sync-site-content` and fail if generated
   `docs/content/` copies are stale.
2. **Full corpus demo smoke** — on manual dispatch, and optionally when `e2e/fixtures/**` or
   `src/demo_full_corpus.py` changes, run `make demo-full-corpus-fast` to catch regressions in
   the Session Manager + reflection walkthrough.
3. **Pre-commit mirror** — run `pre-commit run --all-files` as a separate job once the hook set
   is stable, so local and CI formatting/security expectations stay aligned.
4. **GitHub Pages deployment/status** — keep Pages pointed at `/docs`, but add an Actions job
   that validates the static site before deployment if Pages is later moved from branch deploys
   to Actions deploys.
5. **CodeQL or zizmor hardening** — add a security workflow for Python code and GitHub Actions
   workflow linting after baseline CI is green.
6. **Secret-gated fixture generation** — keep LLM-backed fixture generation manual only
   (`workflow_dispatch` + `ANTHROPIC_API_KEY`) and require human review of generated JSON before
   commit.
