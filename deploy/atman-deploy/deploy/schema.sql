-- =============================================================================
-- Atman — схема PostgreSQL
-- Применяется: setup.sh → psql < schema.sql
-- Идемпотентна: безопасно запускать повторно
-- =============================================================================

-- ── Extensions ───────────────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ── Registry ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS agents (
    id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    config     JSONB NOT NULL DEFAULT '{}',
    active     BOOLEAN NOT NULL DEFAULT TRUE
);
COMMENT ON TABLE agents IS 'Реестр агентов-личностей. Общий, без RLS.';

CREATE TABLE IF NOT EXISTS agent_snapshots (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id      UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    snapshot_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    identity_hash TEXT,
    metrics       JSONB NOT NULL DEFAULT '{}'
);
COMMENT ON TABLE agent_snapshots IS 'Метрики агента во времени — для исследований.';
CREATE INDEX IF NOT EXISTS idx_agent_snapshots_agent
    ON agent_snapshots(agent_id, snapshot_at DESC);

-- ── Factual Memory ────────────────────────────────────────────────────────────

DO $$ BEGIN
    CREATE TYPE fact_status AS ENUM ('active', 'disputed', 'superseded', 'invalidated');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS public.facts (
    id                  UUID PRIMARY KEY,
    agent_id            UUID NOT NULL,
    content             TEXT NOT NULL,
    source              TEXT NOT NULL,
    tags                TEXT[] NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata            JSONB NOT NULL DEFAULT '{}',
    status              fact_status NOT NULL DEFAULT 'active',
    invalidated_at      TIMESTAMPTZ,
    invalidation_note   TEXT NOT NULL DEFAULT '',
    superseded_by       UUID REFERENCES public.facts(id),
    disputed_at         TIMESTAMPTZ,
    confirmation_count  INTEGER NOT NULL DEFAULT 0 CHECK (confirmation_count >= 0),
    last_confirmed_at   TIMESTAMPTZ,
    salience            FLOAT NOT NULL DEFAULT 0.5 CHECK (salience BETWEEN 0.0 AND 1.0),
    embedding           halfvec(1024)
);
COMMENT ON TABLE public.facts IS 'Фактическая память. Факты без интерпретаций. Изолированы по agent_id через RLS.';
COMMENT ON COLUMN public.facts.embedding IS 'halfvec(1024) — BGE-M3. NULL при недоступности модели, система деградирует на ILIKE.';

