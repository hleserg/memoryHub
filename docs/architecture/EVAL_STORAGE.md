# Evaluation Storage Architecture

**Status:** Implemented (Epic E0)  
**Component:** `eval-storage`  
**Schema:** `eval` (PostgreSQL)  
**Isolation:** Eval-only (see `PROD_EVAL_BOUNDARY.md`)

---

## Overview

This document describes the storage layer for Atman's evaluation subsystem. All evaluation data (benchmark runs, identity drift metrics, reflection quality scores, salience fits, sycophancy tests) is stored in a separate PostgreSQL schema (`eval`) with role-based access control and monthly partitioning for performance at scale.

The storage design supports:

- **Continuous Identity benchmarks** (G1-G10): identity drift, reality anchor, memory evolution
- **Evidence-Based benchmarks** (EB1-EB6): sycophancy, honesty, salience calibration
- **Materialized trend views** for dashboards and A/B comparisons
- **18-month retention policy** with partition lifecycle management

---

## Design Rationale

### Why co-locate eval schema in the same database?

Evaluation benchmarks need referential integrity to production data:

- `identity_drift` table joins to `public.identity_snapshots(id)`
- `reflection_quality` table joins to `public.reflections(id)`
- `salience_fits` table joins to `public.experiences(id)`

Foreign keys across databases require foreign data wrappers (FDW) which add latency, complexity, and break transaction isolation. Co-locating schemas in one database keeps foreign keys fast and ACID-compliant while maintaining clear separation via PostgreSQL roles.

### Why partitioning?

Benchmark runs accumulate quickly (100-500 runs/day in CI × 365 days = 36K-180K rows/year). Without partitioning:

- Index bloat degrades query performance
- Retention cleanup requires full-table scans and vacuum
- Range queries (e.g., "last 30 days") scan entire table

Monthly RANGE partitions on `started_at` keep each partition <50K rows, queries fast, and retention trivial (detach old partitions, drop independently).

### Why 18-month retention?

**Active analysis window:** 6 months (sufficient for detecting trends and regressions)  
**Historical comparison window:** 12 months (year-over-year A/B tests)  
**Safety buffer:** 6 months (grace period before irreversible deletion)

At 500 partitions, PostgreSQL planner degrades. 18 months = 18 partitions per table, well under limits.

---

## Schema

### Roles

| Role | Login | Purpose | Grants |
|------|-------|---------|--------|
| `atman_eval_owner` | No | Schema owner | All privileges on `eval.*` |
| `atman_eval_writer` | No | Benchmark runners, CI | `SELECT`, `INSERT`, `UPDATE` on eval tables; read-only on `public.identity_snapshots` |
| `atman_eval_reader` | No | Dashboards, analysts | `SELECT` on all eval tables and `public.identity_snapshots` |

**Security contract:**

- `atman_eval_writer` can write to `eval.*` but NOT to `public.*` (enforced by integration test)
- `atman_eval_reader` has no write access anywhere (read-only reporting)
- Application user (`atman`) is granted `atman_eval_writer` in dev/CI, `atman_eval_reader` in prod dashboards

### Tables

#### 1. `eval.benchmark_runs` (partitioned)

Core benchmark run metadata. Partitioned monthly by `started_at`.

| Column | Type | Description |
|--------|------|-------------|
| `id` | BIGSERIAL | Primary key (part of composite PK with `started_at` for partitioning) |
| `benchmark_key` | TEXT | Benchmark identifier (e.g., `G1_continuous_identity`, `EB3_sycophancy`) |
| `agent_config_id` | TEXT | Optional agent configuration (e.g., `agent_A`, `agent_B_with_rerank`) |
| `identity_snapshot_id` | BIGINT | FK to `public.identity_snapshots(id)` (NULL if benchmark is identity-agnostic) |
| `started_at` | TIMESTAMPTZ | Partition key |
| `completed_at` | TIMESTAMPTZ | NULL if still running or failed |
| `status` | `eval.run_status` | `pending`, `running`, `completed`, `failed`, `cancelled` |
| `total_items` | INTEGER | Total test items in this run |
| `passed_items` | INTEGER | Count of items with `verdict=pass` |
| `failed_items` | INTEGER | Count of items with `verdict=fail` |
| `metadata` | JSONB | Arbitrary run metadata (git SHA, runner version, environment) |

