-- Migration 0005: Add key_moments table for KeyMoment adapter
--
-- This migration adds the key_moments table to support storing KeyMoment records
-- independently of experiences. This is additive and idempotent.
--
-- Note: This creates a simplified key_moments table in public schema for
-- the PostgresStateStore adapter. Migration 0004 already created per-agent
-- key_moments tables with full schema inside agent_N schemas.
--
-- Usage:
--   psql -d atman -f migrations/versions/0005_add_key_moments_table.sql
--
-- Rollback:
--   DROP TABLE IF EXISTS public.key_moments CASCADE;

CREATE TABLE IF NOT EXISTS public.key_moments (
    id UUID PRIMARY KEY,
    session_id UUID NOT NULL,
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS key_moments_session_idx ON public.key_moments(session_id);
