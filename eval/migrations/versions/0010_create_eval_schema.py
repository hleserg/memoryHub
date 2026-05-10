"""Create eval schema, roles, grants, and enum types.

Revision ID: 0010_create_eval_schema
Revises:
Create Date: 2026-05-10

This migration is the foundation for epic E0 (Storage Schema for Evaluation
Subsystem). It creates the ``eval`` schema, three least-privilege roles
(``atman_eval_owner`` / ``atman_eval_writer`` / ``atman_eval_reader``), default
privilege grants for future tables, and the two domain enums used by the
benchmark tables (``eval.run_status`` and ``eval.verdict``).

The migration is intentionally idempotent: roles are only created when missing
(``DO $$ ... pg_roles ... $$`` guard) and the schema uses
``CREATE SCHEMA IF NOT EXISTS``. Re-running is a no-op.

Production isolation: this migration ONLY touches the ``eval`` schema and the
three eval roles. It MUST NOT modify any object under ``public.*``. See
``docs/architecture/PROD_EVAL_BOUNDARY.md``.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010_create_eval_schema"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CREATE_ROLES_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'atman_eval_owner') THEN
        CREATE ROLE atman_eval_owner NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'atman_eval_writer') THEN
        CREATE ROLE atman_eval_writer NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'atman_eval_reader') THEN
        CREATE ROLE atman_eval_reader NOLOGIN;
    END IF;
END
$$;
"""


_CREATE_SCHEMA_SQL = "CREATE SCHEMA IF NOT EXISTS eval AUTHORIZATION atman_eval_owner;"


_GRANT_USAGE_SQL = """
GRANT USAGE ON SCHEMA eval TO atman_eval_writer, atman_eval_reader;
"""


# Two parallel sets of ALTER DEFAULT PRIVILEGES are issued so the default
# grants fire regardless of which role actually creates the table:
#
#   1. ``FOR ROLE atman_eval_owner`` — fires when a future migration uses
#      ``SET ROLE atman_eval_owner;`` before ``CREATE TABLE eval.<...>``.
#
#   2. No ``FOR ROLE`` clause — the alter applies to ``current_user`` at the
#      time the ALTER itself runs (the migration runner, typically ``atman``
#      in dev/CI, ``atman_admin`` in prod). This is the path that actually
#      fires for tables created by subsequent eval migrations, since
#      ``eval/migrations/env.py`` connects as the application user, not
#      ``atman_eval_owner``.
#
# Each downstream eval migration should ALSO issue explicit
# ``GRANT SELECT, INSERT, UPDATE ON eval.<table> TO atman_eval_writer;`` (and
# ``GRANT SELECT ... TO atman_eval_reader;``) for clarity and to insulate
# against surprises if the connecting role changes.
_DEFAULT_PRIVILEGES_SQL = """
ALTER DEFAULT PRIVILEGES FOR ROLE atman_eval_owner IN SCHEMA eval
    GRANT SELECT, INSERT, UPDATE ON TABLES TO atman_eval_writer;
ALTER DEFAULT PRIVILEGES FOR ROLE atman_eval_owner IN SCHEMA eval
    GRANT SELECT ON TABLES TO atman_eval_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE atman_eval_owner IN SCHEMA eval
    GRANT USAGE, SELECT ON SEQUENCES TO atman_eval_writer;
ALTER DEFAULT PRIVILEGES FOR ROLE atman_eval_owner IN SCHEMA eval
    GRANT USAGE ON SEQUENCES TO atman_eval_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE atman_eval_owner IN SCHEMA eval
    GRANT EXECUTE ON FUNCTIONS TO atman_eval_writer;
ALTER DEFAULT PRIVILEGES FOR ROLE atman_eval_owner IN SCHEMA eval
    GRANT EXECUTE ON FUNCTIONS TO atman_eval_reader;

ALTER DEFAULT PRIVILEGES IN SCHEMA eval
    GRANT SELECT, INSERT, UPDATE ON TABLES TO atman_eval_writer;
ALTER DEFAULT PRIVILEGES IN SCHEMA eval
    GRANT SELECT ON TABLES TO atman_eval_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA eval
    GRANT USAGE, SELECT ON SEQUENCES TO atman_eval_writer;
ALTER DEFAULT PRIVILEGES IN SCHEMA eval
    GRANT USAGE ON SEQUENCES TO atman_eval_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA eval
    GRANT EXECUTE ON FUNCTIONS TO atman_eval_writer;
ALTER DEFAULT PRIVILEGES IN SCHEMA eval
    GRANT EXECUTE ON FUNCTIONS TO atman_eval_reader;
"""


