#!/usr/bin/env python3
"""Partition lifecycle manager for eval.benchmark_runs.

Manages monthly RANGE partitions for eval.benchmark_runs:
- Creates future partitions (next 3 months by default)
- Detaches and archives old partitions (>18 months by default)
- Reports partition status

Usage:
    python3 scripts/eval/partition_manager.py --create-future
    python3 scripts/eval/partition_manager.py --detach-old
    python3 scripts/eval/partition_manager.py --status
    python3 scripts/eval/partition_manager.py --help

Requirements:
    pip install 'atman[eval]'  # includes psycopg and sqlalchemy

Environment variables:
    POSTGRES_URL - PostgreSQL connection URL (default: from config or localhost)

Production isolation: this script ONLY touches eval.benchmark_runs partitions.
See docs/architecture/PROD_EVAL_BOUNDARY.md.
"""

import argparse
import sys
from datetime import UTC, datetime

try:
    import psycopg
    from psycopg import sql
    from dateutil.relativedelta import relativedelta
except ImportError:
    print(
        "Error: required packages not installed. Run: pip install 'atman[eval]'",
        file=sys.stderr,
    )
    sys.exit(1)


DEFAULT_DB_URL = "postgresql://localhost:5432/atman"
DEFAULT_FUTURE_MONTHS = 3
DEFAULT_RETENTION_MONTHS = 18


def get_db_url() -> str:
    """Get PostgreSQL URL from environment or config."""
    import os

    return os.environ.get("POSTGRES_URL", DEFAULT_DB_URL)


def safe_db_url_for_logging(db_url: str) -> str:
    """Return safe version of DB URL for logging (without credentials)."""
    from urllib.parse import urlparse
    
    try:
        parsed = urlparse(db_url)
        hostname = parsed.hostname or "localhost"
        port = parsed.port or 5432
        database = parsed.path.lstrip("/") or "postgres"
        return f"{hostname}:{port}/{database}"
    except Exception:
        # Fallback: try to hide password
        if "@" in db_url:
            return db_url.split("@")[-1]
        return "***"


def list_existing_partitions(conn: psycopg.Connection) -> list[str]:
    """List all existing benchmark_runs partitions."""
    cur = conn.execute("""
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'eval'
          AND tablename LIKE 'benchmark_runs_%'
        ORDER BY tablename;
    """)
    return [row[0] for row in cur.fetchall()]


def create_partition(
    conn: psycopg.Connection, year: int, month: int, *, dry_run: bool = False
) -> None:
    """Create a monthly partition for the given year/month."""
    suffix = f"{year:04d}_{month:02d}"
    start_date = f"{year:04d}-{month:02d}-01"
    next_month = month + 1
    next_year = year
    if next_month > 12:
        next_month = 1
        next_year += 1
    end_date = f"{next_year:04d}-{next_month:02d}-01"

    sql = f"""
    CREATE TABLE IF NOT EXISTS eval.benchmark_runs_{suffix}
        PARTITION OF eval.benchmark_runs
        FOR VALUES FROM ('{start_date}') TO ('{end_date}');
    """
    print(f"Creating partition: benchmark_runs_{suffix} ({start_date} to {end_date})")
    if dry_run:
        print(f"  [DRY RUN] Would execute:\n{sql}")
    else:
        conn.execute(sql)
        conn.commit()
        print(f"  ✓ Created benchmark_runs_{suffix}")


def detach_partition(
    conn: psycopg.Connection, partition_name: str, *, dry_run: bool = False
) -> None:
    """Detach an old partition (preparing for archive or drop)."""
    sql = f"ALTER TABLE eval.benchmark_runs DETACH PARTITION eval.{partition_name};"
    print(f"Detaching partition: {partition_name}")
    if dry_run:
        print(f"  [DRY RUN] Would execute:\n{sql}")
    else:
        conn.execute(sql)
        conn.commit()
        print(f"  ✓ Detached {partition_name}")


