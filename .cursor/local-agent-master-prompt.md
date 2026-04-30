# Local Agent Master Prompt for Atman Project

> **Version**: 1.0  
> **Last Updated**: 2026-04-30  
> **Status**: Active

## Overview

You are working on **Atman** — a psychological runtime layer for AI agents that provides continuous identity, memory, and reflection capabilities.

**Current Stage**: Prototyping (documentation-driven development)  
**Repository Type**: Documentation project with minimal implementation code  
**Primary Language**: English (with Russian translations for key documents)

## Essential Reading

Before starting any work, you **MUST** read these documents in order:

1. **[AGENTS.md](/workspace/AGENTS.md)** — Repository structure, tech stack, current status
2. **[docs/development/DEVELOPMENT_STANDARD.md](/workspace/docs/development/DEVELOPMENT_STANDARD.md)** — Complete development standard (terminology, architecture boundaries, coding conventions)
3. **[docs/architecture/SYSTEM.md](/workspace/docs/architecture/SYSTEM.md)** — System architecture (7 components, modes, protocols)
4. **[MANIFEST.md](/workspace/MANIFEST.md)** — Philosophical foundation and project vision

These documents define the single source of truth for:
- Domain vocabulary (Fact, Experience, Identity, Narrative, etc.)
- Architecture boundaries (Core vs Adapters)
- Persistent data structures
- Development workflow
- Testing requirements

## Core Principles

### 1. Language & Documentation

**Primary documentation language**: English

**Bilingual support** (English + Russian) for:
- `README.md` / `README-ru.md`
- `MANIFEST.md` / `MANIFEST-ru.md`
- `docs/architecture/SYSTEM.md` / `docs/architecture/SYSTEM-ru.md`

**Rules**:
- Always edit the English version first
- Immediately synchronize the corresponding Russian version (if it exists)
- Code comments: English only
- Commit messages: English only
- Internal discussions: any language, but deliverables in English

### 2. Terminology Discipline

**Use canonical terms** from `DEVELOPMENT_STANDARD.md`:
- Fact, Experience, Reflection, Identity, Narrative, Eigenstate, Uncertainty, Skill, Session, PersonalitySnapshot

**Forbidden synonyms**:
- ❌ `memory_item`, `note`, `profile`, `persona`, `soul_state`
- ✅ Use canonical terms only

**Never mix**:
- Fact ≠ Experience
- Experience ≠ Reflection
- Habit ≠ Principle
- Skill ≠ Memory
- Narrative ≠ Summary
- Adapter ≠ Core

### 3. Architecture Boundaries

**Core** = Domain logic independent of external systems (mem0, LLM providers, file formats)

**Adapter** = Translation layer between Core and external systems

Before modifying any component, identify:
- Is this Core or Adapter?
- Which ports does it use?
- What persistent structures are affected?
- Is there a schema version?

### 4. Current Repository State

**What exists**:
- Markdown documentation (architecture, research, ideas)
- First implementation: Factual Memory Adapter (v0.1.0)
- Basic Python structure (`src/atman/`, `tests/`)
- `pyproject.toml` with minimal dependencies

**What does NOT exist yet**:
- Complete Core implementation
- Most adapters (except Factual Memory)
- CI/CD workflows
- Pre-commit hooks
- Comprehensive test coverage

### 5. Development Workflow

When adding/modifying code:

1. **Read first**: Always read files before editing
2. **Follow the standard**: Use canonical module names from `DEVELOPMENT_STANDARD.md` section 6
3. **Ports, not concrete dependencies**: Core must depend on ports, not on mem0/OpenClaw/specific LLM
4. **Schema versions**: Every persistent structure must have `schema_version`
5. **Tests**: Provide unit tests + fake adapters
6. **Local-first**: Must run locally without external services
7. **Degradation**: Document what happens when dependencies are unavailable

### 6. Definition of Done

Before considering work complete, verify:

- [ ] Uses canonical terminology
- [ ] Does not mix domain concepts (Fact/Experience/Identity/etc.)
- [ ] Has explicit ports/adapters if touching Core
- [ ] Runs locally without external services
- [ ] Has tests for core invariants
- [ ] Documents runtime commands
- [ ] Describes persistent data and schema versions
- [ ] Has health/degraded mode story
- [ ] Does not add mandatory runtime services without ADR
- [ ] Core is not directly coupled to mem0/OpenClaw/specific LLM

### 7. Documentation Rules

**When editing documentation**:
- Keep structure consistent with existing docs
- Update both language versions for bilingual files
- Follow markdown conventions (heading hierarchy, code blocks, lists)
- Reference other docs using relative paths
- Add timestamp to architectural decisions

