# Reflection Engine

**Status**: Implemented (WP-04)
**Русская версия**: [README-ru.md](README-ru.md)

---

## Overview

The Reflection Engine is Atman's component for analyzing already-colored experiences, detecting patterns, updating the narrative, and assessing psychological health. It implements three levels of reflection, each with different scope and depth.

**Key principle**: Reflection works *only* with experiences that were colored first-hand. It never retroactively invents emotions for past events.

---

## Architecture

### Three Levels of Reflection

```text
MICRO    → After each session    → Updates recent narrative layer (repo write)
DAILY    → End of day            → Detects patterns, adds reframing notes
DEEP     → Scheduled (weekly+)   → Health assessment, proposals on ReflectionEvent
```

### Components

1. **Models**:
   - `ReflectionEvent` — record of a reflection process
   - `ReflectionLevel` — depth enum (micro/daily/deep)
   - `PatternCandidate` — detected behavior pattern
   - `HealthAssessment` — psychological health check (6 Jahoda criteria)

2. **Services**:
   - `MicroReflectionService` — session checkpoint
   - `DailyReflectionService` — UTC-calendar-day pattern detection
   - `DeepReflectionService` — windowed health assessment + proposal generation
   - `PrincipleRevisionAdvisor` — distinguishes habits from principles
   - `NarrativeRevisionService` — narrative updates (requires an explicit ``NarrativeWriteAuditPort``; use ``atman.core.narrative_write_audit.NoOpNarrativeWriteAudit`` only when acceptable for tests/demos)

3. **Ports**:
   - `ExperienceRepository` — access to experiences
   - `IdentityRepository` — access to identity
   - `NarrativeRepository` — access to narrative
   - `ReflectionModel` — text generation (LLM or mock)

4. **Adapters**:
   - `MockReflectionModel` — deterministic mock for testing
   - `InMemoryPatternStore` — pattern storage
   - `InMemoryReflectionEventStore` — event history
   - `InMemoryHealthAssessmentStore` — assessment history

---

## Running the Demo

### Quick Start (with fixtures)

```bash
make demo-reflection
```

Or instantly (no pauses):

```bash
make demo-reflection-fast
```

### What the Demo Shows

1. **Micro Reflection**: Updates recent narrative layer after a session
2. **Daily Reflection**: Detects patterns across day's experiences
3. **Deep Reflection**: Performs health assessment on 6 Jahoda criteria (and prints proposals from `ReflectionEvent` when present)
4. **Narrative Revision Service**: Opens/updates/closes a narrative thread (separate from the three reflection levels)
5. **Principle Advisor**: Distinguishes habits from principles

### Demo Output

The demo loads test fixtures, runs micro → daily → deep reflection, then narrative revision and principle advisor. It displays:

- Experiences analyzed
- Patterns detected
- Reframing notes added
- Health assessment scores
- Proposed identity and narrative text (from deep reflection’s `ReflectionEvent`, when the mock produces non-empty strings)
- Narrative thread lifecycle (revision service)
- Principle suggestions

---

## CLI Usage

### Micro Reflection

```bash
python -m atman.cli_reflection reflect micro --fixtures
```

### Daily Reflection

```bash
python -m atman.cli_reflection reflect daily --fixtures
```

### Deep Reflection

```bash
python -m atman.cli_reflection reflect deep --fixtures
```

**Fixtures-only today:** `atman.cli_reflection` supports only `--fixtures` for each subcommand. A full walkthrough (fixtures, narrative revision, and reflection levels) is `make demo-reflection` or `python src/demo_reflection.py`. Planned (not implemented here yet): `--session-id`, `--date`, and `--since` / `--until` backed by persistent state (for example `FileStateStore`).

---

## Key Contracts

### What Reflection Reads

- Colored `SessionExperience` records
- Current `Identity` state
- `Self-Narrative` document (when wired)

### What Reflection Writes (implemented today)

- `reframing_notes` on existing experiences (append-only)
- `ReflectionEvent` records (including **failed** micro outcomes, e.g. narrative concurrency conflict)
- `PatternCandidate` detections (pattern store)
- `HealthAssessment` records (deep path only)
- **Micro**: persists an update to the narrative **recent** layer via `NarrativeRepository` when the optimistic concurrency token matches

### Operational Contracts

