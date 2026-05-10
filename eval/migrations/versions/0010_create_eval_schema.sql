-- =============================================================================
-- Migration 0010: create eval schema, roles, grants, and enum types
--
-- Mirror of eval/migrations/versions/0010_create_eval_schema.py for human review.
-- The Python migration is the source of truth; this file is documentation-only.
--
-- Idempotent: safe to run multiple times.
-- =============================================================================

-- ── Roles ────────────────────────────────────────────────────────────────────
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

-- ── Schema ──────────────────────────────────────────────────────────────────
CREATE SCHEMA IF NOT EXISTS eval AUTHORIZATION atman_eval_owner;

-- ── Grants ──────────────────────────────────────────────────────────────────
GRANT USAGE ON SCHEMA eval TO atman_eval_writer, atman_eval_reader;

-- Two parallel sets of ALTER DEFAULT PRIVILEGES are issued so the default
-- grants fire regardless of which role actually creates the table:
--   1. FOR ROLE atman_eval_owner — fires when a future migration uses
--      ``SET ROLE atman_eval_owner;`` before ``CREATE TABLE eval.<...>``.
--   2. No FOR ROLE clause — applies to current_user at the time of the
--      ALTER (the migration runner, e.g. ``atman``). This is the path that
--      actually fires for tables created by subsequent eval migrations,
--      since ``eval/migrations/env.py`` connects as the application user.
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

-- ── Enum types ──────────────────────────────────────────────────────────────
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
