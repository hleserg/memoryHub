-- Migration 0013: Pending human review inbox for reflection's "I'm not sure" items.
--
-- Reflection (Daily/Deep) writes items here when it is not confident enough to
-- apply an identity/narrative change on its own. The agent runner picks up
-- top unresolved items at the start of the next interactive session and
-- surfaces them to the human. Resolution is one-shot.
--
-- This is additive and idempotent.
--
-- Usage:
--   psql -d atman -f migrations/versions/0013_pending_human_review.sql
--
-- Rollback:
--   DROP TABLE IF EXISTS public.pending_human_review CASCADE;

CREATE TABLE IF NOT EXISTS public.pending_human_review (
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
    applied_change_id UUID REFERENCES public.self_applied_changes(id)
);

CREATE INDEX IF NOT EXISTS pending_human_review_unresolved_idx
    ON public.pending_human_review(priority, created_at)
    WHERE resolved_at IS NULL;
CREATE INDEX IF NOT EXISTS pending_human_review_kind_idx
    ON public.pending_human_review(kind);
CREATE INDEX IF NOT EXISTS pending_human_review_created_by_idx
    ON public.pending_human_review(created_by);
