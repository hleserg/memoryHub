-- =============================================================================
-- Migration 0011: create eval.benchmark_runs partitioned table
--
-- Mirror of eval/migrations/versions/0011_create_benchmark_runs.py for human
-- review. The Python migration is the source of truth (it computes the
-- current-month partition bounds at upgrade time); this file is documented
-- with a placeholder month (YYYY_MM) and exact bounds.
--
-- Idempotent: safe to run multiple times.
-- =============================================================================

-- ── Partitioned root table ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS eval.benchmark_runs (
    id              UUID NOT NULL DEFAULT gen_random_uuid(),
    benchmark_id    TEXT NOT NULL,
    benchmark_kind  TEXT NOT NULL,
    variant         TEXT NOT NULL DEFAULT 'default',
    git_sha         TEXT NOT NULL,
    model_llm       TEXT NOT NULL,
    model_embed     TEXT NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at        TIMESTAMPTZ,
    status          eval.run_status NOT NULL DEFAULT 'pending',
    verdict         eval.verdict,
    metrics_json    JSONB NOT NULL DEFAULT '{}'::jsonb,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, started_at),
    CHECK (ended_at IS NULL OR ended_at >= started_at)
)
PARTITION BY RANGE (started_at);

ALTER TABLE eval.benchmark_runs OWNER TO atman_eval_owner;

COMMENT ON TABLE eval.benchmark_runs IS
    'Central registry of every benchmark execution. Partitioned by month on '
    'started_at. PRIMARY KEY (id, started_at) is a partitioning requirement; '
    'id alone is globally unique by UUIDv4.';

-- ── Initial partition for the current calendar month ────────────────────────
-- Replace YYYY_MM with the actual year and month at upgrade time. The Python
-- migration computes this from `datetime.now(timezone.utc)`. Bounds use
-- inclusive lower and exclusive upper, aligning with PG's
-- `FOR VALUES FROM ... TO ...` semantics.
CREATE TABLE IF NOT EXISTS eval.benchmark_runs_YYYY_MM
    PARTITION OF eval.benchmark_runs
    FOR VALUES FROM ('YYYY-MM-01 00:00:00+00') TO ('YYYY-MM+1-01 00:00:00+00');

ALTER TABLE eval.benchmark_runs_YYYY_MM OWNER TO atman_eval_owner;

-- ── Default partition safety net ────────────────────────────────────────────
-- Prevents otherwise-valid inserts from failing at the next calendar boundary
-- before a monthly partition maintenance job exists.
CREATE TABLE IF NOT EXISTS eval.benchmark_runs_default
    PARTITION OF eval.benchmark_runs DEFAULT;

ALTER TABLE eval.benchmark_runs_default OWNER TO atman_eval_owner;

-- ── Indexes on the partitioned root (inherited by every partition) ──────────
CREATE INDEX IF NOT EXISTS idx_benchmark_runs_benchmark_started
    ON eval.benchmark_runs (benchmark_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_benchmark_runs_git_sha
    ON eval.benchmark_runs (git_sha);
CREATE INDEX IF NOT EXISTS idx_benchmark_runs_metrics_gin
    ON eval.benchmark_runs USING GIN (metrics_json);

-- ── Grants ──────────────────────────────────────────────────────────────────
GRANT SELECT, INSERT, UPDATE ON eval.benchmark_runs TO atman_eval_writer;
GRANT SELECT ON eval.benchmark_runs TO atman_eval_reader;
