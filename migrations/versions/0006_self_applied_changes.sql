-- Migration 0006: Audit table for self-applied identity/narrative changes.
--
-- Reflection (Daily and Deep) may apply identity or narrative revisions
-- on its own through `IdentityService.apply_self_change` /
-- `NarrativeRevisionService.apply_self_layer_update`. Every such application
-- writes a row here so it can be reviewed and reverted.
--
-- A revert is recorded by updating the original row with `reverted_at` and
-- `reverted_reason`; the actual revert mutation produces a new row with
-- `reverted_by_change_id` pointing back to the original.
--
-- This is additive and idempotent.
--
-- Usage:
--   psql -d atman -f migrations/versions/0006_self_applied_changes.sql
--
-- Rollback:
--   DROP TABLE IF EXISTS public.self_applied_changes CASCADE;

CREATE TABLE IF NOT EXISTS public.self_applied_changes (
    id UUID PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL,

    -- Agent whose identity this change targets. NULL for narrative-only
    -- changes, where ownership is keyed by narrative.identity_id instead.
    -- RLS is intentionally not enabled here; we currently run single-agent
    -- per workspace and verification happens in the service layer.
    agent_id UUID,

    actor TEXT NOT NULL CHECK (
        actor IN ('reflection_daily', 'reflection_deep', 'human_via_reflection_review')
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
    reverted_by_change_id UUID REFERENCES public.self_applied_changes(id)
);

CREATE INDEX IF NOT EXISTS self_applied_changes_applied_at_idx
    ON public.self_applied_changes(applied_at DESC);
CREATE INDEX IF NOT EXISTS self_applied_changes_actor_idx
    ON public.self_applied_changes(actor);
CREATE INDEX IF NOT EXISTS self_applied_changes_target_kind_idx
    ON public.self_applied_changes(target_kind);
CREATE INDEX IF NOT EXISTS self_applied_changes_reflection_event_idx
    ON public.self_applied_changes(reflection_event_id);
CREATE INDEX IF NOT EXISTS self_applied_changes_agent_idx
    ON public.self_applied_changes(agent_id) WHERE agent_id IS NOT NULL;
