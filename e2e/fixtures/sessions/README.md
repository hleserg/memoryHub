# Session JSON fixtures (E2E)

JSON files describe **session-shaped** scenarios: `metadata`, `events`, `key_moments`,
and `expected_session_outcome`, aligned with `SessionEvent` / `KeyMomentInput` in
`atman.core.models.session`.

## Layout

- `en/session_<NN>_<slug>.json` — English dialogue and text fields.
- `ru/session_<NN>_<slug>.json` — Russian text; `event_type` values stay English for tooling.

## Generating fixtures

One-off LLM generation (manual/secret-gated automation). Requires `ANTHROPIC_API_KEY` and `pip install -e ".[e2e]"`.

Default: **20 English + 20 Russian** sessions, **parallel** API runs:

```bash
pip install -e ".[e2e]"
export ANTHROPIC_API_KEY=...
python -m e2e.generate_fixtures --model claude-haiku-4-5
```

Generation is incremental: each valid session is written to disk immediately.

Corpus repair policy (cross-session checks in `e2e/validation.py`):

- **strict** (default): if `validate_corpus` fails with a session-scoped error, drop that
  session tail and retry. If the tail would exceed **`--max-corpus-regen`** (default 12),
  the run **stops without deleting** extra files and prints a warning instead (`0` = no limit).
  Global failures (no session number in the error) never delete files.
- **soft** (`--corpus-policy soft`): on corpus failure, **never delete**; warn and keep all
  saved sessions (useful to finish filling missing slots without mass re-generation).

Options:

- `--count-en N` / `--count-ru N` — per-locale session counts (0 skips that locale).
- `--no-parallel-locales` — generate locales one after another.
- `--count N` — legacy: English only, `N` sessions under `en/`.
- `--corpus-policy strict|soft` — see above.
- `--max-corpus-regen N` — strict mode only; default 12.

**Always review and edit** before committing; model output is non-deterministic.

See [issue #141](https://github.com/hleserg/atman/issues/141).