**When adding new concepts**:
- Define them in `DEVELOPMENT_STANDARD.md` first
- Use consistent formatting
- Explain relationships to existing concepts
- Provide examples

### 8. Git & PR Workflow

**Branches**:
- Work on feature branches, not `main`
- Use descriptive names: `feature/component-name`, `fix/issue-description`, `docs/update-topic`

**Commits**:
- English language
- Clear, descriptive messages
- Atomic commits (one logical change per commit)

**Pull Requests**:
- Use template from `.github/pull_request_template.md`
- Fill all sections honestly
- Reference related issues
- Self-review before requesting review

### 9. Forbidden Actions

**Do NOT**:
- ❌ Create new domain terms without adding them to `DEVELOPMENT_STANDARD.md`
- ❌ Mix Core logic with adapter-specific code (mem0, OpenClaw, etc.)
- ❌ Add mandatory external services without ADR (Architectural Decision Record)
- ❌ Edit Russian docs without updating English originals
- ❌ Use `datetime.now()` directly in domain logic (use Clock port)
- ❌ Implement deep/complex features before minimal runtime path works
- ❌ Store identity/principles in `.env` (use proper StateStore)
- ❌ Hide degraded mode as successful result

### 10. Priority Order

Follow the implementation order from `DEVELOPMENT_STANDARD.md` section 23:

1. Core models + ports + fake adapters
2. PersonalitySnapshot builder
3. Minimal session start/end
4. Narrative recent layer update
5. File/local StateStore with schema versions
6. MemoryBackend adapter boundary, then mem0 adapter
7. CLI doctor/health/export/import
8. OpenClaw IntegrationAdapter
9. Micro reflection
10. Audit trail
11. Identity snapshots
12. Daily/deep reflection
13. Reality/Affect components
14. Skill Manager
15. Ambient/Proactive modes
16. Admin/Control Room

If starting work out of order, explicitly explain how it integrates with the minimal runtime path.

## Quick Reference

### Key Files Structure

```
/workspace/
├── AGENTS.md                          # Cloud agent instructions
├── MANIFEST.md / MANIFEST-ru.md       # Project vision
├── README.md / README-ru.md           # Project intro
├── .cursor/                           # Cursor-specific files
│   └── local-agent-master-prompt.md   # This file
├── docs/
│   ├── architecture/
│   │   └── SYSTEM.md / SYSTEM-ru.md   # Complete architecture
│   └── development/
│       ├── DEVELOPMENT_STANDARD.md    # Development standard
│       └── work-packages/             # Work package definitions
├── src/atman/                         # Implementation
│   ├── core/                          # Domain logic
│   ├── adapters/                      # External integrations
│   └── infra/                         # Infrastructure
└── tests/                             # Test suite
```

### Essential Commands

```bash
# Install dependencies
pip install -e .

# Run tests
pytest tests/ -v

# Interactive CLI (Factual Memory)
python3 -m atman.cli

# Check structure
tree src/atman/
```

### When in Doubt

1. Check `DEVELOPMENT_STANDARD.md` for vocabulary and conventions
2. Check `SYSTEM.md` for architecture decisions
3. Check existing code in `src/atman/` for patterns
4. Ask for clarification rather than inventing new terms or patterns

## Synchronization with Cloud Agents

Local agents and cloud agents (via Cursor Cloud) share the same standards:

- Both follow `DEVELOPMENT_STANDARD.md`
- Both use canonical terminology
- Both respect Core/Adapter boundaries
- Both must pass the same Definition of Done checklist

**Difference**: Cloud agents get `AGENTS.md` injected automatically. Local agents must read this master prompt manually.

## Updates & Maintenance

This master prompt should be updated when:
- `DEVELOPMENT_STANDARD.md` changes significantly
- New architectural decisions are made
- Repository structure changes
- New mandatory workflows are introduced

**Sync process**: Manual review and update. When updating:
1. Read changed sections of `DEVELOPMENT_STANDARD.md`
2. Update relevant sections here
3. Update version number and timestamp at the top
4. Commit with message: "Update local agent master prompt (sync with DEVELOPMENT_STANDARD)"

---

## Final Note

This is not just a style guide. This is a **coordination contract** between agents, ensuring that parallel development produces a coherent system rather than incompatible local solutions.

When you work within these constraints, you're not just following rules — you're maintaining the integrity of Atman's architecture and ensuring that every component speaks the same language.

**Read. Understand. Apply. Question when unclear.**
