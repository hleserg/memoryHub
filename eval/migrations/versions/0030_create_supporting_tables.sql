-- =============================================================================
-- Migration 0030: create supporting evaluation tables
--
-- Mirror of eval/migrations/versions/0030_create_supporting_tables.py for human review.
-- The Python migration is the source of truth; this file is documentation-only.
--
-- Idempotent: safe to run multiple times.
-- =============================================================================

-- ── 1. run_items ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS eval.run_items (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL,
    item_key TEXT NOT NULL,
    verdict eval.verdict NOT NULL,
    score DOUBLE PRECISION,
    expected_value TEXT,
    actual_value TEXT,
    error_message TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'::jsonb,
    UNIQUE (run_id, item_key),
    CONSTRAINT fk_run_items_run
        FOREIGN KEY (run_id)
        REFERENCES eval.benchmark_runs(id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_run_items_run_id ON eval.run_items (run_id);
CREATE INDEX IF NOT EXISTS idx_run_items_verdict ON eval.run_items (verdict);
CREATE INDEX IF NOT EXISTS idx_run_items_started_at ON eval.run_items (started_at DESC);

COMMENT ON TABLE eval.run_items IS
    'Individual test items within a benchmark run. Each item represents one '
    'atomic test case (e.g., one question-answer pair, one identity drift check).';

GRANT SELECT, INSERT, UPDATE ON eval.run_items TO atman_eval_writer;
GRANT SELECT ON eval.run_items TO atman_eval_reader;
GRANT USAGE, SELECT ON SEQUENCE eval.run_items_id_seq TO atman_eval_writer;

-- ── 2. identity_drift ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS eval.identity_drift (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL,
    session_id TEXT NOT NULL,
    before_snapshot_id BIGINT NOT NULL,
    after_snapshot_id BIGINT NOT NULL,
    cosine_distance DOUBLE PRECISION NOT NULL,
    principle_violations INTEGER DEFAULT 0,
    voice_drift_score DOUBLE PRECISION,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'::jsonb,
    CONSTRAINT fk_identity_drift_run
        FOREIGN KEY (run_id)
        REFERENCES eval.benchmark_runs(id)
        ON DELETE CASCADE,
    CONSTRAINT fk_identity_drift_before
        FOREIGN KEY (before_snapshot_id)
        REFERENCES public.identity_snapshots(id)
        ON DELETE RESTRICT,
    CONSTRAINT fk_identity_drift_after
        FOREIGN KEY (after_snapshot_id)
        REFERENCES public.identity_snapshots(id)
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_identity_drift_run_id ON eval.identity_drift (run_id);
CREATE INDEX IF NOT EXISTS idx_identity_drift_session ON eval.identity_drift (session_id);
CREATE INDEX IF NOT EXISTS idx_identity_drift_before_snapshot
    ON eval.identity_drift (before_snapshot_id);
CREATE INDEX IF NOT EXISTS idx_identity_drift_after_snapshot
    ON eval.identity_drift (after_snapshot_id);
CREATE INDEX IF NOT EXISTS idx_identity_drift_cosine
    ON eval.identity_drift (cosine_distance DESC);

COMMENT ON TABLE eval.identity_drift IS
    'Identity coherence metrics. Tracks eigenstate drift between sessions using '
    'cosine distance, principle violations, and voice consistency.';

GRANT SELECT, INSERT, UPDATE ON eval.identity_drift TO atman_eval_writer;
GRANT SELECT ON eval.identity_drift TO atman_eval_reader;
GRANT USAGE, SELECT ON SEQUENCE eval.identity_drift_id_seq TO atman_eval_writer;

-- ── 3. reflection_quality ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS eval.reflection_quality (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL,
    reflection_id TEXT NOT NULL,
    reflection_type TEXT NOT NULL,
    depth_score DOUBLE PRECISION NOT NULL,
    honesty_score DOUBLE PRECISION,
    insight_count INTEGER DEFAULT 0,
    contradictions_detected INTEGER DEFAULT 0,
    judge_model TEXT,
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'::jsonb,
    CONSTRAINT fk_reflection_quality_run
        FOREIGN KEY (run_id)
        REFERENCES eval.benchmark_runs(id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_reflection_quality_run_id ON eval.reflection_quality (run_id);
CREATE INDEX IF NOT EXISTS idx_reflection_quality_reflection
    ON eval.reflection_quality (reflection_id);
CREATE INDEX IF NOT EXISTS idx_reflection_quality_type
    ON eval.reflection_quality (reflection_type);
CREATE INDEX IF NOT EXISTS idx_reflection_quality_depth
    ON eval.reflection_quality (depth_score DESC);

COMMENT ON TABLE eval.reflection_quality IS
    'Reflection depth and honesty metrics. Measures quality of micro/daily/deep '
    'reflections using LLM judge or rule-based heuristics.';

GRANT SELECT, INSERT, UPDATE ON eval.reflection_quality TO atman_eval_writer;
GRANT SELECT ON eval.reflection_quality TO atman_eval_reader;
GRANT USAGE, SELECT ON SEQUENCE eval.reflection_quality_id_seq TO atman_eval_writer;

-- ── 4. salience_fits ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS eval.salience_fits (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL,
    experience_id TEXT NOT NULL,
    predicted_salience DOUBLE PRECISION NOT NULL,
    actual_salience DOUBLE PRECISION NOT NULL,
    absolute_error DOUBLE PRECISION NOT NULL,
    context_similarity DOUBLE PRECISION,
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'::jsonb,
    CONSTRAINT fk_salience_fits_run
        FOREIGN KEY (run_id)
        REFERENCES eval.benchmark_runs(id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_salience_fits_run_id ON eval.salience_fits (run_id);
CREATE INDEX IF NOT EXISTS idx_salience_fits_experience
    ON eval.salience_fits (experience_id);
CREATE INDEX IF NOT EXISTS idx_salience_fits_error
    ON eval.salience_fits (absolute_error DESC);

COMMENT ON TABLE eval.salience_fits IS
    'Salience score prediction accuracy. Measures how well the agent''s predicted '
    'importance scores match ground truth or human-labeled salience.';

GRANT SELECT, INSERT, UPDATE ON eval.salience_fits TO atman_eval_writer;
GRANT SELECT ON eval.salience_fits TO atman_eval_reader;
GRANT USAGE, SELECT ON SEQUENCE eval.salience_fits_id_seq TO atman_eval_writer;

-- ── 5. sycophancy_pairs ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS eval.sycophancy_pairs (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL,
    question TEXT NOT NULL,
    correct_answer TEXT NOT NULL,
    user_belief TEXT NOT NULL,
    agent_response TEXT NOT NULL,
    verdict eval.verdict NOT NULL,
    sycophancy_score DOUBLE PRECISION,
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB DEFAULT '{}'::jsonb,
    CONSTRAINT fk_sycophancy_pairs_run
        FOREIGN KEY (run_id)
        REFERENCES eval.benchmark_runs(id)
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sycophancy_pairs_run_id ON eval.sycophancy_pairs (run_id);
CREATE INDEX IF NOT EXISTS idx_sycophancy_pairs_verdict ON eval.sycophancy_pairs (verdict);
CREATE INDEX IF NOT EXISTS idx_sycophancy_pairs_score
    ON eval.sycophancy_pairs (sycophancy_score DESC);

COMMENT ON TABLE eval.sycophancy_pairs IS
    'Sycophancy detection test pairs. Presents questions where user belief differs '
    'from ground truth and measures whether agent defers to user vs. provides truth.';

GRANT SELECT, INSERT, UPDATE ON eval.sycophancy_pairs TO atman_eval_writer;
GRANT SELECT ON eval.sycophancy_pairs TO atman_eval_reader;
GRANT USAGE, SELECT ON SEQUENCE eval.sycophancy_pairs_id_seq TO atman_eval_writer;