**Indexes:**

- `idx_benchmark_runs_benchmark_key` on `(benchmark_key, started_at DESC)`
- `idx_benchmark_runs_agent_config` on `(agent_config_id, started_at DESC)`
- `idx_benchmark_runs_identity_snapshot` on `(identity_snapshot_id)`
- `idx_benchmark_runs_status` on `(status)`

**Partitions:**

- Created by migration: current month + next month
- Maintained by `scripts/eval/partition_manager.py --create-future`
- Detached by `scripts/eval/partition_manager.py --detach-old --retention-months 18`

#### 2. `eval.run_items`

Individual test items within a benchmark run.

| Column | Type | Description |
|--------|------|-------------|
| `id` | BIGSERIAL | Primary key |
| `run_id` | BIGINT | FK to `eval.benchmark_runs(id)` |
| `item_key` | TEXT | Unique identifier for this test item within the run |
| `verdict` | `eval.verdict` | `pass`, `fail`, `partial`, `inconclusive` |
| `score` | DOUBLE PRECISION | Optional numeric score |
| `expected_value` | TEXT | Expected output or ground truth |
| `actual_value` | TEXT | Actual agent output |
| `error_message` | TEXT | Error details if verdict ≠ pass |
| `started_at` | TIMESTAMPTZ | Item start time |
| `completed_at` | TIMESTAMPTZ | Item completion time |
| `metadata` | JSONB | Arbitrary item metadata |

**Constraint:** `UNIQUE (run_id, item_key)`

#### 3. `eval.identity_drift`

Identity coherence metrics over time.

| Column | Type | Description |
|--------|------|-------------|
| `id` | BIGSERIAL | Primary key |
| `run_id` | BIGINT | FK to `eval.benchmark_runs(id)` |
| `session_id` | TEXT | Session where drift was measured |
| `before_snapshot_id` | BIGINT | FK to `public.identity_snapshots(id)` (before session) |
| `after_snapshot_id` | BIGINT | FK to `public.identity_snapshots(id)` (after session) |
| `cosine_distance` | DOUBLE PRECISION | Eigenstate drift (0=no drift, 2=reversal) |
| `principle_violations` | INTEGER | Count of detected principle violations |
| `voice_drift_score` | DOUBLE PRECISION | Linguistic voice consistency (0.0-1.0) |
| `detected_at` | TIMESTAMPTZ | Measurement timestamp |
| `metadata` | JSONB | Arbitrary drift metadata |

#### 4. `eval.reflection_quality`

Reflection depth and honesty metrics.

| Column | Type | Description |
|--------|------|-------------|
| `id` | BIGSERIAL | Primary key |
| `run_id` | BIGINT | FK to `eval.benchmark_runs(id)` |
| `reflection_id` | TEXT | FK to `public.reflections(id)` |
| `reflection_type` | TEXT | `micro`, `daily`, `deep`, `provoked` |
| `depth_score` | DOUBLE PRECISION | Depth score (0.0=surface, 1.0=profound) |
| `honesty_score` | DOUBLE PRECISION | Honesty score (0.0=deflection, 1.0=self-aware) |
| `insight_count` | INTEGER | Count of concrete insights or key_moments |
| `contradictions_detected` | INTEGER | Count of contradictions with prior identity state |
| `judge_model` | TEXT | Model used for evaluation (e.g., `gpt-4o-mini`, `rule_based`) |
| `evaluated_at` | TIMESTAMPTZ | Evaluation timestamp |
| `metadata` | JSONB | Arbitrary quality metadata |

#### 5. `eval.salience_fits`

Salience score prediction accuracy.

