# Experience Fixtures

This directory contains sample experience data for testing and demonstration.

## Files

### experience1_competence_challenge.json
A **meaningful** experience where the agent faces a competence challenge.
- Two key moments showing progression from uncertainty to alignment
- Demonstrates values: competence, honesty, service
- Shows principle confirmation through action
- Importance: 0.8, Salience: 0.9

### experience2_value_conflict.json
A **profound** experience involving value conflict resolution.
- Shows internal conflict between service and honesty
- Demonstrates principle questioning and integration
- High emotional intensity (0.8) and profound depth
- Importance: 0.9, Salience: 1.0

### experience3_surface_technical.json
A **surface** experience of routine technical assistance.
- Low emotional intensity (0.3) and surface depth
- Straightforward, no principle questioning
- Lower importance: 0.3, Salience: 0.4

## Usage

Full guide: [`docs/features/experience-store/README.md`](../docs/features/experience-store/README.md).

These fixtures can be used with the CLI:

```bash
atman experience add fixtures/experience1_competence_challenge.json
atman experience add fixtures/experience2_value_conflict.json
atman experience add fixtures/experience3_surface_technical.json
```

Or loaded in tests:

```python
import json
from pathlib import Path

with open("fixtures/experience1_competence_challenge.json") as f:
    data = json.load(f)
    experience = SessionExperience.model_validate(data)
```

## Design Notes

Each fixture demonstrates different aspects of the Experience Store:

1. **Emotional depth spectrum**: surface → meaningful → profound
2. **Value alignment**: from simple to complex conflicts
3. **Principle dynamics**: confirmation, questioning, integration
4. **Context richness**: minimal to detailed context halos
5. **Salience patterns**: for testing decay calculations

All experiences use `incomplete_coloring: false` to demonstrate proper first-hand recording.