def create_future_partitions(
    conn: psycopg.Connection, months: int = DEFAULT_FUTURE_MONTHS, *, dry_run: bool = False
) -> None:
    """Create partitions for the next N months."""
    existing = list_existing_partitions(conn)
    now = datetime.now(UTC)
    for offset in range(months):
        target_date = now + relativedelta(months=offset)
        year = target_date.year
        month = target_date.month
        suffix = f"{year:04d}_{month:02d}"
        if f"benchmark_runs_{suffix}" in existing:
            print(f"Partition benchmark_runs_{suffix} already exists, skipping.")
        else:
            create_partition(conn, year, month, dry_run=dry_run)


def detach_old_partitions(
    conn: psycopg.Connection, retention_months: int = DEFAULT_RETENTION_MONTHS, *, dry_run: bool = False
) -> None:
    """Detach partitions older than retention_months."""
    existing = list_existing_partitions(conn)
    now = datetime.now(UTC)
    cutoff = now - relativedelta(months=retention_months)
    cutoff_suffix = f"{cutoff.year:04d}_{cutoff.month:02d}"

    old_partitions = [p for p in existing if p.replace("benchmark_runs_", "") < cutoff_suffix]
    if not old_partitions:
        print(f"No partitions older than {cutoff_suffix} found.")
        return

    for partition in old_partitions:
        detach_partition(conn, partition, dry_run=dry_run)


def show_status(conn: psycopg.Connection) -> None:
    """Show current partition status."""
    partitions = list_existing_partitions(conn)
    print(f"\nTotal partitions: {len(partitions)}\n")
    if not partitions:
        print("No partitions found.")
        return

    print("Existing partitions:")
    for partition in partitions:
        # Get row count for each partition (safe identifier quoting)
        query = sql.SQL("SELECT COUNT(*) FROM {}.{}").format(
            sql.Identifier("eval"),
            sql.Identifier(partition)
        )
        cur = conn.execute(query)
        count = cur.fetchone()[0]  # type: ignore[index]
        print(f"  {partition:30s} {count:>10,d} rows")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Manage eval.benchmark_runs partitions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--create-future",
        action="store_true",
        help=f"Create partitions for next {DEFAULT_FUTURE_MONTHS} months",
    )
    parser.add_argument(
        "--detach-old",
        action="store_true",
        help=f"Detach partitions older than {DEFAULT_RETENTION_MONTHS} months",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show partition status",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print SQL without executing",
    )
    parser.add_argument(
        "--future-months",
        type=int,
        default=DEFAULT_FUTURE_MONTHS,
        help=f"Number of future months to create (default: {DEFAULT_FUTURE_MONTHS})",
    )
    parser.add_argument(
        "--retention-months",
        type=int,
        default=DEFAULT_RETENTION_MONTHS,
        help=f"Retention period in months (default: {DEFAULT_RETENTION_MONTHS})",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="PostgreSQL URL (default: POSTGRES_URL env or localhost)",
    )

    args = parser.parse_args()

    # Validate arguments
    if args.future_months < 1 or args.future_months > 120:
        parser.error("--future-months must be between 1 and 120")
    if args.retention_months < 1 or args.retention_months > 240:
        parser.error("--retention-months must be between 1 and 240")

    if not (args.create_future or args.detach_old or args.status):
        parser.print_help()
        sys.exit(1)

    db_url = args.db_url or get_db_url()
    print(f"Connecting to: {safe_db_url_for_logging(db_url)}")

    try:
        with psycopg.connect(db_url) as conn:
            if args.status:
                show_status(conn)
            if args.create_future:
                create_future_partitions(
                    conn, months=args.future_months, dry_run=args.dry_run
                )
            if args.detach_old:
                detach_old_partitions(
                    conn, retention_months=args.retention_months, dry_run=args.dry_run
                )
    except psycopg.Error as e:
        print(f"Database error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
