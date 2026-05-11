-- =============================================================================
-- Migration 0020: create eval.benchmark_runs partitioned table
--
-- Mirror of eval/migrations/versions/0020_create_benchmark_runs.py for human review.
-- The Python migration is the source of truth; this file is documentation-only.
--
-- Idempotent: safe to run multiple times.
-- =============================================================================

-- ── Create partitioned parent table ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS eval.benchmark_runs (
    id BIGSERIAL NOT NULL,
    benchmark_key TEXT NOT NULL,
    agent_config_id TEXT,
    identity_snapshot_id BIGINT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    status eval.run_status NOT NULL DEFAULT 'pending',
    total_items INTEGER DEFAULT 0,
    passed_items INTEGER DEFAULT 0,
    failed_items INTEGER DEFAULT 0,
    metadata JSONB DEFAULT '{}'::jsonb,
    PRIMARY KEY (id, started_at)
) PARTITION BY RANGE (started_at);

-- ── Indexes ─────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_benchmark_runs_benchmark_key
    ON eval.benchmark_runs (benchmark_key, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_benchmark_runs_agent_config
    ON eval.benchmark_runs (agent_config_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_benchmark_runs_identity_snapshot
    ON eval.benchmark_runs (identity_snapshot_id);
CREATE INDEX IF NOT EXISTS idx_benchmark_runs_status
    ON eval.benchmark_runs (status);

-- ── Comments ────────────────────────────────────────────────────────────────
COMMENT ON TABLE eval.benchmark_runs IS
    'Core benchmark run metadata. Partitioned monthly by started_at. '
    'Each run represents one execution of a benchmark suite against a specific '
    'agent configuration and optional identity snapshot.';
COMMENT ON COLUMN eval.benchmark_runs.benchmark_key IS
    'Unique identifier for the benchmark (e.g., "G1_continuous_identity", "EB3_sycophancy").';
COMMENT ON COLUMN eval.benchmark_runs.agent_config_id IS
    'Optional identifier for agent configuration (e.g., "agent_A", "agent_B_with_rerank").';
COMMENT ON COLUMN eval.benchmark_runs.identity_snapshot_id IS
    'Foreign key to public.identity_snapshots(id). NULL if benchmark does not depend on identity state.';
COMMENT ON COLUMN eval.benchmark_runs.started_at IS
    'Timestamp when the run started (partition key).';
COMMENT ON COLUMN eval.benchmark_runs.completed_at IS
    'Timestamp when the run finished. NULL if still running or failed before completion.';
COMMENT ON COLUMN eval.benchmark_runs.status IS
    'Run status: pending, running, completed, failed, cancelled.';
COMMENT ON COLUMN eval.benchmark_runs.metadata IS
    'Arbitrary run metadata (git_sha, runner_version, environment_vars, etc.).';

-- ── Grants ──────────────────────────────────────────────────────────────────
GRANT SELECT, INSERT, UPDATE ON eval.benchmark_runs TO atman_eval_writer;
GRANT SELECT ON eval.benchmark_runs TO atman_eval_reader;

-- ── Initial partitions (example for 2026-05) ────────────────────────────────
-- The Python migration computes these dynamically based on current date.
-- Example partitions shown here are placeholders only.
--
-- CREATE TABLE eval.benchmark_runs_2026_05
--     PARTITION OF eval.benchmark_runs
--     FOR VALUES FROM ('2026-05-01') TO ('2026-06-01');
-- CREATE TABLE eval.benchmark_runs_2026_06
--     PARTITION OF eval.benchmark_runs
--     FOR VALUES FROM ('2026-06-01') TO ('2026-07-01');

-- ── DEFAULT partition (safety net) ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS eval.benchmark_runs_default
    PARTITION OF eval.benchmark_runs DEFAULT;

-- ── Foreign key constraint (conditionally added) ─────────────────────────────
-- The Python migration adds this constraint only if public.identity_snapshots exists.
-- If running this SQL manually, ensure the main schema migration (identity_snapshots)
-- has been applied first, or skip this section to avoid constraint violation.
--
-- ALTER TABLE eval.benchmark_runs
--     ADD CONSTRAINT fk_benchmark_runs_identity_snapshot
--         FOREIGN KEY (identity_snapshot_id)
--         REFERENCES public.identity_snapshots(id)
--         ON DELETE SET NULL;