_CREATE_ENUMS_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_type t
        JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE t.typname = 'run_status' AND n.nspname = 'eval'
    ) THEN
        CREATE TYPE eval.run_status AS ENUM (
            'pending', 'running', 'completed', 'failed', 'cancelled'
        );
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_type t
        JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE t.typname = 'verdict' AND n.nspname = 'eval'
    ) THEN
        CREATE TYPE eval.verdict AS ENUM (
            'pass', 'fail', 'partial', 'inconclusive'
        );
    END IF;
END
$$;
"""


_DROP_ENUMS_SQL = """
DROP TYPE IF EXISTS eval.verdict;
DROP TYPE IF EXISTS eval.run_status;
"""


_REVOKE_DEFAULTS_SQL = """
ALTER DEFAULT PRIVILEGES FOR ROLE atman_eval_owner IN SCHEMA eval
    REVOKE SELECT, INSERT, UPDATE ON TABLES FROM atman_eval_writer;
ALTER DEFAULT PRIVILEGES FOR ROLE atman_eval_owner IN SCHEMA eval
    REVOKE SELECT ON TABLES FROM atman_eval_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE atman_eval_owner IN SCHEMA eval
    REVOKE USAGE, SELECT ON SEQUENCES FROM atman_eval_writer;
ALTER DEFAULT PRIVILEGES FOR ROLE atman_eval_owner IN SCHEMA eval
    REVOKE USAGE ON SEQUENCES FROM atman_eval_reader;
ALTER DEFAULT PRIVILEGES FOR ROLE atman_eval_owner IN SCHEMA eval
    REVOKE EXECUTE ON FUNCTIONS FROM atman_eval_writer;
ALTER DEFAULT PRIVILEGES FOR ROLE atman_eval_owner IN SCHEMA eval
    REVOKE EXECUTE ON FUNCTIONS FROM atman_eval_reader;

ALTER DEFAULT PRIVILEGES IN SCHEMA eval
    REVOKE SELECT, INSERT, UPDATE ON TABLES FROM atman_eval_writer;
ALTER DEFAULT PRIVILEGES IN SCHEMA eval
    REVOKE SELECT ON TABLES FROM atman_eval_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA eval
    REVOKE USAGE, SELECT ON SEQUENCES FROM atman_eval_writer;
ALTER DEFAULT PRIVILEGES IN SCHEMA eval
    REVOKE USAGE ON SEQUENCES FROM atman_eval_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA eval
    REVOKE EXECUTE ON FUNCTIONS FROM atman_eval_writer;
ALTER DEFAULT PRIVILEGES IN SCHEMA eval
    REVOKE EXECUTE ON FUNCTIONS FROM atman_eval_reader;
"""


_DROP_SCHEMA_SQL = "DROP SCHEMA IF EXISTS eval CASCADE;"


_DROP_ROLES_SQL = """
DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atman_eval_reader') THEN
        DROP ROLE atman_eval_reader;
    END IF;
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atman_eval_writer') THEN
        DROP ROLE atman_eval_writer;
    END IF;
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'atman_eval_owner') THEN
        DROP ROLE atman_eval_owner;
    END IF;
END
$$;
"""


def upgrade() -> None:
    """Create eval schema, roles, default grants, and enums.

    Order matters:
      1. Create roles (otherwise ``AUTHORIZATION atman_eval_owner`` fails).
      2. Create schema owned by ``atman_eval_owner``.
      3. Grant ``USAGE`` to writer/reader.
      4. Set default privileges so future migrations inherit grants.
      5. Create enum types in the new schema.
    """
    op.execute(_CREATE_ROLES_SQL)
    op.execute(_CREATE_SCHEMA_SQL)
    op.execute(_GRANT_USAGE_SQL)
    op.execute(_DEFAULT_PRIVILEGES_SQL)
    op.execute(_CREATE_ENUMS_SQL)


def downgrade() -> None:
    """Reverse upgrade: drop enums, revoke defaults, drop schema, drop roles."""
    op.execute(_DROP_ENUMS_SQL)
    op.execute(_REVOKE_DEFAULTS_SQL)
    op.execute(_DROP_SCHEMA_SQL)
    op.execute(_DROP_ROLES_SQL)
