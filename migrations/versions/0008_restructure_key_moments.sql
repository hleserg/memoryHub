-- Migration 0008: restructure key_moments — promote to standalone, drop experiences
--
-- Key changes per agent_N schema:
--   sessions        — extended with close_reason, agent_recap, restart_reason,
--                     user_language, overall_tone, key_insight, unexamined_fact_refs
--   key_moments     — extended with session_id (replaces experience_id),
--                     salience, importance, access_count, fact_refs, etc.
--   reframing_notes — session_id backfilled from experiences.session_id
--   experiences     — FK removed, table dropped
--   key_moment_entities — FK to key_moments now added (was deferred in 0007)
--
-- Also:
--   public.prevent_key_moment_modification() — replaced with field-level guard
--   public.key_moments (0005)                — dropped (superseded by per-agent tables)
--
-- Depends on: migrations 0006, 0007
--
-- Usage:
--   psql -d atman -f migrations/versions/0008_restructure_key_moments.sql
--
-- Rollback sketch (per agent schema):
--   ALTER TABLE agent_N.key_moments DROP COLUMN IF EXISTS session_id;
--   (experiences table is gone — rollback requires restore from backup)

-- ── Step 1: replace blanket key_moments immutability trigger with field-level guard ──

CREATE OR REPLACE FUNCTION public.prevent_key_moment_modification()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF (OLD.what_happened IS DISTINCT FROM NEW.what_happened
        OR OLD.emotional_valence IS DISTINCT FROM NEW.emotional_valence
        OR OLD.emotional_intensity IS DISTINCT FROM NEW.emotional_intensity
        OR OLD.depth IS DISTINCT FROM NEW.depth
        OR OLD.why_it_matters IS DISTINCT FROM NEW.why_it_matters
        OR OLD.what_changed IS DISTINCT FROM NEW.what_changed
        OR OLD.values_touched IS DISTINCT FROM NEW.values_touched
        OR OLD.principles_confirmed IS DISTINCT FROM NEW.principles_confirmed
        OR OLD.principles_questioned IS DISTINCT FROM NEW.principles_questioned
        OR OLD.session_id IS DISTINCT FROM NEW.session_id
        OR OLD.recorded_at IS DISTINCT FROM NEW.recorded_at) THEN
        RAISE EXCEPTION 'KeyMoment semantic fields are immutable';
    END IF;
    RETURN NEW;
END;
$$;

-- ── Step 2: per-agent extension helper ───────────────────────────────────────

