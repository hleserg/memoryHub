-- Migration 0004: per-agent private schemas
--
-- Architecture:
--   public.facts / public.fact_relations  — shared, RLS by agent_id (stays)
--   public.agents                          — registry (stays)
--   agent_{N}.*                            — private per-agent schema (new)
--
-- Tables moving out of public: experiences, sessions, identity, identity_snapshots,
-- narrative, key_moments, reframing_notes, agent_snapshots, memory_access_log, quality_alerts

-- ── Reusable trigger functions (live in public, called from any schema) ──────

CREATE OR REPLACE FUNCTION public.prevent_key_moment_modification()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'key_moments are immutable (UPDATE not allowed)';
END;
$$;

CREATE OR REPLACE FUNCTION public.prevent_snapshot_modification()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'identity_snapshots are immutable (UPDATE not allowed)';
END;
$$;

CREATE OR REPLACE FUNCTION public.prevent_reframing_modification()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'reframing_notes are append-only (UPDATE not allowed)';
END;
$$;

-- ── Function: create private schema for one agent ────────────────────────────

CREATE OR REPLACE FUNCTION public.create_agent_schema(
    p_agent_uuid UUID,
    p_serial_id  INT
)
RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE
    schema_name TEXT := 'agent_' || p_serial_id;
BEGIN
    EXECUTE format('CREATE SCHEMA IF NOT EXISTS %I', schema_name);

    -- sessions
    EXECUTE format($sql$
        CREATE TABLE IF NOT EXISTS %I.sessions (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_id             UUID NOT NULL REFERENCES public.agents(id) ON DELETE CASCADE,
            started_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            ended_at             TIMESTAMPTZ,
            status               TEXT NOT NULL DEFAULT 'active'
                                     CHECK (status IN ('active','completed','interrupted')),
            identity_snapshot_id UUID
        );
        CREATE INDEX IF NOT EXISTS sessions_agent_started_idx
            ON %I.sessions (agent_id, started_at DESC);
    $sql$, schema_name, schema_name);

    -- identity  (one row per agent)
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

    -- identity_snapshots  (immutable)
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

    -- narrative  (one row per agent)
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

    -- experiences
    EXECUTE format($sql$
        CREATE TABLE IF NOT EXISTS %I.experiences (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_id            UUID NOT NULL REFERENCES public.agents(id) ON DELETE CASCADE,
            session_id          UUID NOT NULL REFERENCES %I.sessions(id) ON DELETE CASCADE,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            importance          FLOAT NOT NULL DEFAULT 0.5 CHECK (importance BETWEEN 0 AND 1),
            salience            FLOAT NOT NULL DEFAULT 1.0 CHECK (salience BETWEEN 0 AND 1),
            last_accessed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            access_count        INT NOT NULL DEFAULT 0,
            incomplete_coloring BOOLEAN NOT NULL DEFAULT FALSE,
            overall_tone        FLOAT CHECK (overall_tone BETWEEN -1 AND 1),
            key_insight         TEXT
        );
        CREATE INDEX IF NOT EXISTS experiences_agent_idx
            ON %I.experiences (agent_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS experiences_session_idx
            ON %I.experiences (session_id);
    $sql$, schema_name, schema_name, schema_name, schema_name);

    -- key_moments  (immutable, with embedding)
    EXECUTE format($sql$
        CREATE TABLE IF NOT EXISTS %I.key_moments (
            id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            experience_id         UUID NOT NULL REFERENCES %I.experiences(id) ON DELETE CASCADE,
            agent_id              UUID NOT NULL REFERENCES public.agents(id) ON DELETE CASCADE,
            what_happened         TEXT NOT NULL,
            emotional_valence     FLOAT NOT NULL CHECK (emotional_valence BETWEEN -1 AND 1),
            emotional_intensity   FLOAT NOT NULL CHECK (emotional_intensity BETWEEN 0 AND 1),
            depth                 TEXT NOT NULL CHECK (depth IN ('surface','meaningful','profound')),
            why_it_matters        TEXT,
            values_touched        TEXT[] NOT NULL DEFAULT '{}',
            principles_confirmed  TEXT[] NOT NULL DEFAULT '{}',
            principles_questioned TEXT[] NOT NULL DEFAULT '{}',
            what_changed          TEXT,
            recorded_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            embedding             halfvec(2560)
        );
        CREATE INDEX IF NOT EXISTS km_agent_idx
            ON %I.key_moments (agent_id);
        CREATE INDEX IF NOT EXISTS km_experience_idx
            ON %I.key_moments (experience_id);
        CREATE INDEX IF NOT EXISTS km_depth_idx
            ON %I.key_moments (agent_id, depth);
        CREATE INDEX IF NOT EXISTS km_values_idx
            ON %I.key_moments USING GIN (values_touched);
        CREATE INDEX IF NOT EXISTS km_embedding_idx
            ON %I.key_moments USING hnsw (embedding halfvec_cosine_ops)
            WHERE embedding IS NOT NULL;
        DROP TRIGGER IF EXISTS key_moments_immutable ON %I.key_moments;
        CREATE TRIGGER key_moments_immutable
            BEFORE UPDATE ON %I.key_moments
            FOR EACH ROW EXECUTE FUNCTION public.prevent_key_moment_modification();
    $sql$,
    schema_name, schema_name,
    schema_name, schema_name, schema_name, schema_name, schema_name, schema_name, schema_name);

    -- reframing_notes  (append-only)
    EXECUTE format($sql$
        CREATE TABLE IF NOT EXISTS %I.reframing_notes (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            experience_id   UUID NOT NULL REFERENCES %I.experiences(id) ON DELETE CASCADE,
            agent_id        UUID NOT NULL REFERENCES public.agents(id) ON DELETE CASCADE,
            reflection      TEXT NOT NULL,
            reflection_type TEXT NOT NULL
                                CHECK (reflection_type IN ('growth','reinterpretation','closure','insight')),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        CREATE INDEX IF NOT EXISTS reframing_experience_idx
            ON %I.reframing_notes (experience_id);
        DROP TRIGGER IF EXISTS reframing_notes_append_only ON %I.reframing_notes;
        CREATE TRIGGER reframing_notes_append_only
            BEFORE UPDATE ON %I.reframing_notes
            FOR EACH ROW EXECUTE FUNCTION public.prevent_reframing_modification();
    $sql$, schema_name, schema_name, schema_name, schema_name, schema_name);

    -- Grants: atman_app gets full DML on all tables in this schema
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO atman_app', schema_name);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA %I TO atman_app', schema_name);
    EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO atman_app', schema_name);
END;
$$;

-- ── Drop old shared tables (no data, moving to agent schemas) ────────────────
-- Order matters: children first

DROP TABLE IF EXISTS public.quality_alerts    CASCADE;
DROP TABLE IF EXISTS public.memory_access_log CASCADE;
DROP TABLE IF EXISTS public.agent_snapshots   CASCADE;
DROP TABLE IF EXISTS public.reframing_notes   CASCADE;
DROP TABLE IF EXISTS public.key_moments       CASCADE;
DROP TABLE IF EXISTS public.experiences       CASCADE;
DROP TABLE IF EXISTS public.sessions          CASCADE;
DROP TABLE IF EXISTS public.identity_snapshots CASCADE;
DROP TABLE IF EXISTS public.narrative         CASCADE;
DROP TABLE IF EXISTS public.identity          CASCADE;
