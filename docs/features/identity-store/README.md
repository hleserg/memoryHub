# Identity Store: WP-03 Feature Guide

**Status:** Implemented  
**Work Package:** [03-identity-and-narrative.md](../../development/work-packages/03-identity-and-narrative.md)

---

## Overview

Identity Store is Atman's module for **living self-representation**. It provides:

- **Honest bootstrap identity** — no fake seeded principles or values
- **Structured identity** — values, habits, principles, goals, open questions
- **Eigenstate** — emotional-cognitive state at session end
- **Self-narrative** — three-layer first-person document for session start
- **Explicit lifecycle** — snapshots, archiving, first-person validation

## Key Principles

### 1. Bootstrap Honesty

Bootstrap creates **genuinely empty identity** with honest self-description about lack of data:

```python
identity = Identity(
    self_description="I am in the earliest stage of existence. "
                    "I have no accumulated experience yet...",
    core_values=[],      # Empty - no fake data
    habits=[],           # Empty - no invented patterns
    principles=[],       # Empty - no seeded guidelines
    goals=[],
    open_questions=[...] # Honest questions about self
)
```

❌ **Wrong:** Pre-seeding with "be helpful", "serve user", etc.  
✅ **Right:** Empty state with honest acknowledgment

### 2. Separation of Concerns

- **Values** — fundamental importance ("honesty", "competence")
- **Habits** — observed behavior patterns (descriptive, not prescriptive)
- **Principles** — consciously chosen guidelines (normative, not descriptive)
- **Goals** — objectives (agent-owned or user-owned)

### 3. Three-Layer Narrative

Self-narrative has explicit structure:

- **CORE LAYER** — stable identity, rarely changes
- **RECENT LAYER** — ephemeral, replaced after each session
- **THREADS** — ongoing storylines, must be explicitly closed

### 4. First-Person Validation

Narrative content must be first-person:

❌ **Wrong:** "The agent learned something today"  
✅ **Right:** "I learned something today"

## Architecture

```
┌─────────────────────────────────────┐
│         Identity Service            │
│   (bootstrap, update, snapshot)     │
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│        Narrative Service            │
│   (render, validate, archive)       │
└─────────────┬───────────────────────┘
              │
              ▼
┌─────────────────────────────────────┐
│       FileStateStore                │
│   (persistence adapter)             │
└─────────────────────────────────────┘
```

### Models

- `Identity` — complete self-representation
- `CoreValue`, `Habit`, `Principle`, `Goal`, `OpenQuestion`
- `IdentitySnapshot` — versioned history
- `Eigenstate` — session end state
- `NarrativeDocument` — three-layer structure
- `NarrativeThread` — ongoing storyline

## Usage

### Bootstrap Identity

```bash
# Create new identity
atman-identity init --workspace ./my-workspace

# With specific agent ID
atman-identity init --workspace ./my-workspace --agent-id <uuid>
```

### Show Identity

```bash
atman-identity show --workspace ./my-workspace --agent-id <uuid>
```

### Create Snapshot

```bash
atman-identity snapshot \
  --workspace ./my-workspace \
  --agent-id <uuid> \
  --description "Manual checkpoint"
```

### Render Narrative

```bash
# From identity only
atman-identity render --workspace ./my-workspace --agent-id <uuid>

# From identity + eigenstate
atman-identity render \
  --workspace ./my-workspace \
  --agent-id <uuid> \
  --eigenstate fixtures/eigenstate_sample.json
```

### Validate Narrative

```bash
atman-identity validate ./my-workspace/NARRATIVE.md
```

## Demo

Run reproducible walkthrough:

```bash
make demo-identity         # With pauses
make demo-identity-fast    # Instant output
```

Demo shows:

1. Bootstrap honest empty identity
2. Add values, habits, principles, goals
3. Create snapshots
4. Generate three-layer narrative
5. Update from eigenstate
6. Add and close threads
7. Render and validate NARRATIVE.md

