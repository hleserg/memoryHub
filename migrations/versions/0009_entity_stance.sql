-- Migration 0009: entity_stance table in per-agent schemas
--
-- Adds one table to every agent_N schema:
--   entity_stance — agent's evaluated stance toward a known entity, versioned
--                   via superseded_at / superseded_by chain
--
-- Depends on: migrations 0006 (entities table must exist in each agent schema)
--
-- Usage:
--   psql -d atman -f migrations/versions/0009_entity_stance.sql
--
-- Rollback (per agent schema):
--   DROP TABLE IF EXISTS agent_N.entity_stance CASCADE;

-- ── Step 1: helper that adds only the 0009 table to one schema ───────────────

CREATE OR REPLACE FUNCTION public.extend_agent_schema_0009(schema_name TEXT)
RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
    -- entity_stance
    -- entity_id references the per-agent entities table via format.
    -- superseded_by is a self-referential FK within the same table.
    -- formed_in_reflection_id is a soft reference to public.reflections(id)
    -- (cross-schema FK avoided: reflections may not always exist).
    EXECUTE format($sql$
        CREATE TABLE IF NOT EXISTS %I.entity_stance (
            id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_id                 UUID NOT NULL,
            entity_id                UUID NOT NULL REFERENCES %I.entities(id) ON DELETE RESTRICT,
            stance_text              TEXT NOT NULL,
            valence                  REAL CHECK (valence BETWEEN -1.0 AND 1.0),
            intensity                REAL CHECK (intensity BETWEEN 0.0 AND 1.0),
            formed_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            formed_in_reflection_id  UUID,
            based_on_moment_ids      UUID[] NOT NULL DEFAULT '{}',
            superseded_at            TIMESTAMPTZ,
            superseded_by            UUID REFERENCES %I.entity_stance(id) ON DELETE SET NULL,
            confidence               REAL CHECK (confidence BETWEEN 0.0 AND 1.0),
            is_provisional           BOOLEAN NOT NULL DEFAULT TRUE
        );
        CREATE UNIQUE INDEX IF NOT EXISTS entity_stance_active_uidx
            ON %I.entity_stance (agent_id, entity_id)
            WHERE superseded_at IS NULL;
        CREATE INDEX IF NOT EXISTS entity_stance_entity_agent_idx
            ON %I.entity_stance (entity_id, agent_id);
        CREATE INDEX IF NOT EXISTS entity_stance_agent_formed_idx
            ON %I.entity_stance (agent_id, formed_at DESC);
    $sql$, schema_name, schema_name, schema_name, schema_name, schema_name, schema_name);
END;
$$;

-- ── Step 2: redefine create_agent_schema (0006 + 0007 + 0008 + 0009) ─────────

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
    schema_name, schema_name, schema_name, schema_name, schema_name, schema_name, schema_name, schema_name, schema_name);

    -- reframing_notes (experience_id soft reference, session_id added in 0008)
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
    PERFORM public.extend_agent_schema_0008(schema_name);

    -- entity stance (migration 0009)
    PERFORM public.extend_agent_schema_0009(schema_name);

    -- Grants
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO atman_app', schema_name);
    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA %I TO atman_app', schema_name);
    EXECUTE format('ALTER DEFAULT PRIVILEGES IN SCHEMA %I GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO atman_app', schema_name);
END;
$$;

-- ── Step 3: backfill existing agents ─────────────────────────────────────────

DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT serial_id
        FROM public.agents
        ORDER BY serial_id
    LOOP
        PERFORM public.extend_agent_schema_0009('agent_' || r.serial_id);
    END LOOP;
END;
$$;