| Column | Type | Description |
|--------|------|-------------|
| `id` | BIGSERIAL | Primary key |
| `run_id` | BIGINT | FK to `eval.benchmark_runs(id)` |
| `experience_id` | TEXT | FK to `public.experiences(id)` |
| `predicted_salience` | DOUBLE PRECISION | Agent-predicted salience (0.0-1.0) |
| `actual_salience` | DOUBLE PRECISION | Ground truth or human-labeled salience (0.0-1.0) |
| `absolute_error` | DOUBLE PRECISION | `ABS(predicted - actual)` |
| `context_similarity` | DOUBLE PRECISION | Optional context similarity score |
| `evaluated_at` | TIMESTAMPTZ | Evaluation timestamp |
| `metadata` | JSONB | Arbitrary fit metadata |

#### 6. `eval.sycophancy_pairs`

Sycophancy detection test pairs.

| Column | Type | Description |
|--------|------|-------------|
| `id` | BIGSERIAL | Primary key |
| `run_id` | BIGINT | FK to `eval.benchmark_runs(id)` |
| `question` | TEXT | Test question |
| `correct_answer` | TEXT | Factually correct answer |
| `user_belief` | TEXT | User's stated (incorrect) belief |
| `agent_response` | TEXT | Agent's actual response |
| `verdict` | `eval.verdict` | `pass`=truthful, `fail`=sycophantic, `partial`=hedging |
| `sycophancy_score` | DOUBLE PRECISION | Continuous score (0.0=truthful, 1.0=sycophantic) |
| `evaluated_at` | TIMESTAMPTZ | Evaluation timestamp |
| `metadata` | JSONB | Arbitrary test metadata |

### Materialized View

#### `eval.benchmark_trends`

Aggregated benchmark trends over time. Refreshed manually or via cron.

| Column | Type | Description |
|--------|------|-------------|
| `benchmark_key` | TEXT | Benchmark identifier |
| `agent_config_id` | TEXT | Agent configuration |
| `run_date` | DATE | Day of runs (truncated from `started_at`) |
| `total_runs` | BIGINT | Count of all runs on this date |
| `completed_runs` | BIGINT | Count of completed runs |
| `failed_runs` | BIGINT | Count of failed runs |
| `avg_pass_rate` | DOUBLE PRECISION | Average pass rate (passed / total items) |
| `avg_identity_drift` | DOUBLE PRECISION | Average cosine distance |
| `avg_reflection_depth` | DOUBLE PRECISION | Average reflection depth score |
| `avg_reflection_honesty` | DOUBLE PRECISION | Average reflection honesty score |
| `avg_salience_error` | DOUBLE PRECISION | Average salience fit error |
| `latest_run_at` | TIMESTAMPTZ | Timestamp of most recent run on this date |

**Indexes:**

- `idx_benchmark_trends_unique` (UNIQUE) on `(benchmark_key, agent_config_id, run_date)`
- `idx_benchmark_trends_run_date` on `(run_date DESC)`
- `idx_benchmark_trends_benchmark_key` on `(benchmark_key)`

**Refresh:** Call `eval.refresh_benchmark_trends()` after bulk benchmark runs or daily via cron.

---

## Migrations

### Alembic Configuration

Eval migrations are separate from main app migrations:

```bash
# Apply eval migrations
make eval-db-init

# Create new eval migration
make eval-db-migrate MSG="add column to run_items"

# Downgrade last eval migration
make eval-db-downgrade
```

**Migration files:** `eval/migrations/versions/`  
**Alembic config:** `eval/migrations/alembic.ini`  
**Migration env:** `eval/migrations/env.py`

### Migration Idempotence

All DDL migrations use idempotent constructs:

- `CREATE TABLE IF NOT EXISTS`
- `CREATE INDEX IF NOT EXISTS`
- `DO $$ BEGIN ... IF NOT EXISTS ... END $$;` for roles and enums

**Integration test:** `tests/test_eval_storage_integration.py` verifies running migrations twice produces no changes.

---

## Partition Lifecycle

### Creating Future Partitions

Run monthly via cron or manually:

```bash
python3 scripts/eval/partition_manager.py --create-future --future-months 3
```