## Storage Layout

```
workspace/
├── identity.json                # Current identity
├── identity_snapshots/          # Versioned history
│   └── <snapshot-id>.json
├── narrative.json               # Current narrative
├── narrative_archive/           # Old narratives
│   └── <narrative-id>_<timestamp>.json
├── eigenstate.json              # Latest eigenstate
├── NARRATIVE.md                 # Rendered markdown
└── experiences/                 # Experience records
    └── <experience-id>.json
```

## Testing

Key test coverage:

- ✓ Bootstrap creates honest empty identity
- ✓ No fake seeded principles or values
- ✓ Snapshots are immutable
- ✓ Narrative has mandatory sections (CORE, RECENT)
- ✓ First-person validation rejects third-person
- ✓ Recent layer replaces, core layer preserved
- ✓ Threads must be explicitly closed

Run tests:

```bash
pytest tests/test_identity_models.py -v
pytest tests/test_narrative_models.py -v
pytest tests/test_identity_service.py -v
pytest tests/test_narrative_service.py -v
```

## Integration

### From Code

```python
from pathlib import Path
from uuid import uuid4
from atman.adapters.storage import FileStateStore
from atman.core.services import IdentityService, NarrativeService
from atman.core.models import CoreValue, Principle, Eigenstate

# Initialize
workspace = Path("./my-workspace")
store = FileStateStore(workspace)
identity_service = IdentityService(store)
narrative_service = NarrativeService(store)

# Bootstrap
agent_id = uuid4()
identity = identity_service.bootstrap_identity(agent_id)

# Add value
value = CoreValue(
    name="honesty",
    description="Being truthful",
    confidence=0.8
)
identity = identity_service.add_core_value(agent_id, value)

# Create narrative
narrative = narrative_service.create_narrative(identity)

# Render to file
output = workspace / "NARRATIVE.md"
narrative_service.render_to_file(identity.id, output)
```

### Session Lifecycle Integration

```python
# At session start
narrative = narrative_service.get_narrative(agent_id)
markdown = narrative.render_markdown()
# -> Feed to agent as context

# At session end
eigenstate = Eigenstate(
    session_id=session_id,
    emotional_tone=0.3,
    session_summary="...",
    open_threads=["..."]
)
store.save_eigenstate(eigenstate)

# Update narrative
identity = identity_service.get_identity(agent_id)
narrative = narrative_service.update_from_identity_and_eigenstate(
    identity, eigenstate
)
```

## Invariants

### Identity

- Bootstrap creates empty identity with honest self-description
- No fake seeded values or principles
- Schema version tracked for migrations
- Timestamps for created_at and updated_at

### Snapshots

- Created on significant changes (values, principles, baseline shift)
- Immutable — preserve state at point in time
- Include change summary

### Narrative

- Three layers: CORE, RECENT, THREADS
- CORE layer stable, rarely changes
- RECENT layer ephemeral, replaced each session
- Threads must be explicitly closed (with reason)
- Content validated for first-person style

### Eigenstate

- Captured at session end
- Records emotional tone, cognitive load, open threads
- Used to update narrative

## Future Integration

This module is designed to integrate with:

- **Experience Store** (WP-02) — identity built from real experience
- **Reflection Engine** — deep analysis updates identity
- **Session Manager** — uses narrative at session start, saves eigenstate at end
- **Reality Anchor** — uses identity to detect drift

See `docs/architecture/SYSTEM.md` for full integration picture.

## References

- Work Package: [03-identity-and-narrative.md](../../development/work-packages/03-identity-and-narrative.md)
- Architecture: [SYSTEM.md](../../architecture/SYSTEM.md)
- Development Standard: [DEVELOPMENT_STANDARD.md](../../development/DEVELOPMENT_STANDARD.md)

---

**Next:** See [Russian version (README-ru.md)](./README-ru.md)
