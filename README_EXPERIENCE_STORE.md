# Experience Store - Work Package 02

Experience Store is the archive of first-hand lived experiences for the Atman agent. It stores not facts and not analysis, but *what the agent actually experienced*.

## Overview

The Experience Store implements the following architecture components:

- **Domain Models** (`atman/core/models/experience.py`): Core entities representing experiences
- **StateStore Port** (`atman/core/ports/state_store.py`): Interface for storage adapters
- **JSONL Adapter** (`atman/adapters/storage/jsonl_experience_store.py`): File-based persistence
- **In-Memory Adapter** (`atman/adapters/storage/in_memory_experience_store.py`): For testing
- **Experience Service** (`atman/core/services/experience_service.py`): Business logic layer
- **CLI** (`atman/cli_experience.py`): Command-line interface

## Key Principles

### 1. First-Hand Experience Only

Experiences are colored **in real-time** during the session, not retrospectively. If emotional coloring couldn't be captured in the moment, we use `incomplete_coloring: true` as an honest fallback.

**Prohibited**: Retroactive "guessing" of emotional coloring.

### 2. Immutability of Original Experience

The original `key_moments` are **immutable** after recording. They represent what actually happened and how it was felt *at that time*.

**Allowed**: Adding `reframing_notes` that provide new perspectives without changing the original.

### 3. Salience Decay

Memories fade without access. The `salience` value represents current brightness of a memory and decays over time based on:

- Days since last access
- Emotional intensity of the experience
- Depth (profound experiences decay slower)

**Important**: Calculating salience does NOT modify the stored experience.

## Domain Models

### EmotionalDepth

```python
class EmotionalDepth(str, Enum):
    SURFACE = "surface"      # Noticed but didn't affect deeply
    MEANINGFUL = "meaningful" # Touched values or principles
    PROFOUND = "profound"     # Changed something fundamental
```

### FeltSense

Emotional coloring of a moment:

```python
FeltSense(
    emotional_valence=0.3,      # -1.0 (negative) to +1.0 (positive)
    emotional_intensity=0.7,    # 0.0 (barely noticed) to 1.0 (overwhelming)
    depth=EmotionalDepth.MEANINGFUL
)
```

### KeyMoment

A significant moment within a session:

```python
KeyMoment(
    what_happened="User asked a challenging question",
    when=datetime.now(timezone.utc),
    how_i_felt=felt_sense,
    why_it_matters="Tests my competence",
    values_touched=["honesty", "competence"],
    principles_confirmed=["admit_uncertainty"],
    principles_questioned=[],
    what_changed="Became more aware of my limitations"
)
```

### SessionExperience

Complete experience from one session:

```python
SessionExperience(
    session_id=uuid4(),
    key_moments=[moment1, moment2],
    importance=0.7,
    salience=0.8,
    incomplete_coloring=False,
    reframing_notes=[]
)
```

## Installation

```bash
# Install in development mode
pip install -e .

# Or install with dev dependencies
pip install -e ".[dev]"
```

## Usage

### CLI Commands

Start the CLI:

```bash
python -m atman.cli_experience
```

Or use the module directly:

```bash
python src/atman/cli_experience.py
```

#### Add Experience

```bash
atman> experience add fixtures/experience1_competence_challenge.json
```

#### Get Experience

```bash
atman> experience get <experience_id>
```

#### Add Reframing Note

```bash
atman> experience reflect <experience_id> "Looking back, this was a growth moment" growth
```

#### Search Experiences

```bash
# By session
atman> experience search session <session_id>

# By values touched
atman> experience search values honesty,competence

# By emotional depth
atman> experience search depth profound

# Recent experiences
atman> experience search recent 10
```

#### Preview Salience Decay

```bash
atman> experience decay-preview <experience_id> 30
```

### Programmatic Usage

```python
from atman.adapters.storage import JsonlExperienceStore
from atman.core.services import ExperienceService
from atman.core.models import SessionExperience, KeyMoment, FeltSense

# Initialize
store = JsonlExperienceStore(".atman/experiences.jsonl")
service = ExperienceService(store)

# Create experience
felt = FeltSense(
    emotional_valence=0.3,
    emotional_intensity=0.7,
    depth="meaningful"
)
moment = KeyMoment(
    what_happened="Something significant happened",
    how_i_felt=felt,
    why_it_matters="It touched my values"
)
experience = SessionExperience(
    session_id=uuid4(),
    key_moments=[moment]
)

# Store it
record = service.create_experience(experience)

# Retrieve it
retrieved = service.get_experience(record.experience.id)

# Add reframing note
service.add_reframing_note(
    experience_id=record.experience.id,
    reflection="New perspective gained",
    reflection_type="growth"
)

# Search by values
results = service.search_by_values(["honesty", "competence"])

# Calculate current salience
current_salience = service.calculate_current_salience(record.experience.id)
```

