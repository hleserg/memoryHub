-- Migration 0011: public.maintenance_jobs — shared background-job queue
--
-- Adds one table to the public schema (NOT per-agent):
--   maintenance_jobs — queue for background maintenance tasks such as
--                      salience decay, memory guardian scans, entity merges,
--                      lingvo enrichment, and mrebel extraction.
--
-- agent_id is nullable: some jobs are global (no agent scope); when set,
-- it scopes the job to a specific agent and cascades on agent deletion.
--
-- run_key is an optional deduplication key (UNIQUE): callers can use it to
-- prevent duplicate scheduling of the same logical job.
--
-- Depends on: migration 0004 (public.agents must exist)
--
-- Usage:
--   psql -d atman -f migrations/versions/0011_maintenance_jobs.sql
--
-- Rollback:
--   DROP TABLE IF EXISTS public.maintenance_jobs CASCADE;

-- ── Step 1: create the shared jobs table ─────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.maintenance_jobs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_name     TEXT NOT NULL
                     CHECK (job_name IN (
                         'salience_decay',
                         'memory_guardian_scan',
                         'mrebel_extract',
                         'lingvo_enrich',
                         'entity_merge',
                         'other'
                     )),
    agent_id     UUID REFERENCES public.agents(id) ON DELETE CASCADE,
    payload      JSONB NOT NULL DEFAULT '{}',
    run_key      TEXT UNIQUE,
    status       TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending','running','succeeded','failed','skipped')),
    scheduled_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at   TIMESTAMPTZ,
    finished_at  TIMESTAMPTZ,
    error        TEXT,
    result       JSONB
);

-- ── Step 2: indexes ───────────────────────────────────────────────────────────

-- Efficient poll for the next pending job of a given type, ordered by schedule.
CREATE INDEX IF NOT EXISTS idx_maintenance_pending
    ON public.maintenance_jobs (job_name, scheduled_at)
    WHERE status = 'pending';

-- Per-agent job history / status lookup.
CREATE INDEX IF NOT EXISTS idx_maintenance_agent
    ON public.maintenance_jobs (agent_id, scheduled_at DESC)
    WHERE agent_id IS NOT NULL;

-- ── Step 3: grants ────────────────────────────────────────────────────────────

GRANT SELECT, INSERT, UPDATE ON public.maintenance_jobs TO atman_app;
