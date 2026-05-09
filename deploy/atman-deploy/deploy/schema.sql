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

CREATE TABLE IF NOT EXISTS facts (
    id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id   UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    content    TEXT NOT NULL,
    source     TEXT NOT NULL,
    tags       TEXT[] NOT NULL DEFAULT '{}',
    embedding  VECTOR(768),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata   JSONB NOT NULL DEFAULT '{}'
);
COMMENT ON TABLE facts IS 'Фактическая память. Факты без интерпретаций.';
COMMENT ON COLUMN facts.embedding IS 'Вектор qwen3-embedding:1.5b, 768 dims.';

CREATE INDEX IF NOT EXISTS idx_facts_agent     ON facts(agent_id);
CREATE INDEX IF NOT EXISTS idx_facts_tags      ON facts USING GIN(tags);
CREATE INDEX IF NOT EXISTS idx_facts_embedding ON facts USING hnsw(embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_facts_fts       ON facts USING GIN(to_tsvector('russian', content));

ALTER TABLE facts ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS facts_isolation ON facts;
CREATE POLICY facts_isolation ON facts
    USING (agent_id = NULLIF(current_setting('atman.current_agent', TRUE), '')::UUID);

CREATE TABLE IF NOT EXISTS fact_relations (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id       UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    source_fact_id UUID NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    target_fact_id UUID NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    relation_type  TEXT NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT no_self_relation CHECK (source_fact_id != target_fact_id)
);
COMMENT ON COLUMN fact_relations.relation_type IS 'led_to, confirms, contradicts, supports';

CREATE INDEX IF NOT EXISTS idx_fact_rel_agent  ON fact_relations(agent_id);
CREATE INDEX IF NOT EXISTS idx_fact_rel_source ON fact_relations(source_fact_id);
CREATE INDEX IF NOT EXISTS idx_fact_rel_target ON fact_relations(target_fact_id);

ALTER TABLE fact_relations ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS fact_relations_isolation ON fact_relations;
CREATE POLICY fact_relations_isolation ON fact_relations
    USING (agent_id = NULLIF(current_setting('atman.current_agent', TRUE), '')::UUID);

-- Sharing заложен но выключен (active DEFAULT FALSE)
CREATE TABLE IF NOT EXISTS fact_sharing (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    from_agent_id UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    to_agent_id   UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    fact_id       UUID NOT NULL REFERENCES facts(id) ON DELETE CASCADE,
    active        BOOLEAN NOT NULL DEFAULT FALSE,
    shared_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT no_self_sharing CHECK (from_agent_id != to_agent_id)
);
COMMENT ON TABLE fact_sharing IS 'Шаринг фактов между агентами. active=FALSE пока не нужно.';

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
    embedding             VECTOR(768),
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
CREATE INDEX IF NOT EXISTS idx_km_embedding  ON key_moments USING hnsw(embedding vector_cosine_ops);
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
    query_embedding VECTOR(768),
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
