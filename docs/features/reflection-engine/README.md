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

```
MICRO    → After each session    → Updates recent layer + checkpoint
DAILY    → End of day            → Detects patterns, adds reframing notes
DEEP     → Scheduled (weekly+)   → Health assessment, identity revision
```

### Components

1. **Models**:
   - `ReflectionEvent` — record of a reflection process
   - `ReflectionLevel` — depth enum (micro/daily/deep)
   - `PatternCandidate` — detected behavior pattern
   - `HealthAssessment` — psychological health check (6 Yakhoda criteria)

2. **Services**:
   - `MicroReflectionService` — session checkpoint
   - `DailyReflectionService` — pattern detection
   - `DeepReflectionService` — health + identity revision
   - `PrincipleRevisionAdvisor` — distinguishes habits from principles
   - `NarrativeRevisionService` — narrative updates

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
3. **Deep Reflection**: Performs health assessment on 6 Yakhoda criteria
4. **Principle Advisor**: Distinguishes habits from principles

### Demo Output

The demo loads test fixtures and runs all three reflection levels, displaying:

- Experiences analyzed
- Patterns detected
- Reframing notes added
- Health assessment scores
- Proposed identity/narrative changes

---

## CLI Usage

### Micro Reflection

```bash
python -m atman.cli_reflection reflect micro --fixtures
```

Or with real data:

```bash
python -m atman.cli_reflection reflect micro --session-id <uuid>
```

### Daily Reflection

```bash
python -m atman.cli_reflection reflect daily --fixtures
```

Or with specific date:

```bash
python -m atman.cli_reflection reflect daily --date 2026-05-01
```

### Deep Reflection

```bash
python -m atman.cli_reflection reflect deep --fixtures
```

Or with date range:

```bash
python -m atman.cli_reflection reflect deep --since 2026-04-01 --until 2026-05-01
```

---

## Key Contracts

### What Reflection Reads

- Colored `SessionExperience` records
- Current `Identity` state
- `Self-Narrative` document
- Existing `Uncertainty` entries

### What Reflection Writes

- `reframing_notes` to existing experiences (append-only)
- `ReflectionEvent` records
- `PatternCandidate` detections
- Updated or new `Uncertainty` entries
- Draft changes to `Identity` and `Narrative`

### Critical Rule

**Reflection does NOT invent emotions for old events.**  
It can only interpret experiences where `how_i_felt` was recorded first-hand during the session.

---

## Health Assessment (6 Yakhoda Criteria)

Deep reflection assesses psychological health using Jahoda's framework:

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

Micro updates checkpoint, Daily detects patterns, Deep revises identity.

**Why**: Separation of concerns — frequent lightweight updates vs rare deep revisions.

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

Micro updates recent layer, Deep updates core layer.

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

**Last Updated**: 2026-05-02