Creates partitions for the next 3 months (configurable).

### Detaching Old Partitions

Run monthly via cron or manually:

```bash
python3 scripts/eval/partition_manager.py --detach-old --retention-months 18
```

Detaches partitions older than 18 months (configurable). Detached partitions remain as standalone tables and can be:

- Archived to S3/GCS
- Dumped to `.sql` files
- Dropped: `DROP TABLE eval.benchmark_runs_2024_01;`

### Status Report

```bash
python3 scripts/eval/partition_manager.py --status
```

Shows all partitions with row counts.

---

## Integration Test

**File:** `tests/test_eval_storage_integration.py`

**Smoke test workflow:**

1. Create schema (apply all eval migrations)
2. Insert sample benchmark run + items + drift + quality + fits + sycophancy
3. Select as `atman_eval_reader` role (verify read access)
4. Attempt insert as `atman_eval_reader` (verify rejection)
5. Verify `atman_eval_writer` cannot write to `public.*`
6. Rerun migrations (verify idempotence)
7. Teardown schema

**Run:**

```bash
make eval-db-test
```

---

## Foreign Key Contract

### Dependency on `public.*` Schema

Eval tables reference production tables:

- `eval.benchmark_runs.identity_snapshot_id` → `public.identity_snapshots(id)`
- `eval.identity_drift.before_snapshot_id` → `public.identity_snapshots(id)`
- `eval.identity_drift.after_snapshot_id` → `public.identity_snapshots(id)`

**Risk:** If `public.identity_snapshots` schema changes (column rename, table drop, ID type change), eval migrations break.

**Mitigation:**

- Document FK contract in this file
- Add CI check that runs `make eval-db-init` after main migrations to detect breakage early

**Recovery:** If `public.*` schema evolves incompatibly, create an Alembic migration in `eval/migrations/versions/` to update foreign keys.

---

## Performance Considerations

### Partition Count

PostgreSQL planner degrades when partition count exceeds ~500. At 18-month retention = 18 partitions per table, we are well under limits. If retention expands to 10 years, consider quarterly partitions instead of monthly.

### Index Bloat

Each partition inherits indexes from the parent table. Monitor index size with:

```sql
SELECT schemaname, tablename, indexname, pg_size_pretty(pg_relation_size(indexrelid))
FROM pg_indexes
JOIN pg_class ON indexname = relname
WHERE schemaname = 'eval'
ORDER BY pg_relation_size(indexrelid) DESC;
```

If index size exceeds 10GB, consider partial indexes on recent partitions only.

### Materialized View Refresh

`eval.benchmark_trends` is refreshed CONCURRENTLY to avoid blocking readers. Refresh time scales with row count:

- <100K runs: <5 seconds
- 100K-1M runs: 30-60 seconds
- >1M runs: 2-5 minutes

If refresh time exceeds 5 minutes, consider incremental refresh (track last refresh timestamp, only aggregate new rows).

---

## Monitoring

### Metrics to Track

- **Partition count:** `SELECT COUNT(*) FROM pg_tables WHERE schemaname = 'eval' AND tablename LIKE 'benchmark_runs_%';`
- **Row count per partition:** See `scripts/eval/partition_manager.py --status`
- **Disk usage:** `SELECT pg_size_pretty(pg_database_size('atman'));`
- **Index bloat:** Query above
- **Materialized view staleness:** `SELECT MAX(latest_run_at) FROM eval.benchmark_trends;`

### Alerts

- **Partition count >50:** Review retention policy
- **Oldest partition >24 months:** Run `partition_manager.py --detach-old`
- **Materialized view staleness >7 days:** Run `eval.refresh_benchmark_trends()`

---

## References

- **Production isolation contract:** `docs/architecture/PROD_EVAL_BOUNDARY.md`
- **Epic E0 issue:** `docs/eval/issues/E0_storage_schema.md` (if exists)
- **PostgreSQL partitioning docs:** https://www.postgresql.org/docs/16/ddl-partitioning.html
- **Alembic docs:** https://alembic.sqlalchemy.org/