CREATE OR REPLACE FUNCTION public.extend_agent_schema_0008(schema_name TEXT)
RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN

    -- ── A: extend sessions ────────────────────────────────────────────────────
    EXECUTE format('ALTER TABLE %I.sessions ADD COLUMN IF NOT EXISTS close_reason TEXT CHECK (close_reason IN (''timeout_sleep'',''menu_timeout'',''restart'',''forced'',''interrupted''))', schema_name);
    EXECUTE format('ALTER TABLE %I.sessions ADD COLUMN IF NOT EXISTS agent_recap TEXT', schema_name);
    EXECUTE format('ALTER TABLE %I.sessions ADD COLUMN IF NOT EXISTS restart_reason TEXT NOT NULL DEFAULT ''''', schema_name);
    EXECUTE format('ALTER TABLE %I.sessions ADD COLUMN IF NOT EXISTS user_language TEXT NOT NULL DEFAULT ''ru''', schema_name);
    EXECUTE format('ALTER TABLE %I.sessions ADD COLUMN IF NOT EXISTS overall_tone FLOAT CHECK (overall_tone BETWEEN -1 AND 1)', schema_name);
    EXECUTE format('ALTER TABLE %I.sessions ADD COLUMN IF NOT EXISTS key_insight TEXT', schema_name);
    EXECUTE format('ALTER TABLE %I.sessions ADD COLUMN IF NOT EXISTS unexamined_fact_refs UUID[] NOT NULL DEFAULT ''{}''', schema_name);

    -- ── B: extend key_moments ─────────────────────────────────────────────────
    EXECUTE format('ALTER TABLE %I.key_moments ADD COLUMN IF NOT EXISTS session_id UUID', schema_name);
    EXECUTE format('ALTER TABLE %I.key_moments ADD COLUMN IF NOT EXISTS salience REAL NOT NULL DEFAULT 1.0 CHECK (salience BETWEEN 0.0 AND 1.0)', schema_name);
    EXECUTE format('ALTER TABLE %I.key_moments ADD COLUMN IF NOT EXISTS salience_at TIMESTAMPTZ NOT NULL DEFAULT NOW()', schema_name);
    EXECUTE format('ALTER TABLE %I.key_moments ADD COLUMN IF NOT EXISTS last_accessed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()', schema_name);
    EXECUTE format('ALTER TABLE %I.key_moments ADD COLUMN IF NOT EXISTS access_count INT NOT NULL DEFAULT 0 CHECK (access_count >= 0)', schema_name);
    EXECUTE format('ALTER TABLE %I.key_moments ADD COLUMN IF NOT EXISTS incomplete_coloring BOOLEAN NOT NULL DEFAULT FALSE', schema_name);
    EXECUTE format('ALTER TABLE %I.key_moments ADD COLUMN IF NOT EXISTS recorded_by TEXT NOT NULL DEFAULT ''session_manager''', schema_name);
    EXECUTE format('ALTER TABLE %I.key_moments ADD COLUMN IF NOT EXISTS identity_snapshot_id UUID', schema_name);
    EXECUTE format('ALTER TABLE %I.key_moments ADD COLUMN IF NOT EXISTS importance REAL NOT NULL DEFAULT 0.5 CHECK (importance BETWEEN 0.0 AND 1.0)', schema_name);
    EXECUTE format('ALTER TABLE %I.key_moments ADD COLUMN IF NOT EXISTS context_halo JSONB', schema_name);
    EXECUTE format('ALTER TABLE %I.key_moments ADD COLUMN IF NOT EXISTS fact_refs UUID[] NOT NULL DEFAULT ''{}''', schema_name);
    EXECUTE format('ALTER TABLE %I.key_moments ADD COLUMN IF NOT EXISTS structured_markers JSONB', schema_name);
    EXECUTE format('ALTER TABLE %I.key_moments ADD COLUMN IF NOT EXISTS structured_markers_version TEXT', schema_name);

    -- ── C: backfill key_moments from experiences and sessions from experiences ─
    EXECUTE format($sql$
        UPDATE %I.key_moments km
        SET session_id           = e.session_id,
            incomplete_coloring  = e.incomplete_coloring,
            importance           = e.importance,
            salience             = e.salience,
            last_accessed_at     = e.last_accessed_at,
            access_count         = e.access_count,
            identity_snapshot_id = s.identity_snapshot_id
        FROM %I.experiences e
        JOIN %I.sessions s ON s.id = e.session_id
        WHERE km.experience_id = e.id
          AND km.session_id IS NULL;
    $sql$, schema_name, schema_name, schema_name);

    -- Backfill session metadata from experiences. Note: pre-0008 experiences
    -- did NOT have `close_reason` or `unexamined_fact_refs` (see migration 0004,
    -- agent_N.experiences columns), so these are intentionally initialised to
    -- NULL / '{}' — there is no prior value to preserve. Only `overall_tone`
    -- and `key_insight` are copied from the soon-to-be-dropped experiences row.
    EXECUTE format($sql$
        UPDATE %I.sessions s
        SET overall_tone         = e.overall_tone,
            key_insight          = e.key_insight,
            unexamined_fact_refs = '{}',
            close_reason         = NULL
        FROM %I.experiences e
        WHERE e.session_id = s.id
          AND s.overall_tone IS NULL;
    $sql$, schema_name, schema_name);

    -- ── D: make session_id NOT NULL, add FK, add new indexes ─────────────────
    -- First delete any orphan key_moments whose session_id is still NULL
    -- after backfill (e.g. their experience was already deleted, or the
    -- experience_id pointed to a missing row). Without this cleanup, the
    -- ALTER ... SET NOT NULL below would fail with a constraint violation
    -- and abort the migration mid-way through the agent's schema.
    EXECUTE format($sql$
        DELETE FROM %I.key_moments WHERE session_id IS NULL;
    $sql$, schema_name);

    EXECUTE format($sql$
        ALTER TABLE %I.key_moments
            ALTER COLUMN session_id SET NOT NULL;
        DO $inner$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE constraint_name = 'key_moments_session_fk'
                  AND table_schema = %L
            ) THEN
                ALTER TABLE %I.key_moments
                    ADD CONSTRAINT key_moments_session_fk
                    FOREIGN KEY (session_id) REFERENCES %I.sessions(id) ON DELETE RESTRICT;
            END IF;
        END $inner$;
    $sql$, schema_name, schema_name, schema_name, schema_name);

    EXECUTE format($sql$
        CREATE INDEX IF NOT EXISTS km_agent_session_idx
            ON %I.key_moments (agent_id, session_id);
        CREATE INDEX IF NOT EXISTS km_agent_salience_idx
            ON %I.key_moments (agent_id, salience DESC);
        CREATE INDEX IF NOT EXISTS km_fact_refs_gin_idx
            ON %I.key_moments USING GIN (fact_refs)
            WHERE cardinality(fact_refs) > 0;
    $sql$, schema_name, schema_name, schema_name);

    -- ── E: add session_id to reframing_notes, backfill from experiences ───────
    EXECUTE format('ALTER TABLE %I.reframing_notes ADD COLUMN IF NOT EXISTS session_id UUID', schema_name);

    EXECUTE format($sql$
        UPDATE %I.reframing_notes rn
        SET session_id = e.session_id
        FROM %I.experiences e
        WHERE rn.experience_id = e.id
          AND rn.session_id IS NULL;
    $sql$, schema_name, schema_name);

    -- ── F: drop experience_id FK from key_moments, then drop experiences ──────
    EXECUTE format('ALTER TABLE %I.key_moments DROP CONSTRAINT IF EXISTS key_moments_experience_id_fkey', schema_name);
    EXECUTE format('ALTER TABLE %I.key_moments DROP COLUMN IF EXISTS experience_id', schema_name);
    EXECUTE format('ALTER TABLE %I.reframing_notes DROP CONSTRAINT IF EXISTS reframing_notes_experience_id_fkey', schema_name);
    EXECUTE format('DROP TABLE IF EXISTS %I.experiences CASCADE', schema_name);

    -- ── G: re-attach field-level trigger on key_moments ──────────────────────
    --   The function public.prevent_key_moment_modification() was already replaced
    --   at the top of this migration (field-level guard). The trigger name is the
    --   same so we just recreate it to pick up the new function body.
    EXECUTE format($sql$
        DROP TRIGGER IF EXISTS key_moments_immutable ON %I.key_moments;
        CREATE TRIGGER key_moments_immutable
            BEFORE UPDATE ON %I.key_moments
            FOR EACH ROW EXECUTE FUNCTION public.prevent_key_moment_modification();
    $sql$, schema_name, schema_name);

    -- ── H: add FK from key_moment_entities to key_moments (deferred from 0007) ─
    EXECUTE format($sql$
        DO $inner$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.table_constraints
                WHERE constraint_name = 'kme_key_moment_fk'
                  AND table_schema = %L
            ) THEN
                ALTER TABLE %I.key_moment_entities
                    ADD CONSTRAINT kme_key_moment_fk
                    FOREIGN KEY (key_moment_id) REFERENCES %I.key_moments(id) ON DELETE RESTRICT;
            END IF;
        END $inner$;
    $sql$, schema_name, schema_name, schema_name);