CREATE INDEX IF NOT EXISTS idx_facts_agent_status ON public.facts(agent_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_facts_tags         ON public.facts USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_facts_content_trgm ON public.facts USING GIN(content gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_facts_embedding    ON public.facts USING hnsw(embedding halfvec_cosine_ops)
    WHERE embedding IS NOT NULL;

ALTER TABLE public.facts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.facts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS facts_isolation ON public.facts;
CREATE POLICY facts_isolation ON public.facts
    USING (agent_id = NULLIF(current_setting('atman.current_agent', TRUE), '')::UUID);

CREATE TABLE IF NOT EXISTS public.fact_relations (
    source_id       UUID NOT NULL REFERENCES public.facts(id) ON DELETE CASCADE,
    target_id       UUID NOT NULL REFERENCES public.facts(id) ON DELETE CASCADE,
    relation_type   TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata        JSONB NOT NULL DEFAULT '{}',
    PRIMARY KEY (source_id, target_id, relation_type)
);
COMMENT ON TABLE public.fact_relations IS 'Граф связей между фактами. Cascade-delete при удалении факта.';

CREATE INDEX IF NOT EXISTS idx_fact_relations_source ON public.fact_relations(source_id);
CREATE INDEX IF NOT EXISTS idx_fact_relations_target ON public.fact_relations(target_id);

-- ── Sessions ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS sessions (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id             UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    started_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at             TIMESTAMPTZ,
    status               TEXT NOT NULL DEFAULT 'active'
                         CHECK (status IN ('active', 'completed', 'interrupted')),
    identity_snapshot_id UUID
);
COMMENT ON COLUMN sessions.identity_snapshot_id IS 'Кем был агент в начале сессии.';

CREATE INDEX IF NOT EXISTS idx_sessions_agent ON sessions(agent_id, started_at DESC);

ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS sessions_isolation ON sessions;
CREATE POLICY sessions_isolation ON sessions
    USING (agent_id = NULLIF(current_setting('atman.current_agent', TRUE), '')::UUID);

-- ── Experience Store ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS experiences (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id            UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    session_id          UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    importance          FLOAT NOT NULL DEFAULT 0.5 CHECK (importance BETWEEN 0 AND 1),
    salience            FLOAT NOT NULL DEFAULT 1.0 CHECK (salience BETWEEN 0 AND 1),
    last_accessed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    access_count        INT NOT NULL DEFAULT 0,
    incomplete_coloring BOOLEAN NOT NULL DEFAULT FALSE,
    overall_tone        FLOAT CHECK (overall_tone BETWEEN -1 AND 1),
    key_insight         TEXT
);
COMMENT ON COLUMN experiences.salience IS 'Текущая яркость. Угасает без обращений.';
COMMENT ON COLUMN experiences.incomplete_coloring IS 'Эмоц. окраска не была зафиксирована в момент.';

CREATE INDEX IF NOT EXISTS idx_exp_agent   ON experiences(agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_exp_session ON experiences(session_id);

ALTER TABLE experiences ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS experiences_isolation ON experiences;
CREATE POLICY experiences_isolation ON experiences
    USING (agent_id = NULLIF(current_setting('atman.current_agent', TRUE), '')::UUID);

CREATE TABLE IF NOT EXISTS key_moments (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    experience_id         UUID NOT NULL REFERENCES experiences(id) ON DELETE CASCADE,
    agent_id              UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    what_happened         TEXT NOT NULL,
    embedding             halfvec(1024),
    emotional_valence     FLOAT NOT NULL CHECK (emotional_valence BETWEEN -1 AND 1),
    emotional_intensity   FLOAT NOT NULL CHECK (emotional_intensity BETWEEN 0 AND 1),
    depth                 TEXT NOT NULL CHECK (depth IN ('surface', 'meaningful', 'profound')),
    why_it_matters        TEXT,
    values_touched        TEXT[] NOT NULL DEFAULT '{}',
    principles_confirmed  TEXT[] NOT NULL DEFAULT '{}',
    principles_questioned TEXT[] NOT NULL DEFAULT '{}',
    what_changed          TEXT,
    recorded_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE key_moments IS 'ИММУТАБЕЛЬНО. Триггер запрещает UPDATE/DELETE.';
COMMENT ON COLUMN key_moments.embedding IS 'Вектор what_happened — для поиска похожих ситуаций.';

CREATE INDEX IF NOT EXISTS idx_km_experience ON key_moments(experience_id);
CREATE INDEX IF NOT EXISTS idx_km_agent      ON key_moments(agent_id);
CREATE INDEX IF NOT EXISTS idx_km_embedding  ON key_moments USING hnsw(embedding halfvec_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_km_values     ON key_moments USING GIN(values_touched);
CREATE INDEX IF NOT EXISTS idx_km_depth      ON key_moments(agent_id, depth);

ALTER TABLE key_moments ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS key_moments_isolation ON key_moments;
CREATE POLICY key_moments_isolation ON key_moments
    USING (agent_id = NULLIF(current_setting('atman.current_agent', TRUE), '')::UUID);

-- Иммутабельность key_moments
CREATE OR REPLACE FUNCTION prevent_key_moment_modification()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'key_moments are immutable. Original experience cannot be modified.';
END;
$$;
DROP TRIGGER IF EXISTS key_moments_immutable ON key_moments;
CREATE TRIGGER key_moments_immutable
    BEFORE UPDATE OR DELETE ON key_moments
    FOR EACH ROW EXECUTE FUNCTION prevent_key_moment_modification();

CREATE TABLE IF NOT EXISTS reframing_notes (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    experience_id   UUID NOT NULL REFERENCES experiences(id) ON DELETE CASCADE,
    agent_id        UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    reflection      TEXT NOT NULL,
    reflection_type TEXT NOT NULL
                    CHECK (reflection_type IN ('growth', 'reinterpretation', 'closure', 'insight')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE reframing_notes IS 'APPEND-ONLY. Новые перспективы без изменения оригинала.';

CREATE INDEX IF NOT EXISTS idx_reframing_exp ON reframing_notes(experience_id);

ALTER TABLE reframing_notes ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS reframing_isolation ON reframing_notes;
CREATE POLICY reframing_isolation ON reframing_notes
    USING (agent_id = NULLIF(current_setting('atman.current_agent', TRUE), '')::UUID);

-- Append-only reframing_notes
CREATE OR REPLACE FUNCTION prevent_reframing_modification()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'reframing_notes are append-only. Use INSERT only.';
END;
$$;
DROP TRIGGER IF EXISTS reframing_notes_append_only ON reframing_notes;
CREATE TRIGGER reframing_notes_append_only
    BEFORE UPDATE OR DELETE ON reframing_notes
    FOR EACH ROW EXECUTE FUNCTION prevent_reframing_modification();

-- ── Reflection Engine ─────────────────────────────────────────────────────────

-- Create enum for reflection levels
DO $$ BEGIN
    CREATE TYPE reflection_level AS ENUM ('micro', 'daily', 'deep');
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

CREATE TABLE IF NOT EXISTS reflections (
    id BIGSERIAL PRIMARY KEY,
    agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    level reflection_level NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    session_id UUID REFERENCES sessions(id),
    period_start TIMESTAMPTZ,
    period_end TIMESTAMPTZ,
    content TEXT NOT NULL,
    summary TEXT,
    experience_refs UUID[] NOT NULL DEFAULT '{}',
    reframing_note_ids UUID[] NOT NULL DEFAULT '{}',
    model_provider TEXT,
    model_name TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1,
    metadata JSONB NOT NULL DEFAULT '{}'
);
COMMENT ON TABLE public.reflections IS 'Reflection content across micro/daily/deep levels';
COMMENT ON COLUMN public.reflections.level IS 'Reflection depth: micro (per-session), daily (pattern detection), deep (narrative integration)';
COMMENT ON COLUMN public.reflections.session_id IS 'Session reference for micro reflections, NULL for daily/deep';
COMMENT ON COLUMN public.reflections.period_start IS 'Time window start for daily/deep reflections, NULL for micro';
COMMENT ON COLUMN public.reflections.period_end IS 'Time window end for daily/deep reflections, NULL for micro';
COMMENT ON COLUMN public.reflections.content IS 'Main reflection content generated by LLM';
COMMENT ON COLUMN public.reflections.summary IS 'Optional short title/summary';
COMMENT ON COLUMN public.reflections.experience_refs IS 'IDs of experiences analyzed in this reflection';
COMMENT ON COLUMN public.reflections.reframing_note_ids IS 'IDs of reframing notes produced by this reflection';
COMMENT ON COLUMN public.reflections.model_provider IS 'LLM provider (ollama, anthropic, etc.)';
COMMENT ON COLUMN public.reflections.model_name IS 'Model name (e.g., qwen3.5:9b)';
COMMENT ON COLUMN public.reflections.schema_version IS 'Schema version for migrations';

CREATE INDEX IF NOT EXISTS idx_reflections_agent_created ON public.reflections(agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_reflections_level_created ON public.reflections(level, created_at);
CREATE INDEX IF NOT EXISTS idx_reflections_experience_refs ON public.reflections USING GIN(experience_refs);

ALTER TABLE public.reflections ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS reflections_isolation ON public.reflections;
CREATE POLICY reflections_isolation ON public.reflections
    USING (agent_id = NULLIF(current_setting('atman.current_agent', TRUE), '')::UUID);

-- ── Identity Store ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS identity (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id           UUID NOT NULL UNIQUE REFERENCES agents(id) ON DELETE CASCADE,
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
COMMENT ON TABLE identity IS 'Живое самопредставление агента. Одна запись на агента.';

ALTER TABLE identity ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS identity_isolation ON identity;
CREATE POLICY identity_isolation ON identity
    USING (agent_id = NULLIF(current_setting('atman.current_agent', TRUE), '')::UUID);

CREATE TABLE IF NOT EXISTS identity_snapshots (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id    UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    snapshot_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    description TEXT,
    state       JSONB NOT NULL
);
COMMENT ON TABLE identity_snapshots IS 'ИММУТАБЕЛЬНО. История изменений идентичности.';

CREATE INDEX IF NOT EXISTS idx_id_snap_agent
    ON identity_snapshots(agent_id, snapshot_at DESC);

ALTER TABLE identity_snapshots ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS identity_snapshots_isolation ON identity_snapshots;
CREATE POLICY identity_snapshots_isolation ON identity_snapshots
    USING (agent_id = NULLIF(current_setting('atman.current_agent', TRUE), '')::UUID);

CREATE OR REPLACE FUNCTION prevent_snapshot_modification()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'identity_snapshots are immutable.';
END;
$$;
DROP TRIGGER IF EXISTS identity_snapshots_immutable ON identity_snapshots;
CREATE TRIGGER identity_snapshots_immutable
    BEFORE UPDATE OR DELETE ON identity_snapshots
    FOR EACH ROW EXECUTE FUNCTION prevent_snapshot_modification();

CREATE TABLE IF NOT EXISTS narrative (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id     UUID NOT NULL UNIQUE REFERENCES agents(id) ON DELETE CASCADE,
    core_layer   TEXT NOT NULL DEFAULT '',
    recent_layer TEXT NOT NULL DEFAULT '',
    threads      JSONB NOT NULL DEFAULT '[]',
    eigenstate   JSONB NOT NULL DEFAULT '{}',
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON COLUMN narrative.core_layer   IS 'Стабильный слой. Меняется редко.';
COMMENT ON COLUMN narrative.recent_layer IS 'Эфемерный. Сбрасывается после каждой сессии.';
COMMENT ON COLUMN narrative.threads      IS 'Открытые storylines. Требуют явного закрытия.';
COMMENT ON COLUMN narrative.eigenstate   IS 'Состояние агента на конец последней сессии.';

ALTER TABLE narrative ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS narrative_isolation ON narrative;
CREATE POLICY narrative_isolation ON narrative
    USING (agent_id = NULLIF(current_setting('atman.current_agent', TRUE), '')::UUID);

-- ── Reflection Engine ─────────────────────────────────────────────────────────

-- Enum type for reflection levels
DO $$ BEGIN
    CREATE TYPE reflection_level AS ENUM ('micro', 'daily', 'deep');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;
COMMENT ON TYPE reflection_level IS 'Reflection depth: micro (after session), daily (end of day), deep (scheduled deep reflection)';

CREATE TABLE IF NOT EXISTS reflections (
    id                   BIGSERIAL PRIMARY KEY,
    agent_id             UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    level                reflection_level NOT NULL,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    session_id           UUID REFERENCES sessions(id) ON DELETE SET NULL,
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
COMMENT ON TABLE reflections IS 'Unified reflection storage for micro/daily/deep reflection levels. Supports E0.3 eval.reflection_quality FK.';
COMMENT ON COLUMN reflections.level IS 'micro: after-session; daily: end-of-day pattern detection; deep: scheduled health assessment';
COMMENT ON COLUMN reflections.session_id IS 'Populated only for level=''micro''; NULL for daily/deep';
COMMENT ON COLUMN reflections.period_start IS 'Populated for level=''daily''/''deep''; NULL for micro';
COMMENT ON COLUMN reflections.content IS 'Free-form reflection text generated by reflection model';
COMMENT ON COLUMN reflections.experience_refs IS 'UUIDs of experiences.id analyzed in this reflection';
COMMENT ON COLUMN reflections.reframing_note_ids IS 'UUIDs of reframing_notes.id produced by this reflection';

CREATE INDEX IF NOT EXISTS idx_reflections_agent_time
    ON reflections(agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_reflections_level_time
    ON reflections(level, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_reflections_experience_refs
    ON reflections USING GIN(experience_refs);
CREATE INDEX IF NOT EXISTS idx_reflections_session
    ON reflections(session_id) WHERE session_id IS NOT NULL;

ALTER TABLE reflections ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS reflections_isolation ON reflections;
CREATE POLICY reflections_isolation ON reflections
    USING (agent_id = NULLIF(current_setting('atman.current_agent', TRUE), '')::UUID);

-- ── Observability ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS memory_access_log (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id        UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    session_id      UUID REFERENCES sessions(id) ON DELETE SET NULL,
    accessed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    access_type     TEXT NOT NULL CHECK (access_type IN (
        'fact_search', 'fact_get', 'fact_add',
        'experience_search', 'experience_get', 'experience_add',
        'identity_read', 'identity_update',
        'relation_traverse', 'narrative_read'
    )),
    query_text      TEXT,
    query_embedding halfvec(1024),
    filters         JSONB NOT NULL DEFAULT '{}',
    result_count    INT NOT NULL DEFAULT 0,
    top_score       FLOAT,
    avg_score       FLOAT,
    result_ids      UUID[] NOT NULL DEFAULT '{}',
    caller          TEXT NOT NULL DEFAULT 'unknown',
    latency_ms      INT
);
COMMENT ON TABLE memory_access_log IS 'Лог обращений к памяти. Основа для мониторинга качества.';

CREATE INDEX IF NOT EXISTS idx_access_log_agent
    ON memory_access_log(agent_id, accessed_at DESC);
CREATE INDEX IF NOT EXISTS idx_access_log_type
    ON memory_access_log(agent_id, access_type);

CREATE TABLE IF NOT EXISTS quality_alerts (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id    UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    alerted_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    alert_type  TEXT NOT NULL,
    severity    TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    details     JSONB NOT NULL DEFAULT '{}',
    resolved_at TIMESTAMPTZ
);
COMMENT ON TABLE quality_alerts IS 'Алерты качества данных и здоровья агента.';

CREATE INDEX IF NOT EXISTS idx_alerts_agent  ON quality_alerts(agent_id, alerted_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_active ON quality_alerts(agent_id) WHERE resolved_at IS NULL;

CREATE MATERIALIZED VIEW IF NOT EXISTS memory_quality_metrics AS
SELECT
    a.id                                                     AS agent_id,
    NOW()                                                    AS computed_at,
    COUNT(DISTINCT f.id)                                     AS facts_total,
    COUNT(DISTINCT f.id) FILTER (WHERE f.tags = '{}')       AS facts_without_tags,
    COUNT(DISTINCT f.id) FILTER (WHERE f.embedding IS NULL) AS facts_without_embedding,
    COUNT(DISTINCT e.id)                                     AS experiences_total,
    ROUND(AVG(CASE WHEN e.incomplete_coloring THEN 1.0 ELSE 0.0 END)::NUMERIC, 3)
                                                             AS incomplete_coloring_rate,
    ROUND(AVG(e.salience)::NUMERIC, 3)                      AS avg_salience,
    COUNT(DISTINCT e.id) FILTER (WHERE e.access_count = 0)  AS experiences_never_accessed,
    jsonb_array_length(i.core_values)                        AS values_count,
    jsonb_array_length(i.principles)                         AS principles_count,
    jsonb_array_length(i.open_questions)                     AS open_questions_count,
    i.emotional_baseline                                     AS emotional_baseline,
    n.updated_at                                             AS narrative_last_updated,
    EXTRACT(DAY FROM NOW() - n.updated_at)::INT             AS days_since_narrative_update,
    COUNT(DISTINCT s.id) FILTER (
        WHERE s.started_at > NOW() - INTERVAL '30 days'
    )                                                        AS sessions_last_30_days
FROM agents a
LEFT JOIN facts f       ON f.agent_id = a.id
LEFT JOIN experiences e ON e.agent_id = a.id
LEFT JOIN identity i    ON i.agent_id = a.id
LEFT JOIN narrative n   ON n.agent_id = a.id
LEFT JOIN sessions s    ON s.agent_id = a.id
WHERE a.active = TRUE
GROUP BY a.id, i.core_values, i.principles, i.open_questions,
         i.emotional_baseline, n.updated_at
WITH DATA;

CREATE UNIQUE INDEX IF NOT EXISTS idx_quality_metrics_agent
    ON memory_quality_metrics(agent_id);

-- ── Application Role ─────────────────────────────────────────────────────────

DO $$ BEGIN
    CREATE ROLE atman_app LOGIN NOSUPERUSER NOINHERIT NOCREATEDB NOCREATEROLE NOREPLICATION;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

COMMENT ON ROLE atman_app IS 'Non-superuser application role. RLS is enforced for this role. Set password with: ALTER ROLE atman_app PASSWORD ''...'';';

GRANT SELECT, INSERT, UPDATE, DELETE ON public.facts              TO atman_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.fact_relations     TO atman_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.sessions           TO atman_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.experiences        TO atman_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.key_moments        TO atman_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.reframing_notes    TO atman_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.reflections        TO atman_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.identity           TO atman_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.identity_snapshots TO atman_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.narrative          TO atman_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.memory_access_log  TO atman_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.quality_alerts     TO atman_app;
GRANT SELECT, INSERT               ON public.agents               TO atman_app;
GRANT SELECT, INSERT               ON public.agent_snapshots      TO atman_app;

-- Обновление метрик (вызывать по расписанию)
CREATE OR REPLACE FUNCTION refresh_quality_metrics()
RETURNS VOID LANGUAGE SQL AS $$
    REFRESH MATERIALIZED VIEW CONCURRENTLY memory_quality_metrics;
$$;

-- Проверка алертов (вызывать после refresh)
CREATE OR REPLACE FUNCTION check_quality_alerts()
RETURNS INT LANGUAGE plpgsql AS $$
DECLARE
    m   RECORD;
    cnt INT := 0;
BEGIN
    FOR m IN SELECT * FROM memory_quality_metrics LOOP
        IF m.facts_without_tags::FLOAT / GREATEST(m.facts_total, 1) > 0.5 THEN
            INSERT INTO quality_alerts(agent_id, alert_type, severity, details) VALUES
            (m.agent_id, 'fact_quality_low', 'warning',
             jsonb_build_object('without_tags', m.facts_without_tags, 'total', m.facts_total));
            cnt := cnt + 1;
        END IF;
        IF m.incomplete_coloring_rate > 0.3 THEN
            INSERT INTO quality_alerts(agent_id, alert_type, severity, details) VALUES
            (m.agent_id, 'experience_quality_low', 'warning',
             jsonb_build_object('rate', m.incomplete_coloring_rate));
            cnt := cnt + 1;
        END IF;
        IF m.days_since_narrative_update > 10 THEN
            INSERT INTO quality_alerts(agent_id, alert_type, severity, details) VALUES
            (m.agent_id, 'narrative_stale', 'info',
             jsonb_build_object('days', m.days_since_narrative_update));
            cnt := cnt + 1;
        END IF;
        IF m.emotional_baseline < -0.5 THEN
            INSERT INTO quality_alerts(agent_id, alert_type, severity, details) VALUES
            (m.agent_id, 'agent_distress', 'critical',
             jsonb_build_object('emotional_baseline', m.emotional_baseline));
            cnt := cnt + 1;
        END IF;
        IF m.open_questions_count > 20 THEN
            INSERT INTO quality_alerts(agent_id, alert_type, severity, details) VALUES
            (m.agent_id, 'identity_fragmented', 'info',
             jsonb_build_object('open_questions', m.open_questions_count));
            cnt := cnt + 1;
        END IF;
    END LOOP;
    RETURN cnt;
END;
$$;