- **Time windows are UTC**: daily reflection analyzes the UTC calendar day containing the provided anchor; deep reflection treats `since` and `until` as inclusive UTC instants. Naive datetimes are normalized as UTC wall time.
- **Daily/deep runs are idempotent**: each normal, empty, or skipped daily/deep job receives a deterministic `reflection_run_key`. If a terminal success event already exists (`outcome=daily_ok`, `outcome=daily_empty`, `outcome=daily_skipped`, `outcome=deep_ok`, `outcome=deep_empty`, `outcome=deep_skipped`), the service returns it instead of repeating side effects.
- **Identity is anchored by snapshot**: normal daily/deep jobs materialize or reuse a deterministic `IdentitySnapshot` and store its id in `ReflectionEvent.identity_snapshot_id`. This is never the mutable `Identity.id`.
- **Reframing is replay-safe**: generated notes use stable `triggered_by` keys (`reflection|<run_key>|reframe|<experience_id>`). Replays count `DUPLICATE_TRIGGERED_BY` outcomes in `reframing_duplicate_triggered_by_count` rather than appending duplicate notes.
- **Degraded reframing is explicit**: missing experiences and storage rejections are recorded on `ReflectionEvent` as `reframing_experience_not_found_count` and `reframing_append_storage_rejected_count`; `notes` also includes `signal=reframing_append_degraded` when applicable.
- **Persistence failures are observable**: if daily/deep side effects happen but saving the success event fails, a `ReflectionEventPersistenceObserver` is notified. Deep reflection also attempts to save an `outcome=deep_failed reason=persist` event; callers still receive the original exception.

Example `ReflectionEvent.notes` values:

```text
outcome=daily_ok
outcome=daily_empty reason=no_experiences
outcome=daily_skipped reason=no_identity
outcome=micro_failed reason=narrative_conflict
outcome=deep_ok signal=reframing_append_degraded not_found=1 storage_rejected=0
```

### Not implemented in this package (future / proposal-only)

- **`Uncertainty` store**: no port or persistence yet; reflection does not read or write uncertainty rows.
- **Deep → core narrative**: `DeepReflectionService` attaches **proposed** narrative text to the `ReflectionEvent` only; it does **not** persist the core layer. Apply proposals through `NarrativeRevisionService` (or another governed path) when you want a durable core-layer change.
- **Identity mutations from deep reflection**: proposals are text on the event, not automatic `IdentityRepository` writes.

### Critical Rule

**Reflection does NOT invent emotions for old events.**
It can only interpret experiences where `how_i_felt` was recorded first-hand during the session.

---

## Health Assessment (6 Jahoda Criteria)

Deep reflection assesses psychological health using Marie Jahoda's framework:

1. **Positive Self-Attitude** — self-acceptance and awareness
2. **Growth and Actualization** — pursuing potential
3. **Integration** — coherent personality, aligned values/actions
4. **Autonomy** — self-determination, conscious choices
5. **Reality Perception** — accurate world understanding
6. **Environmental Mastery** — effective coping strategies

Each criterion is scored 0.0-1.0 with evidence and concerns.

---

## Testing

### Run All Tests

```bash
pytest tests/test_reflection*.py -v
```

### Coverage

Reflection engine tests cover:

- Model validation
- Service logic (micro/daily/deep)
- Idempotent daily/deep run keys and identity anchor snapshots
- Skipped/empty outcomes (`no_experiences`, `no_identity`, `no_narrative`)
- Reframing duplicate and degraded append accounting
- Persistence observer paths for event-store failures after side effects
- Principle vs habit distinction
- Health assessment completeness
- Pattern detection
- Reframing note addition

### Fixtures

Test fixtures are in `fixtures/reflection/`:

- `experiences.json` — 3 colored experiences
- `identity.json` — basic identity with values, habits, principles

---

## Design Decisions

### 1. Deterministic Mock Model

The `MockReflectionModel` provides template-based responses for testing.
Real LLM integration happens through the `ReflectionModel` port.

**Why**: Reflection logic must be testable without external dependencies.

### 2. Append-Only Reframing

Original experience fields are immutable.
Reframing notes accumulate in a separate list.

**Why**: Preserves first-hand authenticity of original coloring.

### 3. Three-Level Hierarchy

Micro updates the **recent** narrative layer; Daily detects patterns; Deep assesses health and emits **proposals** on the reflection event (identity / narrative persistence is out of band).

**Why**: Separation of concerns — frequent lightweight updates vs rare deep revisions, with a clear boundary between “proposed” and “committed” state.

### 4. Health Assessment is Optional

Only Deep reflection performs health checks.
Micro and Daily focus on pattern recognition.

**Why**: Health assessment is computationally expensive and rarely needed.

---

## Integration Points

### With Experience Store

Reflection reads colored experiences and adds reframing notes.

### With Identity Store

Deep reflection proposes changes to values, habits, principles.

### With Narrative Store

Micro updates the **recent** layer when the write succeeds. Deep reflection **proposes** narrative text on `ReflectionEvent`; persisting a **core** layer update is a separate step (e.g. `NarrativeRevisionService.update_core_layer` under audit).

### With Session Manager (future)

Session Manager will trigger micro reflection automatically after each session.

---

## Future Work

See `docs/development/work-packages/04-reflection-engine.md` for:

- Real LLM integration via `ReflectionModel` port
- Scheduler for automatic daily/deep reflection
- Integration with mem0 for pattern persistence
- Advanced pattern confirmation logic

---

## References

- **Work Package**: `docs/development/work-packages/04-reflection-engine.md`
- **Architecture**: `docs/architecture/SYSTEM.md` § Reflection Engine
- **Development Standard**: `docs/development/DEVELOPMENT_STANDARD.md`

---

**Last Updated**: 2026-05-04
