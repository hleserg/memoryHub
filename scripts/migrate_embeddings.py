#!/usr/bin/env python3
"""
Migration script: Re-embed all facts from old dimension (2560) to new dimension (1024).

This script migrates the PostgreSQL vector store from the old Qwen-based embeddings
(dim=2560) to the new BGE-M3 embeddings (dim=1024).

Usage:
    python scripts/migrate_embeddings.py [--dry-run]

Environment variables:
    DATABASE_URL or ATMAN_DB_URL: PostgreSQL connection string
    EMBEDDING_MODEL: Ollama model name (default: bge-m3)
    EMBEDDING_OLLAMA_HOST: Ollama API URL (default: http://localhost:11434)
"""

import argparse
import os
import sys
from pathlib import Path

# Add src/ to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    print("ERROR: psycopg is required. Install with: pip install 'psycopg[binary]'")
    sys.exit(1)

from atman.adapters.memory.ollama_embedding import OllamaEmbeddingAdapter


def get_db_url() -> str:
    """Get database URL from environment."""
    url = os.environ.get("ATMAN_DB_URL") or os.environ.get("DATABASE_URL")
    if not url:
        print(
            "ERROR: DATABASE_URL or ATMAN_DB_URL environment variable is required",
            file=sys.stderr,
        )
        sys.exit(1)
    return url


def check_current_dimension(conn: psycopg.Connection) -> int | None:
    """Check the current dimension of the embedding column."""
    with conn.cursor() as cur:
        # Check if the table and column exist
        cur.execute(
            """
            SELECT column_name, udt_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'facts'
              AND column_name = 'embedding'
            """
        )
        result = cur.fetchone()
        if not result:
            print("INFO: No embedding column found in facts table")
            return None

        # Check dimension by querying a sample embedding
        cur.execute("SELECT embedding FROM public.facts WHERE embedding IS NOT NULL LIMIT 1")
        row = cur.fetchone()
        if not row or not row["embedding"]:
            print("INFO: No embeddings found in database")
            return None

        # Parse dimension from pgvector representation
        vec_str = str(row["embedding"])
        # pgvector format: [1.0, 2.0, 3.0, ...]
        dimension = len(vec_str.strip("[]").split(","))
        return dimension


def migrate_embeddings(dry_run: bool = False) -> None:
    """
    Migrate all embeddings from old dimension to new dimension.

    Args:
        dry_run: If True, only print what would be done without making changes
    """
    db_url = get_db_url()
    embedding_model = os.environ.get("EMBEDDING_MODEL", "bge-m3")
    ollama_host = os.environ.get("EMBEDDING_OLLAMA_HOST", "http://localhost:11434")

    print("Migration Configuration:")
    print(f"  Database: {db_url.split('@')[-1] if '@' in db_url else db_url}")
    print(f"  Embedding Model: {embedding_model}")
    print(f"  Ollama Host: {ollama_host}")
    print(f"  Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print()

    # Initialize embedding adapter
    try:
        embedding = OllamaEmbeddingAdapter(base_url=ollama_host, model=embedding_model)
        new_dimension = embedding.dimension()
        print(f"Target embedding dimension: {new_dimension}")
    except Exception as e:
        print(f"ERROR: Failed to initialize embedding adapter: {e}", file=sys.stderr)
        sys.exit(1)

    # Connect to database
    try:
        conn = psycopg.connect(db_url, row_factory=dict_row)
    except Exception as e:
        print(f"ERROR: Failed to connect to database: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        # Check current dimension
        current_dim = check_current_dimension(conn)
        if current_dim is None:
            print("INFO: No embeddings to migrate. Exiting.")
            return

        print(f"Current embedding dimension: {current_dim}")
        print()

        if current_dim == new_dimension:
            print(
                f"INFO: Embeddings are already at target dimension {new_dimension}. Nothing to do."
            )
            return

        # Count facts with embeddings
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM public.facts WHERE embedding IS NOT NULL")
            count_before = cur.fetchone()["count"]
            print(f"Found {count_before} facts with embeddings to migrate")
            print()

        if dry_run:
            print("DRY RUN: Would perform the following actions:")
            print(f"  1. Load all {count_before} facts with content and IDs")
            print(f"  2. Re-embed each fact using {embedding_model}")
            print(f"  3. Update embedding column with new {new_dimension}-dim vectors")
            print(f"  4. Verify {count_before} facts were updated")
            print()
            print("Run without --dry-run to apply changes")
            return

        # Load all facts with embeddings
        print("Loading facts from database...")
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, content
                FROM public.facts
                WHERE embedding IS NOT NULL
                ORDER BY created_at
                """
            )
            facts = cur.fetchall()

        print(f"Loaded {len(facts)} facts")
        print()

        # Re-embed and update
        print("Re-embedding facts with new model...")
        batch_size = 50
        updated_count = 0

        for i in range(0, len(facts), batch_size):
            batch = facts[i : i + batch_size]
            batch_ids = [f["id"] for f in batch]
            batch_texts = [f["content"] for f in batch]

            # Generate new embeddings
            try:
                new_embeddings = embedding.embed_batch(batch_texts)
            except Exception as e:
                print(f"ERROR: Failed to generate embeddings for batch {i // batch_size + 1}: {e}")
                raise

            # Update database
            with conn.cursor() as cur:
                for fact_id, new_vec in zip(batch_ids, new_embeddings, strict=True):
                    vec_str = "[" + ",".join(str(v) for v in new_vec) + "]"
                    cur.execute(
                        "UPDATE public.facts SET embedding = %s::vector, embed_model = %s WHERE id = %s",
                        (vec_str, embedding.model_name(), fact_id),
                    )
                    updated_count += 1

            conn.commit()

            progress = (i + len(batch)) / len(facts) * 100
            print(f"  Progress: {i + len(batch)}/{len(facts)} ({progress:.1f}%)", end="\r")

        print()
        print(f"Re-embedded {updated_count} facts")
        print()

        # Verify dimension
        new_dim = check_current_dimension(conn)
        print("Verification:")
        print(f"  New dimension: {new_dim}")
        print(f"  Expected dimension: {new_dimension}")

        if new_dim == new_dimension:
            print("  ✓ Migration successful!")
        else:
            print("  ✗ Dimension mismatch - migration may have failed")
            sys.exit(1)

        # Verify count
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM public.facts WHERE embedding IS NOT NULL")
            count_after = cur.fetchone()["count"]

        print(f"  Facts with embeddings before: {count_before}")
        print(f"  Facts with embeddings after: {count_after}")

        if count_after == count_before:
            print("  ✓ Count matches!")
        else:
            print(f"  ✗ Count mismatch: {count_before} → {count_after}")
            sys.exit(1)

    finally:
        conn.close()


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Migrate PostgreSQL vector embeddings from old to new dimension"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    args = parser.parse_args()

    try:
        migrate_embeddings(dry_run=args.dry_run)
    except KeyboardInterrupt:
        print("\nMigration interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\nERROR: Migration failed: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
