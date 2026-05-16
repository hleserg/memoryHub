-- Migration 0015: move subjective tables into per-agent schemas
--
-- Moves reflections, self_applied_changes, and pending_human_review from
-- public (RLS or global) into agent_{serial_id}.* for physical isolation.
-- Backfills existing rows and repoints reflection_entities FKs locally.
--
-- Depends on: 0001 (reflection_level enum), 0010 (latest create_agent_schema),
--             0012, 0013 (public audit/inbox tables)
--
-- Usage:
--   psql -d atman -f migrations/versions/0015_move_subjective_tables.sql
--
-- Rollback: restore from backup; forward-only data migration.
--
-- Multi-agent backfill: rows in public.self_applied_changes with agent_id IS NULL
-- (narrative-only) and public.pending_human_review without context.agent_id are
-- copied only when public.agents has a single row. Verify counts before 0016 DROP.

-- Grants for atman_app on per-agent schema (tables + BIGSERIAL sequences).
CREATE OR REPLACE FUNCTION public.grant_agent_schema_app_privileges(schema_name TEXT)
RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
    EXECUTE format('GRANT USAGE ON SCHEMA %I TO atman_app', schema_name);
    EXECUTE format(
        'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA %I TO atman_app',
        schema_name
    );
    EXECUTE format(
        'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA %I TO atman_app',
        schema_name
    );
    EXECUTE format(
        'ALTER DEFAULT PRIVILEGES IN SCHEMA %I '
        'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO atman_app',
        schema_name
    );
    EXECUTE format(
        'ALTER DEFAULT PRIVILEGES IN SCHEMA %I '
        'GRANT USAGE, SELECT ON SEQUENCES TO atman_app',
        schema_name
    );
END;
$$;

-- ── Step 1: per-schema subjective tables ────────────────────────────────────

CREATE OR REPLACE FUNCTION public.extend_agent_schema_0015(schema_name TEXT)
RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
    -- reflections (subjective interpretation layer; no RLS in per-agent schema)
    EXECUTE format($sql$
        CREATE TABLE IF NOT EXISTS %I.reflections (
            id                   BIGSERIAL PRIMARY KEY,
            agent_id             UUID NOT NULL REFERENCES public.agents(id) ON DELETE CASCADE,
            level                reflection_level NOT NULL,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            session_id           UUID REFERENCES %I.sessions(id) ON DELETE SET NULL,
            period_start         TIMESTAMPTZ,
            period_end           TIMESTAMPTZ,
            content              TEXT NOT NULL,
            summary              TEXT,
            experience_refs      UUID[] NOT NULL DEFAULT '{}',
            reframing_note_ids   UUID[] NOT NULL DEFAULT '{}',
            model_provider       TEXT,
            model_name           TEXT,
            schema_version       INTEGER NOT NULL DEFAULT 1,
            metadata             JSONB NOT NULL DEFAULT '{}'
        );
        COMMENT ON TABLE %I.reflections IS
            'Per-agent reflection storage (micro/daily/deep). experience_refs holds key_moment UUIDs.';
        CREATE INDEX IF NOT EXISTS reflections_created_idx
            ON %I.reflections (created_at DESC);
        CREATE INDEX IF NOT EXISTS reflections_level_created_idx
            ON %I.reflections (level, created_at DESC);
        CREATE INDEX IF NOT EXISTS reflections_experience_refs_idx
            ON %I.reflections USING GIN (experience_refs);
        CREATE INDEX IF NOT EXISTS reflections_session_idx
            ON %I.reflections (session_id) WHERE session_id IS NOT NULL;
    $sql$,
        schema_name, schema_name,
        schema_name, schema_name, schema_name, schema_name, schema_name);

    -- self_applied_changes audit trail
    EXECUTE format($sql$
        CREATE TABLE IF NOT EXISTS %I.self_applied_changes (
            id UUID PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL,
            agent_id UUID,
            actor TEXT NOT NULL CHECK (
                actor IN (
                    'reflection_daily', 'reflection_deep', 'human_via_reflection_review'
                )
            ),
            reflection_event_id UUID NOT NULL,
            target_kind TEXT NOT NULL CHECK (
                target_kind IN (
                    'identity_core_value',
                    'identity_principle',
                    'identity_habit',
                    'identity_goal',
                    'identity_open_question',
                    'identity_self_description',
                    'narrative_core_layer',
                    'narrative_recent_layer'
                )
            ),
            target_ref TEXT NOT NULL,
            before_snapshot JSONB NOT NULL,
            after_snapshot JSONB NOT NULL,
            rationale TEXT NOT NULL,
            confidence_self_assessment TEXT NOT NULL,
            based_on_moment_ids UUID[] NOT NULL DEFAULT '{}',
            reverted_at TIMESTAMPTZ,
            reverted_reason TEXT,
            reverted_by_change_id UUID REFERENCES %I.self_applied_changes(id)
        );
        CREATE INDEX IF NOT EXISTS self_applied_changes_applied_at_idx
            ON %I.self_applied_changes (applied_at DESC);
        CREATE INDEX IF NOT EXISTS self_applied_changes_actor_idx
            ON %I.self_applied_changes (actor);
        CREATE INDEX IF NOT EXISTS self_applied_changes_target_kind_idx
            ON %I.self_applied_changes (target_kind);
        CREATE INDEX IF NOT EXISTS self_applied_changes_reflection_event_idx
            ON %I.self_applied_changes (reflection_event_id);
        CREATE INDEX IF NOT EXISTS self_applied_changes_agent_idx
            ON %I.self_applied_changes (agent_id) WHERE agent_id IS NOT NULL;
    $sql$, schema_name, schema_name, schema_name, schema_name, schema_name, schema_name, schema_name);

    -- pending human review inbox
    EXECUTE format($sql$
        CREATE TABLE IF NOT EXISTS %I.pending_human_review (
            id UUID PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL,
            created_by TEXT NOT NULL,
            reflection_event_id UUID,
            kind TEXT NOT NULL CHECK (
                kind IN (
                    'identity_change_doubt',
                    'narrative_change_doubt',
                    'high_salience_judgement'
                )
            ),
            question TEXT NOT NULL,
            context JSONB NOT NULL DEFAULT '{}'::jsonb,
            priority TEXT NOT NULL DEFAULT 'normal'
                CHECK (priority IN ('normal', 'high')),
            resolved_at TIMESTAMPTZ,
            resolution TEXT CHECK (
                resolution IS NULL OR resolution IN (
                    'accepted', 'rejected', 'modified', 'dismissed'
                )
            ),
            resolution_note TEXT,
            applied_change_id UUID REFERENCES %I.self_applied_changes(id)
        );
        CREATE INDEX IF NOT EXISTS pending_human_review_unresolved_idx
            ON %I.pending_human_review (priority, created_at)
            WHERE resolved_at IS NULL;
        CREATE INDEX IF NOT EXISTS pending_human_review_kind_idx
            ON %I.pending_human_review (kind);
        CREATE INDEX IF NOT EXISTS pending_human_review_created_by_idx
            ON %I.pending_human_review (created_by);
    $sql$, schema_name, schema_name, schema_name, schema_name, schema_name);

    PERFORM public.grant_agent_schema_app_privileges(schema_name);