END;
$$;

-- ── Step 3: redefine create_agent_schema (0006 + 0007 + 0008, no experiences) ─

CREATE OR REPLACE FUNCTION public.create_agent_schema(
    p_agent_uuid UUID,
    p_serial_id  INT
)
RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE
    schema_name TEXT := 'agent_' || p_serial_id;
BEGIN
    EXECUTE format('CREATE SCHEMA IF NOT EXISTS %I', schema_name);

    -- sessions (includes all 0008 columns)
    EXECUTE format($sql$
        CREATE TABLE IF NOT EXISTS %I.sessions (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_id             UUID NOT NULL REFERENCES public.agents(id) ON DELETE CASCADE,
            started_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            ended_at             TIMESTAMPTZ,
            status               TEXT NOT NULL DEFAULT 'active'
                                     CHECK (status IN ('active','completed','interrupted')),
            identity_snapshot_id UUID,
            close_reason         TEXT CHECK (close_reason IN (
                                     'timeout_sleep','menu_timeout','restart','forced','interrupted'
                                 )),
            agent_recap          TEXT,
            restart_reason       TEXT NOT NULL DEFAULT '',
            user_language        TEXT NOT NULL DEFAULT 'ru',
            overall_tone         FLOAT CHECK (overall_tone BETWEEN -1 AND 1),
            key_insight          TEXT,
            unexamined_fact_refs UUID[] NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS sessions_agent_started_idx
            ON %I.sessions (agent_id, started_at DESC);
    $sql$, schema_name, schema_name);

    -- identity
    EXECUTE format($sql$
        CREATE TABLE IF NOT EXISTS %I.identity (
            id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_id           UUID NOT NULL UNIQUE REFERENCES public.agents(id) ON DELETE CASCADE,
            self_description   TEXT NOT NULL DEFAULT '',
            core_values        JSONB NOT NULL DEFAULT '[]',
            habits             JSONB NOT NULL DEFAULT '[]',
            principles         JSONB NOT NULL DEFAULT '[]',
            goals              JSONB NOT NULL DEFAULT '[]',
            open_questions     JSONB NOT NULL DEFAULT '[]',
            emotional_baseline FLOAT NOT NULL DEFAULT 0.0
                                   CHECK (emotional_baseline BETWEEN -1 AND 1),
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    $sql$, schema_name);

    -- identity_snapshots
    EXECUTE format($sql$
        CREATE TABLE IF NOT EXISTS %I.identity_snapshots (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_id    UUID NOT NULL REFERENCES public.agents(id) ON DELETE CASCADE,
            snapshot_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            description TEXT,
            state       JSONB NOT NULL
        );
        CREATE INDEX IF NOT EXISTS id_snapshots_agent_idx
            ON %I.identity_snapshots (agent_id, snapshot_at DESC);
        DROP TRIGGER IF EXISTS identity_snapshots_immutable ON %I.identity_snapshots;
        CREATE TRIGGER identity_snapshots_immutable
            BEFORE UPDATE ON %I.identity_snapshots
            FOR EACH ROW EXECUTE FUNCTION public.prevent_snapshot_modification();
    $sql$, schema_name, schema_name, schema_name, schema_name);

    -- narrative
    EXECUTE format($sql$
        CREATE TABLE IF NOT EXISTS %I.narrative (
            id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_id     UUID NOT NULL UNIQUE REFERENCES public.agents(id) ON DELETE CASCADE,
            core_layer   TEXT NOT NULL DEFAULT '',
            recent_layer TEXT NOT NULL DEFAULT '',
            threads      JSONB NOT NULL DEFAULT '[]',
            eigenstate   JSONB NOT NULL DEFAULT '{}',
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
    $sql$, schema_name);

    -- key_moments (new version: session_id FK, all 0008 fields, no experience_id)
    EXECUTE format($sql$
        CREATE TABLE IF NOT EXISTS %I.key_moments (
            id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id               UUID NOT NULL REFERENCES %I.sessions(id) ON DELETE RESTRICT,
            agent_id                 UUID NOT NULL REFERENCES public.agents(id) ON DELETE CASCADE,
            what_happened            TEXT NOT NULL,
            emotional_valence        FLOAT NOT NULL CHECK (emotional_valence BETWEEN -1 AND 1),
            emotional_intensity      FLOAT NOT NULL CHECK (emotional_intensity BETWEEN 0 AND 1),
            depth                    TEXT NOT NULL CHECK (depth IN ('surface','meaningful','profound')),
            why_it_matters           TEXT,
            values_touched           TEXT[] NOT NULL DEFAULT '{}',
            principles_confirmed     TEXT[] NOT NULL DEFAULT '{}',
            principles_questioned    TEXT[] NOT NULL DEFAULT '{}',
            what_changed             TEXT,
            recorded_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            embedding                halfvec(1024),
            salience                 REAL NOT NULL DEFAULT 1.0 CHECK (salience BETWEEN 0.0 AND 1.0),
            salience_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_accessed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            access_count             INT NOT NULL DEFAULT 0 CHECK (access_count >= 0),
            incomplete_coloring      BOOLEAN NOT NULL DEFAULT FALSE,
            recorded_by              TEXT NOT NULL DEFAULT 'session_manager',
            identity_snapshot_id     UUID,
            importance               REAL NOT NULL DEFAULT 0.5 CHECK (importance BETWEEN 0.0 AND 1.0),
            context_halo             JSONB,
            fact_refs                UUID[] NOT NULL DEFAULT '{}',
            structured_markers       JSONB,
            structured_markers_version TEXT
        );
        CREATE INDEX IF NOT EXISTS km_agent_idx
            ON %I.key_moments (agent_id);
        CREATE INDEX IF NOT EXISTS km_agent_session_idx
            ON %I.key_moments (agent_id, session_id);
        CREATE INDEX IF NOT EXISTS km_depth_idx
            ON %I.key_moments (agent_id, depth);
        CREATE INDEX IF NOT EXISTS km_agent_salience_idx
            ON %I.key_moments (agent_id, salience DESC);
        CREATE INDEX IF NOT EXISTS km_values_idx
            ON %I.key_moments USING GIN (values_touched);
        CREATE INDEX IF NOT EXISTS km_fact_refs_gin_idx
            ON %I.key_moments USING GIN (fact_refs)
            WHERE cardinality(fact_refs) > 0;
        CREATE INDEX IF NOT EXISTS km_embedding_idx
            ON %I.key_moments USING hnsw (embedding halfvec_cosine_ops)
            WHERE embedding IS NOT NULL;
        DROP TRIGGER IF EXISTS key_moments_immutable ON %I.key_moments;
        CREATE TRIGGER key_moments_immutable
            BEFORE UPDATE ON %I.key_moments
            FOR EACH ROW EXECUTE FUNCTION public.prevent_key_moment_modification();
    $sql$,
    schema_name, schema_name,
    schema_name, schema_name, schema_name, schema_name, schema_name, schema_name, schema_name, schema_name);

    -- reframing_notes (experience_id retained as soft reference — no FK — session_id added)
    EXECUTE format($sql$
        CREATE TABLE IF NOT EXISTS %I.reframing_notes (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            experience_id   UUID,
            session_id      UUID,
            agent_id        UUID NOT NULL REFERENCES public.agents(id) ON DELETE CASCADE,
            reflection      TEXT NOT NULL,
            reflection_type TEXT NOT NULL
                                CHECK (reflection_type IN ('growth','reinterpretation','closure','insight')),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS reframing_session_idx ON %I.reframing_notes (session_id);
        DROP TRIGGER IF EXISTS reframing_notes_append_only ON %I.reframing_notes;
        CREATE TRIGGER reframing_notes_append_only
            BEFORE UPDATE ON %I.reframing_notes
            FOR EACH ROW EXECUTE FUNCTION public.prevent_reframing_modification();
    $sql$, schema_name, schema_name, schema_name, schema_name);

    -- entity registry tables (migration 0006)
    PERFORM public.extend_agent_schema_0006(schema_name);

    -- entity link and relation tables (migration 0007)
    PERFORM public.extend_agent_schema_0007(schema_name);

    -- key_moments restructure + entity FK (migration 0008)
    -- Note: for new schemas extend_agent_schema_0008 is a no-op structurally
    -- (tables created above already have the new layout) but it still safely
    -- attaches the kme_key_moment_fk that extend_agent_schema_0007 left open.
    PERFORM public.extend_agent_schema_0008(schema_name);

    -- Grants
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO atman_app', schema_name);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA %I TO atman_app', schema_name);
    EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO atman_app', schema_name);
END;
$$;

-- ── Step 4: drop public.key_moments (migration 0005, now superseded) ─────────

DROP TABLE IF EXISTS public.key_moments CASCADE;

-- ── Step 5: backfill existing agents ─────────────────────────────────────────

DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT serial_id
        FROM public.agents
        ORDER BY serial_id
    LOOP
        PERFORM public.extend_agent_schema_0008('agent_' || r.serial_id);
    END LOOP;
END;
$$;
