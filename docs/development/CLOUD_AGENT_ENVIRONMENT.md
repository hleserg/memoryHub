# Cloud Agent Environment Setup Guide

**Status:** Recommendations for Cursor Cloud Agent environment configuration

**Last Updated:** 2026-04-30

---

## Purpose

This document specifies what should be pre-installed and pre-configured in the Cloud Agent environment to enable faster, more efficient work on the Atman project. It serves as input for environment setup configuration at [cursor.com/onboard](https://cursor.com/onboard).

---

## Current State Analysis

### What's Already Available ✅

The following tools are already present in the base Cloud Agent environment:

- **Python 3.12.3** — matches project requirement (≥3.12)
- **pip 24.0** — standard package manager
- **pytest 9.0.3** — testing framework
- **git 2.x** — version control
- **Basic system tools** — bash, standard GNU utilities

### What Works Out-of-the-Box ✅

The project currently installs successfully with minimal setup:

```bash
pip install -e .        # Installs atman with dependencies
pytest tests/ -v        # All 49 tests pass
python3 -m atman.cli    # CLI runs (interactive mode)
```

**Dependencies automatically installed:**
- `pydantic>=2.0.0`
- `pytest>=7.0.0` (dev)
- `pytest-asyncio>=0.21.0` (dev)

---

## Recommended Pre-installations

### Critical: Package Manager `uv`

**Why:** The project architecture explicitly plans to use `uv` as the package manager (see `SYSTEM.md`, `AGENTS.md`).

**Current issue:** `uv` is not available in the base environment.

**Recommendation:**
```bash
# Add to startup script
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.cargo/bin:$PATH"
```

**Impact:** High — future work packages will likely require `uv` for dependency management.

---

### Optional: Development Tools

The following tools would improve agent productivity but are not strictly required:

#### 1. Python Development Tools

```bash
# Code quality tools (if needed for future linting)
pip install black ruff mypy
```

**Note:** Currently not required — the project has no linters or formatters configured.

#### 2. Markdown Tools

```bash
# For documentation validation (optional)
npm install -g markdownlint-cli
```

**Note:** Low priority — documentation is simple markdown without complex validation needs.

#### 3. JSON/YAML Tools

```bash
# For working with JSONL files (factual memory storage)
pip install jq-py
```

**Note:** Medium priority — file backend uses JSONL format.

---

## Environment Variables

### Not Required Currently

The project does not currently require any environment variables for basic development work.

### Future Requirements (from architecture docs)

When implementation progresses beyond current stage, these will be needed:

```bash
# Runtime configuration (not yet implemented)
ATMAN_ENV=development
ATMAN_LOG_LEVEL=info
ATMAN_STATE_URL=file://./data
ATMAN_MEMORY_BACKEND=file
ATMAN_LLM_PROVIDER=anthropic
ATMAN_EMBEDDING_PROVIDER=openai

# API keys (for integration work)
ANTHROPIC_API_KEY=...
OPENAI_API_KEY=...
```

**Recommendation:** Do not pre-configure these yet. They belong in user secrets, not base image.

---

## File System Pre-configuration

### Working Directory Structure

No special directory structure is required. The project works with:

```
/workspace/              # Standard Cursor workspace
  ├── src/atman/        # Source code
  ├── tests/            # Tests
  ├── docs/             # Documentation
  └── pyproject.toml    # Project config
```

### Data Storage

For development work, agents may create:

```
/workspace/.atman_data/  # Suggested location for file backend storage
```

**Recommendation:** Do not pre-create this directory. Let the application manage it.

---

## Startup Script Recommendations

### Minimal Startup Script

For **immediate needs** (current prototyping stage):

```bash
#!/bin/bash
# Atman Cloud Agent startup script

# Install project in editable mode
cd /workspace
pip install -e . --quiet

# Verify installation
python3 -m atman.cli --version 2>/dev/null || echo "Atman installed"
pytest tests/ -q 2>/dev/null && echo "✅ Tests passing" || echo "⚠️  Tests need attention"
```

### Future-Ready Startup Script

For **future implementation stages** (Experience Store, Identity Store, etc.):

```bash
#!/bin/bash
# Atman Cloud Agent startup script (future-ready)

# Install uv package manager
if ! command -v uv &> /dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$PATH"
fi

# Install project dependencies
cd /workspace
pip install -e . --quiet

# Create data directory if using file backend
mkdir -p /workspace/.atman_data

# Verify installation
python3 -c "import atman; print('Atman version:', atman.__version__ if hasattr(atman, '__version__') else '0.1.0')"
```

---

## Testing the Environment

### Verification Commands

Agents should be able to run these commands successfully:

```bash
# 1. Verify Python version
python3 --version  # Should be >= 3.12

# 2. Install project
pip install -e .

# 3. Run all tests
pytest tests/ -v   # Should show 49 passing tests

# 4. Check CLI
python3 -m atman.cli --help

# 5. Verify imports
python3 -c "from atman.factual_memory import FactualMemory, InMemoryBackend, FileBackend"
```

### Expected Results

All commands should complete without errors. Tests should pass 100%.

---

## What NOT to Pre-install

### ❌ External Services

Do **not** pre-install or configure:

- **mem0** — not yet integrated; will be added as adapter later
- **PydanticAI** — not yet used in codebase
- **APScheduler** — not yet needed (reflection scheduler is future work)
- **Database systems** (PostgreSQL, pgvector, etc.) — not needed for current stage
- **Redis, MongoDB** — not in scope yet

### ❌ Heavy Dependencies

Do **not** pre-install large frameworks that aren't currently used:

- ML/AI frameworks (transformers, torch, etc.)
- Full LLM providers (langchain, llamaindex, etc.)
- Vector databases

### ❌ User-Specific Secrets

Do **not** bake API keys or credentials into the base image. These belong in:

- User secrets (via Cursor Dashboard → Cloud Agents → Secrets)
- Repository-scoped secrets
- Runtime environment variables

---

## Maintenance Notes

### When to Update This Guide

Update this document when:

1. A new work package is implemented (e.g., Experience Store, Identity Store)
2. The project adds new mandatory dependencies
3. Integration with external services becomes required
4. The build system changes (e.g., switching from pip to uv)

### Who Should Review Updates

- Project maintainers before merging environment changes
- Agents implementing new work packages that affect dependencies
- Anyone proposing to add mandatory external services

---

## Quick Reference: Current vs. Future

| Component | Current Stage | Future Stage | Pre-install Now? |
|-----------|---------------|--------------|------------------|
| Python 3.12+ | ✅ Required | ✅ Required | ✅ Already available |
| pip | ✅ Required | ⚠️  Fallback | ✅ Already available |
| uv | ❌ Not used | ✅ Primary | ⚠️  **Recommended** |
| pytest | ✅ Required | ✅ Required | ✅ Already available |
| pydantic | ✅ Required | ✅ Required | ✅ Installed with project |
| mem0 | ❌ Not integrated | ✅ Required | ❌ Wait for integration |
| PydanticAI | ❌ Not used | ✅ Required | ❌ Wait for usage |
| APScheduler | ❌ Not used | ✅ Required | ❌ Wait for implementation |
| LLM providers | ❌ Not used | ✅ Required | ❌ User secrets only |

---

## Conclusion

### Minimal Recommendation (Immediate)

**Add to base image:**
- `uv` package manager installation

**Add to startup script:**
- `pip install -e .` (auto-install project dependencies)

**That's it.** Everything else either works already or should wait for actual implementation needs.

### Rationale

The Atman project is currently in **early prototyping stage** with only the Factual Memory Adapter implemented. Pre-installing tools for future components would be premature optimization.

The environment setup should be **just-in-time**: add tools when they become needed, not before.

### Next Review Trigger

Review this document when:
- Work Package #02 (Experience Store) begins implementation
- Integration with mem0 is started
- LLM provider integration is added
- Reflection Engine requires scheduler setup

---

**For environment setup agent:** Use the "Minimal Recommendation" section above as your configuration input. The startup script should be lightweight and focused on current needs.