END;
$$;

CREATE OR REPLACE FUNCTION public.repoint_reflection_entities_fk(schema_name TEXT)
RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
    IF to_regclass(format('%I.reflection_entities', schema_name)) IS NULL THEN
        RETURN;
    END IF;
    IF to_regclass(format('%I.reflections', schema_name)) IS NULL THEN
        RETURN;
    END IF;
    EXECUTE format(
        'ALTER TABLE %I.reflection_entities DROP CONSTRAINT IF EXISTS reflection_entities_reflection_id_fkey',
        schema_name
    );
    EXECUTE format($sql$
        ALTER TABLE %I.reflection_entities
            ADD CONSTRAINT reflection_entities_reflection_id_fkey
            FOREIGN KEY (reflection_id)
            REFERENCES %I.reflections(id)
            ON DELETE CASCADE
    $sql$, schema_name, schema_name);
END;
$$;

-- ── Step 2: backfill one agent schema from public tables ─────────────────────

CREATE OR REPLACE FUNCTION public.migrate_subjective_data_to_agent(
    p_serial_id INT,
    p_agent_uuid UUID
)
RETURNS VOID LANGUAGE plpgsql AS $$
DECLARE
    schema_name TEXT := 'agent_' || p_serial_id;
BEGIN
    PERFORM public.extend_agent_schema_0015(schema_name);

    IF to_regclass('public.reflections') IS NOT NULL THEN
        CREATE TEMP TABLE IF NOT EXISTS _reflection_id_map (
            old_id BIGINT PRIMARY KEY,
            new_id BIGINT NOT NULL
        ) ON COMMIT DROP;
        TRUNCATE _reflection_id_map;

        EXECUTE format($sql$
        WITH ordered AS (
            SELECT *
            FROM public.reflections
            WHERE agent_id = %L::uuid
            ORDER BY id
        ),
        ins AS (
            INSERT INTO %I.reflections (
                agent_id, level, created_at, session_id, period_start, period_end,
                content, summary, experience_refs, reframing_note_ids,
                model_provider, model_name, schema_version, metadata
            )
            SELECT
                agent_id, level, created_at, session_id, period_start, period_end,
                content, summary, experience_refs, reframing_note_ids,
                model_provider, model_name, schema_version, metadata
            FROM ordered
            RETURNING id
        )
        INSERT INTO _reflection_id_map (old_id, new_id)
        SELECT o.id, n.id
        FROM (
            SELECT id, row_number() OVER (ORDER BY id) AS rn
            FROM public.reflections
            WHERE agent_id = %L::uuid
        ) o
        JOIN (
            SELECT id, row_number() OVER (ORDER BY id) AS rn
            FROM ins
        ) n ON o.rn = n.rn
        $sql$, p_agent_uuid, schema_name, p_agent_uuid);

        IF to_regclass(format('%I.reflection_entities', schema_name)) IS NOT NULL THEN
            EXECUTE format(
                'ALTER TABLE %I.reflection_entities DROP CONSTRAINT IF EXISTS reflection_entities_reflection_id_fkey',
                schema_name
            );
            EXECUTE format($sql$
                UPDATE %I.reflection_entities re
                SET reflection_id = m.new_id
                FROM _reflection_id_map m
                WHERE re.reflection_id = m.old_id
            $sql$, schema_name);
            PERFORM public.repoint_reflection_entities_fk(schema_name);
        END IF;
    END IF;

    IF to_regclass('public.self_applied_changes') IS NOT NULL THEN
        EXECUTE format($sql$
            INSERT INTO %I.self_applied_changes (
                id, applied_at, agent_id, actor, reflection_event_id, target_kind,
                target_ref, before_snapshot, after_snapshot, rationale,
                confidence_self_assessment, based_on_moment_ids,
                reverted_at, reverted_reason, reverted_by_change_id
            )
            SELECT
                id, applied_at, agent_id, actor, reflection_event_id, target_kind,
                target_ref, before_snapshot, after_snapshot, rationale,
                confidence_self_assessment, based_on_moment_ids,
                reverted_at, reverted_reason, reverted_by_change_id
            FROM public.self_applied_changes s
            WHERE s.agent_id = %L::uuid
               OR (
                   s.agent_id IS NULL
                   AND (SELECT COUNT(*) = 1 FROM public.agents)
               )
            ON CONFLICT (id) DO NOTHING
        $sql$, schema_name, p_agent_uuid);
    END IF;

    IF to_regclass('public.pending_human_review') IS NOT NULL THEN
        EXECUTE format($sql$
            INSERT INTO %I.pending_human_review (
                id, created_at, created_by, reflection_event_id, kind, question,
                context, priority, resolved_at, resolution, resolution_note,
                applied_change_id
            )
            SELECT
                id, created_at, created_by, reflection_event_id, kind, question,
                context, priority, resolved_at, resolution, resolution_note,
                applied_change_id
            FROM public.pending_human_review p
            WHERE p.context->>'agent_id' = %L
               OR (
                   p.context->>'agent_id' IS NULL
                   AND (SELECT COUNT(*) = 1 FROM public.agents)
               )
            ON CONFLICT (id) DO NOTHING
        $sql$, schema_name, p_agent_uuid::text);
    END IF;
