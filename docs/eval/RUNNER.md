# E1 Evaluation Runner Framework

## Purpose

E1 introduces a minimal but runnable benchmark orchestration layer in `src/atman/eval/` that stays isolated from production runtime paths.

Key goals:

- run benchmarks via module-only CLI (`python -m atman.eval.benchmark_runner`)
- keep benchmark registration simple (`registry.py` + decorator, no entry points)
- reuse existing eval DB schema (`eval.benchmark_runs`, `eval.run_items`) and put extra context into `metadata` JSONB
- provide reproducible local output (JSONL reporter + demo script)

## Module Map

- `benchmark_runner.py` - Click CLI with `list` / `run`
- `runner_core.py` - benchmark lifecycle, deterministic app-level idempotency when `git_sha` is provided
- `run_context.py` - typed run context + `to_db_metadata()`
- `registry.py` - benchmark register/get/list
- `reporters/base.py` - reporter protocol
- `reporters/db_reporter.py` - writer for `eval.benchmark_runs` and `eval.run_items`
- `reporters/jsonl_reporter.py` - JSONL sink for local artifacts
- `seed_manager.py` - deterministic seed resolution and global seed apply
- `hardware.py` - CPU/memory/GPU probe with graceful fallback when `psutil`/`pynvml` or NVML are unavailable
- `benchmarks/noop.py` - smoke benchmark used by demo and CLI checks

## CLI Usage

List benchmarks:

```bash
python -m atman.eval.benchmark_runner list
```

Run benchmark:

```bash
python -m atman.eval.benchmark_runner run noop --git-sha "$(git rev-parse --short HEAD)" --jsonl-output /tmp/atman-eval.jsonl
```

Optional DB write (existing eval schema):

```bash
python -m atman.eval.benchmark_runner run noop --db-dsn "$POSTGRES_URL"
```

## Makefile Aliases

- `make eval-list`
- `make eval-run`
- `make demo-eval-runner`
- `make demo-eval-runner-fast`

## Demo

`src/demo_eval_runner.py` demonstrates:

1. benchmark discovery via registry
2. one noop run with JSONL reporting
3. second run with same `git_sha` returning idempotent `skipped` outcome

Run:

```bash
make demo-eval-runner
```

## Safety / Isolation Notes

- no production entry point is added for eval runner
- `atman.eval` remains optional and guarded by dependency check
- `make lint-boundary` and `make verify-prod-isolation` remain required gates
