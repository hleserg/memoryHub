-- =============================================================================
-- Migration 0040: create benchmark_trends materialized view and refresh function
--
-- Mirror of eval/migrations/versions/0040_create_benchmark_trends.py for human review.
-- The Python migration is the source of truth; this file is documentation-only.
--
-- Idempotent: safe to run multiple times.
-- =============================================================================

-- ── Materialized View ───────────────────────────────────────────────────────
CREATE MATERIALIZED VIEW IF NOT EXISTS eval.benchmark_trends AS
SELECT
    br.benchmark_key,
    br.agent_config_id,
    DATE_TRUNC('day', br.started_at) AS run_date,
    COUNT(*) AS total_runs,
    COUNT(*) FILTER (WHERE br.status = 'completed') AS completed_runs,
    COUNT(*) FILTER (WHERE br.status = 'failed') AS failed_runs,
    AVG(br.passed_items::FLOAT / NULLIF(br.total_items, 0)) AS avg_pass_rate,
    (
        SELECT AVG(cosine_distance)
        FROM eval.identity_drift
        WHERE run_id = br.id
    ) AS avg_identity_drift,
    (
        SELECT AVG(depth_score)
        FROM eval.reflection_quality
        WHERE run_id = br.id
    ) AS avg_reflection_depth,
    (
        SELECT AVG(honesty_score)
        FROM eval.reflection_quality
        WHERE run_id = br.id
    ) AS avg_reflection_honesty,
    (
        SELECT AVG(absolute_error)
        FROM eval.salience_fits
        WHERE run_id = br.id
    ) AS avg_salience_error,
    MAX(br.started_at) AS latest_run_at
FROM eval.benchmark_runs br
GROUP BY
    br.benchmark_key,
    br.agent_config_id,
    DATE_TRUNC('day', br.started_at),
    br.id
ORDER BY
    br.benchmark_key,
    br.agent_config_id,
    run_date DESC;

-- ── Indexes ─────────────────────────────────────────────────────────────────
CREATE UNIQUE INDEX IF NOT EXISTS idx_benchmark_trends_unique
    ON eval.benchmark_trends (benchmark_key, agent_config_id, run_date);

CREATE INDEX IF NOT EXISTS idx_benchmark_trends_run_date
    ON eval.benchmark_trends (run_date DESC);

CREATE INDEX IF NOT EXISTS idx_benchmark_trends_benchmark_key
    ON eval.benchmark_trends (benchmark_key);

-- ── Comments ────────────────────────────────────────────────────────────────
COMMENT ON MATERIALIZED VIEW eval.benchmark_trends IS
    'Aggregated benchmark trends over time. Refreshed manually via '
    'eval.refresh_benchmark_trends() or periodically via cron. Shows daily '
    'roll-ups of pass rates, identity drift, reflection quality, and salience fit.';

-- ── Grants ──────────────────────────────────────────────────────────────────
GRANT SELECT ON eval.benchmark_trends TO atman_eval_reader;
GRANT SELECT ON eval.benchmark_trends TO atman_eval_writer;

-- ── Refresh Function ────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION eval.refresh_benchmark_trends()
RETURNS VOID
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
    -- Try CONCURRENT refresh first (requires unique index)
    -- Falls back to non-concurrent if unique index is missing
    BEGIN
        REFRESH MATERIALIZED VIEW CONCURRENTLY eval.benchmark_trends;
    EXCEPTION
        WHEN feature_not_supported THEN
            -- Unique index missing, fall back to blocking refresh
            REFRESH MATERIALIZED VIEW eval.benchmark_trends;
        WHEN object_not_in_prerequisite_state THEN
            -- View being created/populated for first time
            REFRESH MATERIALIZED VIEW eval.benchmark_trends;
    END;
END;
$$;

COMMENT ON FUNCTION eval.refresh_benchmark_trends IS
    'Refresh the eval.benchmark_trends materialized view. Safe to call from cron '
    'or after bulk benchmark runs. Attempts CONCURRENTLY to avoid blocking readers, '
    'falls back to blocking refresh if unique index is not yet available.';

GRANT EXECUTE ON FUNCTION eval.refresh_benchmark_trends TO atman_eval_writer;
