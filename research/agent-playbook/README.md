# Agent Playbook

**Universal patterns and practices for AI agent-driven software development**

> **Note**: This playbook is maintained in the `research/agent-playbook/` directory as a standalone resource. It documents universal patterns derived from real project experience but is not project-specific. For project-specific development standards, refer to the main project documentation.

## What is this?

This repository contains battle-tested patterns, workflows, and governance structures for managing software projects where AI agents are primary contributors. These patterns emerged from real-world experience managing multiple autonomous agents working in parallel on complex architectural projects.

## Why does this exist?

Modern AI agents are capable of sophisticated development work, but traditional development workflows don't account for their unique characteristics:
- Agents can lose system-level context while optimizing local details
- Parallel agent work requires explicit coordination mechanisms
- Human oversight needs to shift from direct supervision to strategic review
- Machine-readable standards enable better agent alignment than prose documentation

This playbook provides proven solutions to these challenges.

## Who is this for?

- **Engineering leaders** orchestrating AI agent teams
- **Individual developers** delegating work to AI agents
- **AI researchers** studying agent collaboration patterns
- **DevOps engineers** setting up agent-friendly environments

## Quick Start

1. **Start with the basics**: Read [Agent Rules Structure](patterns/01-agent-rules-structure.md) to understand how to organize machine-readable documentation
2. **Set up workflows**: Implement [Issue-to-PR Workflow](patterns/02-issue-to-pr-workflow.md) for agent task management
3. **Add governance**: Use [Strategic Review Patterns](patterns/03-strategic-review.md) to maintain system coherence
4. **Scale safely**: Apply [Environment Isolation](patterns/04-environment-isolation.md) for parallel development

## Pattern Catalog

### Core Patterns
- **[01: Agent Rules Structure](patterns/01-agent-rules-structure.md)** — Organizing machine-readable standards and context
- **[02: Issue-to-PR Workflow](patterns/02-issue-to-pr-workflow.md)** — Managing agent work without direct access
- **[03: Strategic Review](patterns/03-strategic-review.md)** — Human oversight for autonomous agents
- **[04: Environment Isolation](patterns/04-environment-isolation.md)** — Safe parallel agent development
- **[05: Context Handoff](patterns/05-context-handoff.md)** — Transferring knowledge between agents

### Supporting Patterns
- **[Definition of Done for Agents](guides/definition-of-done.md)** — Setting clear completion criteria
- **[Common Agent Failure Modes](guides/failure-modes.md)** — Recognizing and preventing typical issues

## Templates

Pre-built templates ready to adapt to your project:
- [AGENTS.md template](templates/AGENTS.md) — Core agent instructions
- [DEVELOPMENT_STANDARD.md template](templates/DEVELOPMENT_STANDARD.md) — Project-specific standards
- [Issue templates](templates/issue-templates/) — Agent-optimized task descriptions
- [PR template](templates/pr-template.md) — Structured change documentation

## Core Principles

### 1. Explicit over Implicit
Agents work best with explicit, structured information. Implicit tribal knowledge creates confusion and inconsistent behavior.

### 2. Machine-Readable Standards
Documentation that agents can parse and reference precisely is more effective than prose guidelines they must interpret.

### 3. Strategic Human Oversight
Humans should focus on system-level coherence and architectural decisions, not micro-managing implementation details.

### 4. Isolation Enables Parallelism
Clear boundaries allow multiple agents to work simultaneously without conflicts or coordination overhead.

### 5. Context is Expensive
Design workflows that minimize context transfer needs between agents and between sessions.

## Project Structure

```
agent-playbook/
├── README.md                 # This file
├── patterns/                 # Core pattern documentation
│   ├── 01-agent-rules-structure.md
│   ├── 02-issue-to-pr-workflow.md
│   ├── 03-strategic-review.md
│   ├── 04-environment-isolation.md
│   └── 05-context-handoff.md
├── guides/                   # Supporting guides
│   ├── definition-of-done.md
│   └── failure-modes.md
└── templates/               # Ready-to-use templates
    ├── AGENTS.md
    ├── DEVELOPMENT_STANDARD.md
    ├── pr-template.md
    └── issue-templates/
```

## Contributing

These patterns emerged from real projects and are continuously refined. If you have:
- **Success stories** using these patterns
- **New patterns** from your agent workflows
- **Improvements** to existing patterns
- **Different contexts** where patterns need adaptation

Please share your experience through issues and pull requests.

## License

MIT License — use freely in commercial and open-source projects.

## Acknowledgments

These patterns emerged from developing a complex multi-component AI agent architecture with parallel autonomous agents, managed entirely through GitHub workflows.

---

**Version**: 0.1.0  
**Status**: Initial Draft  
**Last Updated**: 2026-04-30
