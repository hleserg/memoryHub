-- Migration 0016: drop legacy public subjective tables
--
-- Run only after 0015 backfill and application code target agent_{N}.* tables.
--
-- Usage:
--   psql -d atman -f migrations/versions/0016_drop_public_subjective_tables.sql

DROP TABLE IF EXISTS public.pending_human_review CASCADE;
DROP TABLE IF EXISTS public.self_applied_changes CASCADE;
DROP TABLE IF EXISTS public.reflections CASCADE;
