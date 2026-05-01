# Pattern: Agent Rules Structure

**Category**: Foundation  
**Complexity**: Medium  
**Impact**: High

## Context

AI agents need clear, structured instructions to work effectively. Traditional documentation (README files, wiki pages, onboarding docs) is designed for human readers and often relies on implicit knowledge, contextual understanding, and ability to ask clarifying questions.

Agents work better with:
- Explicit, unambiguous instructions
- Hierarchical, machine-parseable structure
- Project-specific terminology defined upfront
- Clear boundaries of responsibility

## Problem

How do you organize project documentation so that:
1. Agents can quickly find relevant information
2. Multiple agents use consistent terminology and patterns
3. Standards can be updated without rebuilding agent context
4. Human developers can also use the same documentation

## Solution

Create a hierarchical system of machine-readable documentation with clear separation of concerns:

### 1. AGENTS.md — Environment Context

**Purpose**: Tells agents about the repository, tooling, and how to work with it.

**Contents**:
- Repository overview and current stage
- File structure and key locations
- Build/test/lint commands (or their absence)
- Technology stack
- Environment-specific instructions
- Special considerations (e.g., "no code yet, docs only")

**Example Structure**:
````markdown
# AGENTS.md

## Overview
[Brief description of the project]

## Repository Structure
- `src/` — source code
- `docs/` — documentation
- `tests/` — test files

## Build & Test
```bash
npm install
npm test
npm run build
```

## Technology Stack
- Node.js 20+
- TypeScript 5.3
- React 18

## Special Notes
- Always run tests before committing
- Use conventional commits
````

### 2. DEVELOPMENT_STANDARD.md — Domain Standards

**Purpose**: Establishes project-specific terminology, architecture boundaries, and development contracts.

**Contents**:
- Canonical terminology (glossary)
- Module naming conventions
- Architecture boundaries (core vs adapters, etc.)
- Variable naming standards
- Storage boundaries
- What to avoid (forbidden mixings)
- Definition of done criteria

**Example Structure**:
````markdown
# Development Standard

## Core Terminology

### [DomainConcept1]
Definition and usage rules.

### [DomainConcept2]
Definition and usage rules.

## Naming Conventions

### Modules
- `core/` — domain logic
- `adapters/` — external integrations
- `infra/` — infrastructure concerns

### Variables
Preferred: `user_id`, `session_id`, `created_at`
Avoid: `uid`, `data`, `state` (too generic)

## Forbidden Mixings
- Concept A ≠ Concept B (explain why)
- Don't use X to mean Y

## Definition of Done
- [ ] Uses canonical terminology
- [ ] Has unit tests
- [ ] Runs locally without external services
- [ ] Documentation updated
````

### 3. Cursor Rules (.cursorrules, .mdc files)

**Purpose**: IDE/tool-specific agent behavior configuration.

**Contents**:
- General agent behavior preferences
- Language preferences
- Code style guidelines
- Response format preferences

**Example**:
```markdown
## General Principles
- Always respond in [language]
- Prefer practical solutions over theoretical explanations
- Read files before editing them

## Code Style
- Use existing project patterns
- Add comments in [language] for complex logic
- Follow linter rules
```

## Hierarchy and Synchronization

### Information Flow
```
.cursorrules (general behavior)
    ↓
AGENTS.md (environment & tooling)
    ↓
DEVELOPMENT_STANDARD.md (domain & standards)
    ↓
Architecture docs (detailed design)
```

### Update Strategy
- **Cursor rules**: Update when changing general agent behavior
- **AGENTS.md**: Update when environment/tooling changes
- **Development standard**: Update when discovering new patterns or terminology conflicts
- **Sync direction**: Keep higher levels stable, update lower levels more frequently

## Implementation Guide

### Step 1: Start with AGENTS.md
Create minimal viable context:
```markdown
# AGENTS.md
## Overview
[What is this project in 2-3 sentences]

## Current Stage
[prototype / development / production]

## How to Work Here
[Key commands or "no build system yet"]
```

### Step 2: Add Development Standard When Needed
Create DEVELOPMENT_STANDARD.md when you notice:
- Multiple agents using different terms for same concept
- Confusion about architecture boundaries
- Inconsistent naming across modules
- Repeated questions about "how should I name this?"

### Step 3: Iterate Based on Confusion
When an agent:
- Makes inconsistent choices → Add standard
- Asks for clarification → Make explicit
- Does unexpected thing → Check if documentation is clear

## Anti-Patterns

❌ **Don't**: Put everything in one giant file
- Makes it hard for agents to find relevant sections
- Requires loading more context than needed

❌ **Don't**: Duplicate information across files
- Creates synchronization problems
- Leads to contradictory instructions

❌ **Don't**: Write for humans only
- "Use common sense" doesn't work for agents
- "Follow best practices" is too vague

❌ **Don't**: Over-specify too early
- Creates maintenance burden
- Limits agent autonomy unnecessarily

## Benefits

✅ **Consistency**: All agents use same terminology and patterns  
✅ **Efficiency**: Agents find relevant information quickly  
✅ **Quality**: Fewer misunderstandings and rework cycles  
✅ **Scalability**: Easy to onboard new agents  
✅ **Maintainability**: Standards evolve with the project  

## Real-World Example

In a multi-component architecture project:
- 7 agents working on different components
- Each component had different storage boundaries
- Without standards: agents mixed "facts" and "experiences" inconsistently
- After adding DEVELOPMENT_STANDARD.md with explicit definitions:
  - Terminology became consistent
  - Architecture boundaries stayed clean
  - Code review became faster

## Variations

### Minimal (Small Projects)
- Just AGENTS.md with basic context
- Standards emerge organically

### Standard (Most Projects)
- AGENTS.md + DEVELOPMENT_STANDARD.md
- Clear separation of concerns

### Complex (Large/Multi-Agent Projects)
- AGENTS.md + DEVELOPMENT_STANDARD.md
- Additional domain-specific standards documents
- Work package specifications for parallel development

## Related Patterns

- [Issue-to-PR Workflow](02-issue-to-pr-workflow.md) — Uses these rules in task descriptions
- [Strategic Review](03-strategic-review.md) — Validates adherence to standards
- [Context Handoff](05-context-handoff.md) — References these as canonical sources

## References

- [Cursor Rules Documentation](https://docs.cursor.com/)
- [Architecture Decision Records](https://adr.github.io/)

---

**Status**: Stable  
**Last Updated**: 2026-04-30
