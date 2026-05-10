-- Migration: Add embed_model column for embedding traceability
-- Issue: E25.4 - Migration: add embed_model TEXT column
--
-- This migration adds embed_model TEXT column to all tables that store embeddings.
-- The column tracks which model was used to generate each embedding vector,
-- enabling traceability when models change in the future.

-- Add embed_model column to facts table
ALTER TABLE public.facts
ADD COLUMN IF NOT EXISTS embed_model TEXT;

-- Add embed_model column to key_moments table
ALTER TABLE public.key_moments
ADD COLUMN IF NOT EXISTS embed_model TEXT;

-- Add embed_model column to identity_snapshots table
ALTER TABLE public.identity_snapshots
ADD COLUMN IF NOT EXISTS embed_model TEXT;

-- Add comments explaining the column purpose
COMMENT ON COLUMN public.facts.embed_model IS 'Name of the embedding model used to generate the embedding vector (e.g., qwen3-embedding:1.5b)';
COMMENT ON COLUMN public.key_moments.embed_model IS 'Name of the embedding model used to generate the embedding vector (e.g., qwen3-embedding:1.5b)';
COMMENT ON COLUMN public.identity_snapshots.embed_model IS 'Name of the embedding model used to generate the embedding vector (e.g., qwen3-embedding:1.5b)';
