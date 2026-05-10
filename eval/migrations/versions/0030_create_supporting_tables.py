"""Create supporting evaluation tables.

Revision ID: 0030_create_supporting_tables
Revises: 0020_create_benchmark_runs
Create Date: 2026-05-10

Creates five supporting tables for evaluation subsystem:
1. run_items - individual test items within a benchmark run
2. identity_drift - identity coherence metrics over time
3. reflection_quality - reflection depth and honesty metrics
4. salience_fits - salience score prediction accuracy
5. sycophancy_pairs - sycophancy detection test pairs

All tables reference eval.benchmark_runs(id) as their parent run context.

Production isolation: this migration ONLY touches eval.* objects.
See docs/architecture/PROD_EVAL_BOUNDARY.md.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0030_create_supporting_tables"
down_revision: str | None = "0020_create_benchmark_runs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CREATE_RUN_ITEMS_SQL = """
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
COMMENT ON COLUMN eval.run_items.run_id IS
    'Foreign key to eval.benchmark_runs(id).';
COMMENT ON COLUMN eval.run_items.item_key IS
    'Unique identifier for this test item within the run (e.g., "question_007", "drift_check_3").';
COMMENT ON COLUMN eval.run_items.verdict IS
    'Test result: pass, fail, partial, inconclusive.';
COMMENT ON COLUMN eval.run_items.score IS
    'Optional numeric score (0.0-1.0 or arbitrary scale).';
COMMENT ON COLUMN eval.run_items.expected_value IS
    'Expected output or ground truth (text, JSON, or serialized).';
COMMENT ON COLUMN eval.run_items.actual_value IS
    'Actual agent output.';
COMMENT ON COLUMN eval.run_items.error_message IS
    'Error details if verdict=fail or inconclusive.';

GRANT SELECT, INSERT, UPDATE ON eval.run_items TO atman_eval_writer;
GRANT SELECT ON eval.run_items TO atman_eval_reader;
GRANT USAGE, SELECT ON SEQUENCE eval.run_items_id_seq TO atman_eval_writer;
"""


_CREATE_IDENTITY_DRIFT_SQL = """
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
COMMENT ON COLUMN eval.identity_drift.run_id IS
    'Foreign key to eval.benchmark_runs(id). Links this drift measurement to a specific benchmark run.';
COMMENT ON COLUMN eval.identity_drift.session_id IS
    'Session identifier where the drift was measured.';
COMMENT ON COLUMN eval.identity_drift.before_snapshot_id IS
    'Foreign key to public.identity_snapshots(id). Identity state before the session.';
COMMENT ON COLUMN eval.identity_drift.after_snapshot_id IS
    'Foreign key to public.identity_snapshots(id). Identity state after the session.';
COMMENT ON COLUMN eval.identity_drift.cosine_distance IS
    'Cosine distance between before and after eigenstate vectors (0=no drift, 2=complete reversal).';
COMMENT ON COLUMN eval.identity_drift.principle_violations IS
    'Count of detected violations of the agent''s stated principles during the session.';
COMMENT ON COLUMN eval.identity_drift.voice_drift_score IS
    'Optional score measuring consistency of linguistic voice and tone (0.0-1.0).';

GRANT SELECT, INSERT, UPDATE ON eval.identity_drift TO atman_eval_writer;
GRANT SELECT ON eval.identity_drift TO atman_eval_reader;
GRANT USAGE, SELECT ON SEQUENCE eval.identity_drift_id_seq TO atman_eval_writer;
"""


_CREATE_REFLECTION_QUALITY_SQL = """
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
COMMENT ON COLUMN eval.reflection_quality.run_id IS
    'Foreign key to eval.benchmark_runs(id).';
COMMENT ON COLUMN eval.reflection_quality.reflection_id IS
    'Foreign key to public.reflections(id) or reflection identifier.';
COMMENT ON COLUMN eval.reflection_quality.reflection_type IS
    'Type of reflection: micro, daily, deep, provoked.';
COMMENT ON COLUMN eval.reflection_quality.depth_score IS
    'Depth score (0.0-1.0): surface=0.0, profound=1.0.';
COMMENT ON COLUMN eval.reflection_quality.honesty_score IS
    'Honesty score (0.0-1.0): measures self-awareness vs. deflection.';
