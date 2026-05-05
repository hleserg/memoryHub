# Session JSON fixtures (E2E)

JSON files in this directory describe **session-shaped** scenarios: `metadata`, `events`,
`key_moments`, and `expected_session_outcome`, aligned with
`SessionEvent` / `KeyMomentInput` in `atman.core.models.session`.

## Generating new fixtures

One-off LLM generation (not CI). Requires `ANTHROPIC_API_KEY` and the `e2e` optional extra:

```bash
pip install -e ".[e2e]"
export ANTHROPIC_API_KEY=...
python -m e2e.generate_fixtures --model claude-sonnet-4-6 --count 5
```

Output files: `session_<NN>_<slug>.json`. **Always review and edit** before committing;
model output is non-deterministic.

See [issue #141](https://github.com/hleserg/atman/issues/141).
