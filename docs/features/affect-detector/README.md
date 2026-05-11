# Affect Detector (E21)

Behavioural layer that scores agent utterances with eight NRC-backed and lexical metrics, maintains a rolling z-score baseline on disk, and appends tagged `KeyMoment` rows (via `SessionManager.append_key_moment`) — the write-only gateway for automated affect capture.

## Scope

- **In scope:** `src/atman/affect/*`, optional wiring on `SessionManager` (`affect_workspace` + `AffectDetectorConfig`), async hook after `record_event`, agent tool `record_key_moment` → `AffectDetector.submit_self_report`.
- **Out of scope:** new SQL tables, LLM sincerity (`use_llm_analysis=True` raises `NotImplementedError`), reading/querying `key_moments`.

## Configuration

| Field | Default | Notes |
|-------|---------|-------|
| `default_lang` | `"ru"` | Short strings fall back here. **Switch to `"en"` before production** if the agent’s primary surface language is English. |
| `cold_start_sessions` | `10` | First *N* distinct sessions (by first-seen `session_id`) suppress anomaly / random-sample / divergence triggers; baseline still updates. |
| `sigma_threshold` / `strong_signal_threshold` | `2.0` / `2` | Count metrics whose \|z\| exceeds sigma; anomaly when count ≥ threshold. |
| `random_sample_every_n` | `5` | Counter increments each `process()`; every *n*-th call adds `affect:random-sample` when not in cold start. |
| `divergence_threshold` | `25.0` | \|NRC(message) − NRC(thinking)\| on density scale; requires `SessionEvent.thinking`. |
| `min_text_length` | `12` | Skip `process()` unless length ≥ threshold **or** `!` present. |

Baseline persistence: `{affect_workspace}/affect_baseline.jsonl`.

## Tags on `KeyMoment`

- `affect:anomaly`
- `affect:random-sample`
- `affect:self-report`
- `affect:divergence`

Payload lives under `KeyMoment.context_halo` with `description="atman:affect-detector"` and `metadata` keys `tags`, `trigger_reason`, `says_writes`, `demonstrates_thinks`, `divergence_score`.

## Session Manager

```python
from pathlib import Path
from atman.affect.detector import AffectDetectorConfig
from atman.core.services import SessionManager

mgr = SessionManager(
    store,
    affect_workspace=Path("/tmp/agent_ws"),
    affect_config=AffectDetectorConfig(),
)
```

`record_key_moment` on `SessionManager` is removed; callers get `AttributeError` pointing to `AffectDetector`. Use `append_key_moment_input` for tests/programmatic moments.

## CLI demo

```bash
PYTHONPATH=src python -m atman.affect.detector --demo
```

Uses `fixtures/affect_demo_responses.txt` and prints JSON-serialised key moments to stdout.

## Tests

```bash
pytest tests/affect/ -v --tb=short
mypy --strict src/atman/affect/
```

## References

- Manifest: divergence between self-report and objective layer operationalises authenticity as an observable.
- Vendored lexicon: NRC Emotion Lexicon (Mohammad & Turney 2013) inside `affect/emolex/`.
