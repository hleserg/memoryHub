-- =============================================================================
-- Migration 0002: Create facts table
-- Description: Factual memory storage with pgvector support and RLS
-- Author: E28 — PostgreSQL Factual Memory
-- Date: 2026-05-10
-- =============================================================================

-- ── Extensions ────────────────────────────────────────────────────────────────

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ── Fact Status Enum ──────────────────────────────────────────────────────────

DO $$ BEGIN
    CREATE TYPE fact_status AS ENUM ('active', 'disputed', 'superseded', 'invalidated');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

COMMENT ON TYPE fact_status IS 'Lifecycle status of a fact: active (default), disputed, superseded by newer fact, invalidated';

-- ── Facts Table ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.facts (
    id                  UUID PRIMARY KEY,
    agent_id            UUID NOT NULL,
    content             TEXT NOT NULL,
    source              TEXT NOT NULL,
    tags                TEXT[] NOT NULL DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata            JSONB NOT NULL DEFAULT '{}',

    -- Lifecycle
    status              fact_status NOT NULL DEFAULT 'active',
    invalidated_at      TIMESTAMPTZ,
    invalidation_note   TEXT NOT NULL DEFAULT '',
    superseded_by       UUID REFERENCES public.facts(id),
    disputed_at         TIMESTAMPTZ,

    -- Salience
    confirmation_count  INTEGER NOT NULL DEFAULT 0 CHECK (confirmation_count >= 0),
    last_confirmed_at   TIMESTAMPTZ,
    salience            FLOAT NOT NULL DEFAULT 0.5 CHECK (salience BETWEEN 0.0 AND 1.0),

    -- Semantic embedding (nullable: populated when embedding model is available).
    -- halfvec stores float16 vectors — half the space of float32, negligible
    -- precision loss for cosine similarity, and HNSW supports up to 4000 dims.
    embedding           halfvec(2560)
);

COMMENT ON TABLE public.facts IS 'Factual memory: verifiable facts without interpretation. Owned per agent.';
COMMENT ON COLUMN public.facts.agent_id IS 'Owning agent UUID (used for RLS)';
COMMENT ON COLUMN public.facts.embedding IS 'halfvec(2560) embedding (qwen3-embedding:4b). float16 storage: half the size of float32, negligible cosine similarity loss. NULL when model unavailable — system degrades gracefully to text search.';

-- ── Fact Relations Table ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.fact_relations (
    source_id       UUID NOT NULL REFERENCES public.facts(id) ON DELETE CASCADE,
    target_id       UUID NOT NULL REFERENCES public.facts(id) ON DELETE CASCADE,
    relation_type   TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata        JSONB NOT NULL DEFAULT '{}',
    PRIMARY KEY (source_id, target_id, relation_type)
);

COMMENT ON TABLE public.fact_relations IS 'Graph edges between facts. Cascade-deleted when source fact is removed.';

-- ── Indexes ───────────────────────────────────────────────────────────────────

-- Primary lookup: agent's active facts ordered by recency
CREATE INDEX IF NOT EXISTS idx_facts_agent_status
    ON public.facts(agent_id, status, created_at DESC);

-- Tag array containment: facts @> ARRAY['tag1', 'tag2']
CREATE INDEX IF NOT EXISTS idx_facts_tags
    ON public.facts USING GIN(tags);

-- Trigram index for ILIKE text search (fallback when no embedding)
CREATE INDEX IF NOT EXISTS idx_facts_content_trgm
    ON public.facts USING GIN(content gin_trgm_ops);

-- HNSW vector index for cosine similarity search (only populated rows)
CREATE INDEX IF NOT EXISTS idx_facts_embedding
    ON public.facts USING hnsw(embedding halfvec_cosine_ops)
    WHERE embedding IS NOT NULL;

-- Graph traversal: outgoing edges from a fact
CREATE INDEX IF NOT EXISTS idx_fact_relations_source
    ON public.fact_relations(source_id);

-- Graph traversal: incoming edges to a fact (1-hop expansion)
CREATE INDEX IF NOT EXISTS idx_fact_relations_target
    ON public.fact_relations(target_id);

-- ── Row-Level Security ────────────────────────────────────────────────────────

-- PLAYBOOK-START
-- id: row-level-security-dependent-tables
-- category: failure-modes
-- title: RLS Must Cover Owners and Dependent Tables
-- status: draft
--
-- Pattern: row-level security for tenant-owned rows must force policies for
-- owner-role connections and must extend to dependent association tables via
-- predicates that prove both referenced rows belong to the current tenant.
--
-- Why generalizable: otherwise a supposedly isolated primary table can still
-- leak data through owner bypass or globally readable edge tables.
-- PLAYBOOK-END
ALTER TABLE public.facts ENABLE ROW LEVEL SECURITY;
-- FORCE RLS so the table owner (atman) is also subject to the policy.
-- Without this, the owner bypasses all RLS policies by default.
ALTER TABLE public.facts FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS facts_isolation ON public.facts;
CREATE POLICY facts_isolation ON public.facts
    USING (agent_id = NULLIF(current_setting('atman.current_agent', TRUE), '')::UUID);

COMMENT ON POLICY facts_isolation ON public.facts IS 'RLS: agent_id must match atman.current_agent session variable';

ALTER TABLE public.fact_relations ENABLE ROW LEVEL SECURITY;
-- Relations can disclose cross-agent graph structure, so protect them with the
-- same owner-safe posture as facts and require both endpoints to be visible.
ALTER TABLE public.fact_relations FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS fact_relations_isolation ON public.fact_relations;
CREATE POLICY fact_relations_isolation ON public.fact_relations
    USING (
        EXISTS (
            SELECT 1
            FROM public.facts f
            WHERE f.id = source_id
              AND f.agent_id = NULLIF(current_setting('atman.current_agent', TRUE), '')::UUID
        )
        AND EXISTS (
            SELECT 1
            FROM public.facts f
            WHERE f.id = target_id
              AND f.agent_id = NULLIF(current_setting('atman.current_agent', TRUE), '')::UUID
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1
            FROM public.facts f
            WHERE f.id = source_id
              AND f.agent_id = NULLIF(current_setting('atman.current_agent', TRUE), '')::UUID
        )
        AND EXISTS (
            SELECT 1
            FROM public.facts f
            WHERE f.id = target_id
              AND f.agent_id = NULLIF(current_setting('atman.current_agent', TRUE), '')::UUID
        )
    );

COMMENT ON POLICY fact_relations_isolation ON public.fact_relations IS 'RLS: both relation endpoints must belong to atman.current_agent';

-- ── Application Role ─────────────────────────────────────────────────────────
-- Non-superuser role for application connections. RLS is enforced for this role.
-- PostgreSQL superusers bypass RLS unconditionally; the app must connect as
-- atman_app (not as the owner) for isolation to take effect.
--
-- In production, set a password after creation:
--   ALTER ROLE atman_app PASSWORD 'strong-secret';

DO $$ BEGIN
    CREATE ROLE atman_app LOGIN NOSUPERUSER NOINHERIT NOCREATEDB NOCREATEROLE NOREPLICATION;
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

COMMENT ON ROLE atman_app IS 'Non-superuser application role. RLS is enforced for this role.';

GRANT SELECT, INSERT, UPDATE, DELETE ON public.facts         TO atman_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.fact_relations TO atman_app;

-- =============================================================================
-- End of Migration 0002
-- =============================================================================