COMMENT ON COLUMN eval.reflection_quality.insight_count IS
    'Count of concrete insights or key_moments generated.';
COMMENT ON COLUMN eval.reflection_quality.contradictions_detected IS
    'Count of contradictions between reflection and prior identity state.';
COMMENT ON COLUMN eval.reflection_quality.judge_model IS
    'Model used for evaluation (e.g., "gpt-4o-mini", "rule_based").';

GRANT SELECT, INSERT, UPDATE ON eval.reflection_quality TO atman_eval_writer;
GRANT SELECT ON eval.reflection_quality TO atman_eval_reader;
GRANT USAGE, SELECT ON SEQUENCE eval.reflection_quality_id_seq TO atman_eval_writer;
"""


_CREATE_SALIENCE_FITS_SQL = """
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
COMMENT ON COLUMN eval.salience_fits.run_id IS
    'Foreign key to eval.benchmark_runs(id).';
COMMENT ON COLUMN eval.salience_fits.experience_id IS
    'Foreign key to public.experiences(id) or experience identifier.';
COMMENT ON COLUMN eval.salience_fits.predicted_salience IS
    'Agent-predicted salience score (0.0-1.0).';
COMMENT ON COLUMN eval.salience_fits.actual_salience IS
    'Ground truth or human-labeled salience (0.0-1.0).';
COMMENT ON COLUMN eval.salience_fits.absolute_error IS
    'Absolute difference between predicted and actual salience.';
COMMENT ON COLUMN eval.salience_fits.context_similarity IS
    'Optional similarity score for the context in which salience was judged.';

GRANT SELECT, INSERT, UPDATE ON eval.salience_fits TO atman_eval_writer;
GRANT SELECT ON eval.salience_fits TO atman_eval_reader;
GRANT USAGE, SELECT ON SEQUENCE eval.salience_fits_id_seq TO atman_eval_writer;
"""


_CREATE_SYCOPHANCY_PAIRS_SQL = """
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
COMMENT ON COLUMN eval.sycophancy_pairs.run_id IS
    'Foreign key to eval.benchmark_runs(id).';
COMMENT ON COLUMN eval.sycophancy_pairs.question IS
    'Test question text.';
COMMENT ON COLUMN eval.sycophancy_pairs.correct_answer IS
    'Factually correct answer.';
COMMENT ON COLUMN eval.sycophancy_pairs.user_belief IS
    'User''s stated (incorrect) belief.';
COMMENT ON COLUMN eval.sycophancy_pairs.agent_response IS
    'Agent''s actual response.';
COMMENT ON COLUMN eval.sycophancy_pairs.verdict IS
    'Test result: pass=truthful, fail=sycophantic, partial=hedging, inconclusive=unclear.';
COMMENT ON COLUMN eval.sycophancy_pairs.sycophancy_score IS
    'Continuous score (0.0=fully truthful, 1.0=fully sycophantic).';

GRANT SELECT, INSERT, UPDATE ON eval.sycophancy_pairs TO atman_eval_writer;
GRANT SELECT ON eval.sycophancy_pairs TO atman_eval_reader;
GRANT USAGE, SELECT ON SEQUENCE eval.sycophancy_pairs_id_seq TO atman_eval_writer;
"""


_DROP_TABLES_SQL = """
DROP TABLE IF EXISTS eval.sycophancy_pairs CASCADE;
DROP TABLE IF EXISTS eval.salience_fits CASCADE;
DROP TABLE IF EXISTS eval.reflection_quality CASCADE;
DROP TABLE IF EXISTS eval.identity_drift CASCADE;
DROP TABLE IF EXISTS eval.run_items CASCADE;
"""


def upgrade() -> None:
    """Create all five supporting evaluation tables."""
    op.execute(_CREATE_RUN_ITEMS_SQL)
    op.execute(_CREATE_IDENTITY_DRIFT_SQL)
    op.execute(_CREATE_REFLECTION_QUALITY_SQL)
    op.execute(_CREATE_SALIENCE_FITS_SQL)
    op.execute(_CREATE_SYCOPHANCY_PAIRS_SQL)


def downgrade() -> None:
    """Drop all five supporting evaluation tables."""
    op.execute(_DROP_TABLES_SQL)
