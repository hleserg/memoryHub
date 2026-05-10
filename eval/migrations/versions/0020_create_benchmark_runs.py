"""Create eval.benchmark_runs partitioned table.

Revision ID: 0020_create_benchmark_runs
Revises: 0010_create_eval_schema
Create Date: 2026-05-10

Creates the core benchmark_runs table with monthly range partitioning on
started_at. Includes one initial partition for the current month and
next month. Additional partitions are managed by the partition lifecycle
script (epic E0 subtask #220).

Foreign keys:
- identity_snapshot_id references public.identity_snapshots(id)
  (requires that the main app schema has identity_snapshots with stable IDs)

Production isolation: this migration ONLY touches eval.* objects.
See docs/architecture/PROD_EVAL_BOUNDARY.md.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from alembic import op

revision: str = "0020_create_benchmark_runs"
down_revision: str | None = "0010_create_eval_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _get_partition_bounds() -> tuple[str, str, str, str]:
    """Compute bounds for current and next month partitions.

    Returns: (current_start, current_end, next_start, next_end) as ISO strings.
    """
    now = datetime.now(UTC)
    current_year = now.year
    current_month = now.month
    next_month = current_month + 1
    next_year = current_year
    if next_month > 12:
        next_month = 1
        next_year += 1
    following_month = next_month + 1
    following_year = next_year
    if following_month > 12:
        following_month = 1
        following_year += 1

    current_start = f"{current_year:04d}-{current_month:02d}-01"
    current_end = f"{next_year:04d}-{next_month:02d}-01"
    next_start = current_end
    next_end = f"{following_year:04d}-{following_month:02d}-01"

    return current_start, current_end, next_start, next_end


_CREATE_TABLE_SQL = """
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
    PRIMARY KEY (id, started_at),
    CONSTRAINT fk_benchmark_runs_identity_snapshot
        FOREIGN KEY (identity_snapshot_id)
        REFERENCES public.identity_snapshots(id)
        ON DELETE SET NULL
) PARTITION BY RANGE (started_at);

CREATE INDEX IF NOT EXISTS idx_benchmark_runs_benchmark_key
    ON eval.benchmark_runs (benchmark_key, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_benchmark_runs_agent_config
    ON eval.benchmark_runs (agent_config_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_benchmark_runs_identity_snapshot
    ON eval.benchmark_runs (identity_snapshot_id);
CREATE INDEX IF NOT EXISTS idx_benchmark_runs_status
    ON eval.benchmark_runs (status);

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

-- Grant permissions to eval roles
GRANT SELECT, INSERT, UPDATE ON eval.benchmark_runs TO atman_eval_writer;
GRANT SELECT ON eval.benchmark_runs TO atman_eval_reader;
"""


def _create_partition_sql(suffix: str, start_date: str, end_date: str) -> str:
    """Generate SQL to create one monthly partition."""
    return f"""
CREATE TABLE IF NOT EXISTS eval.benchmark_runs_{suffix}
    PARTITION OF eval.benchmark_runs
    FOR VALUES FROM ('{start_date}') TO ('{end_date}');
"""


_DROP_TABLE_SQL = "DROP TABLE IF EXISTS eval.benchmark_runs CASCADE;"


def upgrade() -> None:
    """Create benchmark_runs partitioned table and initial partitions."""
    # Verify public.identity_snapshots exists
    bind = op.get_bind()
    result = bind.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema='public' AND table_name='identity_snapshots';"
    ).fetchone()
    if not result:
        import warnings
        warnings.warn(
            "Table public.identity_snapshots does not exist. "
            "Foreign key constraint will be deferred. Run main migrations first.",
            UserWarning,
            stacklevel=2,
        )
    
    # Create the partitioned parent table
    op.execute(_CREATE_TABLE_SQL)

    # Create partitions for current and next month using bounds computation
    current_start, current_end, next_start, next_end = _get_partition_bounds()
    
    # Extract year/month from start dates for suffix
    now = datetime.now(UTC)
    current_suffix = f"{now.year:04d}_{now.month:02d}"
    next_month = now.month + 1
    next_year = now.year
    if next_month > 12:
        next_month = 1
        next_year += 1
    next_suffix = f"{next_year:04d}_{next_month:02d}"

    op.execute(_create_partition_sql(current_suffix, current_start, current_end))
    op.execute(_create_partition_sql(next_suffix, next_start, next_end))


def downgrade() -> None:
    """Drop benchmark_runs table and all partitions."""
    op.execute(_DROP_TABLE_SQL)