## Testing

Run all tests:

```bash
pytest tests/
```

Run specific test files:

```bash
pytest tests/test_experience_models.py
pytest tests/test_experience_service.py
pytest tests/test_experience_stores.py
```

Run with coverage:

```bash
pytest --cov=atman.core.models.experience --cov=atman.core.services.experience_service
```

## Architecture

### Core vs Adapter

**Core** (`atman/core/`):
- Domain models (FeltSense, KeyMoment, SessionExperience, etc.)
- Ports (StateStore interface)
- Services (ExperienceService)
- **No direct dependencies** on storage implementations, LLMs, or external services

**Adapters** (`atman/adapters/`):
- JSONL storage implementation
- In-memory storage implementation
- **Implements** the StateStore port from Core

This separation ensures Core logic is testable and portable.

### Storage Boundary

The `StateStore` port defines the contract:

```python
class StateStore(ABC):
    @abstractmethod
    def create_experience(self, record: ExperienceRecord) -> ExperienceRecord: ...
    
    @abstractmethod
    def get_experience(self, experience_id: UUID) -> ExperienceRecord | None: ...
    
    @abstractmethod
    def add_reframing_note(self, experience_id: UUID, note: ReframingNote) -> ExperienceRecord | None: ...
    
    # ... more methods
```

Core sees **only this interface**, not the implementation details.

## Invariants Protected by Tests

1. ✅ **Emotional valence** must be between -1.0 and 1.0
2. ✅ **Emotional intensity** must be between 0.0 and 1.0
3. ✅ **Depth** must be one of: surface, meaningful, profound
4. ✅ **Original key_moments are immutable** - no modification methods
5. ✅ **Reframing notes append-only** - never replace original
6. ✅ **Salience calculation doesn't modify stored value**
7. ✅ **Access updates last_accessed_at and increments access_count**
8. ✅ **Profound/intense experiences decay slower**
9. ✅ **Search works by session_id, values_touched, depth, date_range**
10. ✅ **incomplete_coloring is explicit, not default**

## Running Without External Services

Experience Store requires **no external services**. It works with:

- **JSONL storage**: Local file, no database needed
- **In-memory storage**: For tests, no persistence
- **No LLM calls**: All data is provided explicitly
- **No mem0 or vector search**: Simple file or memory storage

Default storage location: `~/.atman/experiences.jsonl`

## Persistent Data

### Data Created

- **experiences.jsonl**: One JSON line per experience
- **Schema version**: Each record includes `schema_version` field

### Example Record

```json
{
  "schema_version": "1.0.0",
  "experience": {
    "id": "123e4567-e89b-12d3-a456-426614174000",
    "session_id": "a1b2c3d4-e5f6-4a5b-8c9d-0e1f2a3b4c5d",
    "timestamp": "2026-04-30T10:30:00Z",
    "key_moments": [...],
    "importance": 0.7,
    "salience": 0.8,
    "incomplete_coloring": false,
    "reframing_notes": []
  }
}
```

## Migration Strategy

When schema changes:

1. Increment `schema_version` in new records
2. Write migration script that:
   - Reads all experiences
   - Transforms old format to new
   - Writes with new schema_version
3. Maintain backward compatibility where possible

Example migration (if needed):

```python
def migrate_1_0_to_2_0(storage_path):
    """Migrate from schema 1.0.0 to 2.0.0."""
    old_records = read_jsonl(storage_path)
    new_records = []
    
    for record in old_records:
        if record.schema_version == "1.0.0":
            # Transform record
            new_record = transform(record)
            new_record.schema_version = "2.0.0"
            new_records.append(new_record)
        else:
            new_records.append(record)
    
    write_jsonl(storage_path, new_records)
```

## Examples

See `fixtures/` directory for complete examples:

- `experience1_competence_challenge.json` - Meaningful depth experience
- `experience2_value_conflict.json` - Profound depth with value conflict
- `experience3_surface_technical.json` - Surface depth routine interaction

## What's NOT Included

As per work package scope, the following are **not implemented**:

- ❌ Generating FeltSense from raw logs (must be provided)
- ❌ Reflection Engine runtime
- ❌ Session Manager runtime
- ❌ Vector search
- ❌ LLM integration for analysis
- ❌ Automatic emotional coloring

These components belong to other work packages.

## Related Documentation

- Work Package: `docs/development/work-packages/02-experience-store.md`
- Architecture: `docs/architecture/SYSTEM.md` (sections on Experience Store)
- Development Standard: `docs/development/DEVELOPMENT_STANDARD.md`

## License

See repository root for license information.