END;
$$;

-- ── Step 3: redefine create_agent_schema (includes 0015 subjective tables) ───

-- ── Step 2: redefine create_agent_schema (0006 + 0007 + 0008 + 0009 + 0010) ──

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
            id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            session_id                 UUID NOT NULL CONSTRAINT key_moments_session_fk REFERENCES %I.sessions(id) ON DELETE RESTRICT,
            agent_id                   UUID NOT NULL REFERENCES public.agents(id) ON DELETE CASCADE,
            what_happened              TEXT NOT NULL,
            emotional_valence          FLOAT NOT NULL CHECK (emotional_valence BETWEEN -1 AND 1),
            emotional_intensity        FLOAT NOT NULL CHECK (emotional_intensity BETWEEN 0 AND 1),
            depth                      TEXT NOT NULL CHECK (depth IN ('surface','meaningful','profound')),
            why_it_matters             TEXT,
            values_touched             TEXT[] NOT NULL DEFAULT '{}',
            principles_confirmed       TEXT[] NOT NULL DEFAULT '{}',
            principles_questioned      TEXT[] NOT NULL DEFAULT '{}',
            what_changed               TEXT,
            recorded_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            embedding                  halfvec(1024),
            salience                   REAL NOT NULL DEFAULT 1.0 CHECK (salience BETWEEN 0.0 AND 1.0),
            salience_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_accessed_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            access_count               INT NOT NULL DEFAULT 0 CHECK (access_count >= 0),
            incomplete_coloring        BOOLEAN NOT NULL DEFAULT FALSE,
            recorded_by                TEXT NOT NULL DEFAULT 'session_manager',
            identity_snapshot_id       UUID,
            importance                 REAL NOT NULL DEFAULT 0.5 CHECK (importance BETWEEN 0.0 AND 1.0),
            context_halo               JSONB,
            fact_refs                  UUID[] NOT NULL DEFAULT '{}',
            structured_markers         JSONB,
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
        -- Immutability: block UPDATE only; DELETE allowed (session/agent CASCADE cleanup).
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

    -- validation findings + divergence events (migration 0010)
    PERFORM public.extend_agent_schema_0010(schema_name);

    -- subjective tables (migration 0015)
    PERFORM public.extend_agent_schema_0015(schema_name);
    PERFORM public.repoint_reflection_entities_fk(schema_name);

  -- Grants (tables + sequences for BIGSERIAL reflections.id)
    PERFORM public.grant_agent_schema_app_privileges(schema_name);
END;
$$;


-- ── Step 4: backfill existing agents from public subjective tables ───────────

DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT serial_id, id AS agent_uuid
        FROM public.agents
        ORDER BY serial_id
    LOOP
        PERFORM public.migrate_subjective_data_to_agent(r.serial_id, r.agent_uuid);
    END LOOP;
END;
$$;
