-- Migration 0014: reframing_notes — drop legacy experience_id, require session_id
--
-- After memory architecture v3, ``experiences`` no longer exists as a separate
-- table — reflection operates on sessions + key_moments directly. The
-- ``reframing_notes`` table kept ``experience_id`` as a soft reference for
-- backwards compatibility while a parallel ``session_id`` was populated; this
-- migration drops the legacy column and promotes ``session_id`` to a
-- not-null FK back into the per-agent ``sessions`` table.
--
-- Depends on: migration 0010 (latest layout for per-agent ``reframing_notes``)
--             and 0008 (per-agent ``sessions`` table populated by SessionManager).
--
-- Backfill rule (from REFLECTION_FUTURE.md §3.4): legacy rows had
-- ``experience_id`` equal to the producing session id (one experience per
-- session, see ``ExperienceViewRepository``), so ``session_id`` is set from
-- ``experience_id`` when ``session_id`` is NULL.
--
-- Usage:
--   psql -d atman -f migrations/versions/0014_reframing_notes_session_id.sql
--
-- Rollback (per agent schema): not provided; the dropped ``experience_id``
-- cannot be reconstructed losslessly. If you need to revert, restore from
-- backup before running this migration.

-- ── Step 1: helper that performs the column swap for one schema ──────────────

CREATE OR REPLACE FUNCTION public.extend_agent_schema_0014(schema_name TEXT)
RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
    -- Backfill session_id from experience_id for legacy rows (one experience
    -- per session, so the two ids match by construction).
    EXECUTE format($sql$
        UPDATE %I.reframing_notes
        SET    session_id = experience_id
        WHERE  session_id IS NULL
          AND  experience_id IS NOT NULL;
    $sql$, schema_name);

    -- Refuse to proceed if any row still has a NULL session_id — surfacing
    -- the data problem rather than masking it under a hard constraint.
    DECLARE
        null_rows BIGINT;
    BEGIN
        EXECUTE format('SELECT COUNT(*) FROM %I.reframing_notes WHERE session_id IS NULL', schema_name)
            INTO null_rows;
        IF null_rows > 0 THEN
            RAISE EXCEPTION
                'reframing_notes in schema % still has % row(s) with NULL session_id after backfill; investigate before re-running',
                schema_name, null_rows;
        END IF;
    END;

    -- Make session_id NOT NULL.
    EXECUTE format(
        'ALTER TABLE %I.reframing_notes ALTER COLUMN session_id SET NOT NULL',
        schema_name
    );

    -- Add FK to sessions(id), one-way cascade on session deletion to keep
    -- audit-trail invariants from migration 0008 intact.
    EXECUTE format($sql$
        ALTER TABLE %I.reframing_notes
            DROP CONSTRAINT IF EXISTS reframing_notes_session_fk;
        ALTER TABLE %I.reframing_notes
            ADD CONSTRAINT reframing_notes_session_fk
                FOREIGN KEY (session_id)
                REFERENCES %I.sessions (id)
                ON DELETE CASCADE;
    $sql$, schema_name, schema_name, schema_name);

    -- Drop the legacy experience_id column (and its index, if any). The
    -- experience_id_idx is best-effort: we name the migration 0007 index
    -- explicitly but tolerate either present or absent.
    EXECUTE format(
        'DROP INDEX IF EXISTS %I.reframing_experience_idx',
        schema_name
    );
    EXECUTE format(
        'ALTER TABLE %I.reframing_notes DROP COLUMN IF EXISTS experience_id',
        schema_name
    );
END;
$$;

-- ── Step 2: backfill existing agents ─────────────────────────────────────────

DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT serial_id
        FROM public.agents
        ORDER BY serial_id
    LOOP
        PERFORM public.extend_agent_schema_0014('agent_' || r.serial_id);
    END LOOP;
END;
$$;

-- ── Step 3: drop the helper to keep the public schema tidy ───────────────────
-- The function is one-shot; future agents will be created via
-- public.create_agent_schema, which already provisions the post-0014 layout
-- once a follow-up migration updates its body. Until then, freshly created
-- agents must run public.extend_agent_schema_0014 explicitly.

-- Intentionally NOT dropping the helper here so callers running migrations
-- out of order can still re-apply the swap. It will be removed when the
-- next migration that touches reframing_notes inlines the layout.
