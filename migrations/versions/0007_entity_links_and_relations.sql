-- Migration 0007: entity link tables and entity_relations in per-agent schemas
--
-- Adds four tables to every agent_N schema:
--   fact_entities         — links public.facts rows to entities observed in them
--   key_moment_entities   — links key_moments to entities with emotional context
--   entity_relations      — directed typed relations between two entities
--   reflection_entities   — links public.reflections rows to entities
--
-- Depends on: migration 0006 (entities table must exist in each agent schema)
--
-- Notes:
--   - fact_entities.fact_id references public.facts(id) (cross-schema FK is fine
--     because public.facts is stable and in the same database).
--   - key_moment_entities.key_moment_id has NO FK intentionally: key_moments
--     will be restructured in migration 0008.
--   - reflection_entities.reflection_id references public.reflections(id).
--   - entity_id FKs inside the per-agent schema use format() with %I so the
--     reference resolves to the correct schema at runtime.
--
-- Usage:
--   psql -d atman -f migrations/versions/0007_entity_links_and_relations.sql
--
-- Rollback (per agent schema):
--   DROP TABLE IF EXISTS agent_N.reflection_entities CASCADE;
--   DROP TABLE IF EXISTS agent_N.entity_relations CASCADE;
--   DROP TABLE IF EXISTS agent_N.key_moment_entities CASCADE;
--   DROP TABLE IF EXISTS agent_N.fact_entities CASCADE;

-- ── Step 1: helper that adds only the 0007 tables to one schema ───────────────

CREATE OR REPLACE FUNCTION public.extend_agent_schema_0007(schema_name TEXT)
RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
    -- fact_entities
    -- fact_id references public.facts (cross-schema FK, safe because public.facts
    -- is a stable shared table).
    -- entity_id references the per-agent entities table via format.
    EXECUTE format($sql$
        CREATE TABLE IF NOT EXISTS %I.fact_entities (
            fact_id    UUID NOT NULL REFERENCES public.facts(id) ON DELETE CASCADE,
            entity_id  UUID NOT NULL REFERENCES %I.entities(id) ON DELETE RESTRICT,
            agent_id   UUID NOT NULL,
            role       TEXT NOT NULL
                           CHECK (role IN ('subject','object','context','mentioned')),
            confidence REAL NOT NULL DEFAULT 1.0
                           CHECK (confidence BETWEEN 0 AND 1),
            PRIMARY KEY (fact_id, entity_id, role)
        );
        CREATE INDEX IF NOT EXISTS fact_entities_entity_agent_idx
            ON %I.fact_entities (entity_id, agent_id);
    $sql$, schema_name, schema_name, schema_name);

    -- key_moment_entities
    -- key_moment_id has no FK by design (key_moments restructured in 0008).
    -- entity_id references the per-agent entities table via format.
    EXECUTE format($sql$
        CREATE TABLE IF NOT EXISTS %I.key_moment_entities (
            key_moment_id            UUID NOT NULL,
            entity_id                UUID NOT NULL REFERENCES %I.entities(id) ON DELETE RESTRICT,
            agent_id                 UUID NOT NULL,
            involvement              TEXT NOT NULL
                                         CHECK (involvement IN (
                                             'primary_subject','present','mentioned','evoked'
                                         )),
            valence_toward_entity    REAL CHECK (valence_toward_entity BETWEEN -1.0 AND 1.0),
            intensity_toward_entity  REAL CHECK (intensity_toward_entity BETWEEN 0.0 AND 1.0),
            PRIMARY KEY (key_moment_id, entity_id, involvement)
        );
    $sql$, schema_name, schema_name);

    -- entity_relations
    -- Both from_entity_id and to_entity_id reference the per-agent entities table.
    EXECUTE format($sql$
        CREATE TABLE IF NOT EXISTS %I.entity_relations (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            agent_id             UUID NOT NULL,
            from_entity_id       UUID NOT NULL REFERENCES %I.entities(id) ON DELETE RESTRICT,
            to_entity_id         UUID NOT NULL REFERENCES %I.entities(id) ON DELETE RESTRICT,
            relation_type        TEXT NOT NULL,
            since                DATE,
            until                DATE,
            confidence           REAL NOT NULL DEFAULT 1.0
                                     CHECK (confidence BETWEEN 0 AND 1),
            learned_from_fact_id UUID,
            learned_by           TEXT NOT NULL
                                     CHECK (learned_by IN ('mrebel','rules','reflection','manual')),
            created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CHECK (from_entity_id != to_entity_id),
            UNIQUE (from_entity_id, to_entity_id, relation_type)
        );
        CREATE INDEX IF NOT EXISTS entity_relations_from_active_idx
            ON %I.entity_relations (agent_id, from_entity_id)
            WHERE until IS NULL;
        CREATE INDEX IF NOT EXISTS entity_relations_to_active_idx
            ON %I.entity_relations (agent_id, to_entity_id)
            WHERE until IS NULL;
    $sql$, schema_name, schema_name, schema_name, schema_name, schema_name);

    -- reflection_entities
    -- reflection_id references public.reflections(id) (cross-schema FK, safe).
    -- entity_id references the per-agent entities table via format.
    EXECUTE format($sql$
        CREATE TABLE IF NOT EXISTS %I.reflection_entities (
            reflection_id  BIGINT NOT NULL REFERENCES public.reflections(id) ON DELETE CASCADE,
            entity_id      UUID NOT NULL REFERENCES %I.entities(id) ON DELETE RESTRICT,
            agent_id       UUID NOT NULL,
            role           TEXT,
            PRIMARY KEY (reflection_id, entity_id)
        );
    $sql$, schema_name, schema_name);
END;
$$;

-- ── Step 2: redefine create_agent_schema to include both 0006 and 0007 calls ──

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

    -- key_moments
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
            embedding             halfvec(1024)
        );
        CREATE INDEX IF NOT EXISTS km_agent_idx ON %I.key_moments (agent_id);
        CREATE INDEX IF NOT EXISTS km_experience_idx ON %I.key_moments (experience_id);
        CREATE INDEX IF NOT EXISTS km_depth_idx ON %I.key_moments (agent_id, depth);
        CREATE INDEX IF NOT EXISTS km_values_idx ON %I.key_moments USING GIN (values_touched);
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

    -- reframing_notes
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
        CREATE INDEX IF NOT EXISTS reframing_experience_idx ON %I.reframing_notes (experience_id);
        DROP TRIGGER IF EXISTS reframing_notes_append_only ON %I.reframing_notes;
        CREATE TRIGGER reframing_notes_append_only
            BEFORE UPDATE ON %I.reframing_notes
            FOR EACH ROW EXECUTE FUNCTION public.prevent_reframing_modification();
    $sql$, schema_name, schema_name, schema_name, schema_name, schema_name);

    -- entity registry tables (migration 0006)
    PERFORM public.extend_agent_schema_0006(schema_name);

    -- entity link and relation tables (migration 0007)
    PERFORM public.extend_agent_schema_0007(schema_name);

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
        PERFORM public.extend_agent_schema_0007('agent_' || r.serial_id);
    END LOOP;
END;
$$;
