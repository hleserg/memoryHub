# .cursor/ Directory

This directory contains Cursor IDE specific files and configurations for the Atman project.

## Contents

### `local-agent-master-prompt.md`

**Master prompt for local Cursor agents** (not cloud agents).

This file provides:
- Complete workflow guidelines
- Links to all essential documentation  
- Terminology discipline rules
- Architecture boundaries (Core vs Adapters)
- Definition of Done checklist
- Forbidden actions and common pitfalls

**Usage**: Local agents should read this file before starting any work to ensure they follow the same standards as cloud agents.

**Version**: See file header for current version and last update date.

### `SYNC_GUIDE.md`

**Synchronization guide** for keeping the master prompt aligned with project standards.

Describes:
- What to sync (which sections from `DEVELOPMENT_STANDARD.md`)
- When to sync (triggers and frequency)
- How to sync (step-by-step process)
- Maintenance log

**Audience**: Maintainers and agents responsible for updating the master prompt.

## Why This Directory?

`.cursor/` is the standard location for Cursor IDE specific files. It keeps:
- IDE configuration separate from project code
- Agent instructions accessible but non-intrusive
- Sync documentation discoverable

## Related Files

- [`/workspace/AGENTS.md`](../AGENTS.md) — Cloud agent instructions (auto-injected)
- [`/workspace/docs/development/DEVELOPMENT_STANDARD.md`](../docs/development/DEVELOPMENT_STANDARD.md) — Source of truth for all standards
- [`/workspace/docs/architecture/SYSTEM.md`](../docs/architecture/SYSTEM.md) — Complete system architecture

## For Cloud Agents

If you're a cloud agent, you don't need this directory. You receive instructions via `AGENTS.md` automatically. This directory is specifically for **local agents** to ensure workflow parity.
