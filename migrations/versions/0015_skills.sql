-- Migration 0015: public.skills + public.skill_invocations — skill-loop tables
--
-- Adds two tables to the public schema (NOT per-agent, but RLS-isolated by agent_id):
--   skills             — registry of all skills for all agents
--   skill_invocations  — invocation log with preliminary/final status
--
-- Design notes:
--   - Skill entities live in agent_{N}.entities (entity_type='skill'); entity_id here
--     is a soft cross-schema reference (no FK constraint, consistent with existing pattern).
--   - Tables are always created regardless of atman.skills.enabled config — this allows
--     toggling the feature without re-running migrations.
--   - RLS is enforced via atman.current_agent session variable (same pattern as facts table).
--   - skill_invocations.session_id is a soft ref to agent_{N}.sessions.id (no FK, cross-schema).
--
-- Depends on: migration 0004 (public.agents must exist)
--
-- Usage:
--   psql -d atman -f migrations/versions/0015_skills.sql
--
-- Rollback:
--   DROP TABLE IF EXISTS public.skill_invocations CASCADE;
--   DROP TABLE IF EXISTS public.skills CASCADE;

-- ── Step 1: public.skills ─────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.skills (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id             UUID NOT NULL REFERENCES public.agents(id) ON DELETE CASCADE,
    -- soft cross-schema ref to agent_{N}.entities.id — no FK constraint by design
    entity_id            UUID NOT NULL,
    name                 TEXT NOT NULL,       -- kebab-case, matches metadata.name in SKILL.md
    description          TEXT NOT NULL DEFAULT '',  -- short human-readable summary (from SKILL.md description)
    version              TEXT NOT NULL DEFAULT '0.1.0',
    kind                 TEXT NOT NULL        -- 'active' | 'passive'
                             CHECK (kind IN ('active', 'passive')),
    status               TEXT NOT NULL DEFAULT 'draft'
                             CHECK (status IN ('draft', 'active', 'disabled')),
    origin               TEXT NOT NULL
                             CHECK (origin IN ('in_session', 'reflection_pattern', 'external')),
    core                 BOOLEAN NOT NULL DEFAULT FALSE,
    session_scoped       BOOLEAN NOT NULL DEFAULT FALSE,

    -- pinning (two independent flags)
    user_pinned          BOOLEAN NOT NULL DEFAULT FALSE,
    auto_pinned          BOOLEAN NOT NULL DEFAULT FALSE,

    -- usage statistics
    invocations_count    INT NOT NULL DEFAULT 0,
    success_count        INT NOT NULL DEFAULT 0,
    failure_count        INT NOT NULL DEFAULT 0,
    last_used_at         TIMESTAMPTZ,
    sessions_since_use   INT NOT NULL DEFAULT 0,

    -- revision tracking
    revision_needed      BOOLEAN NOT NULL DEFAULT FALSE,
    revision_priority    INT NOT NULL DEFAULT 0,
    last_revised_at      TIMESTAMPTZ,
    -- true when SKILL.md was auto-generated from README (external skills without manifest)
    manifest_inferred    BOOLEAN NOT NULL DEFAULT FALSE,

    -- filesystem paths (Agent Skills Open Standard layout)
    skill_root           TEXT NOT NULL,   -- absolute path to skill directory
    manifest_path        TEXT NOT NULL,   -- skill_root + '/SKILL.md'

    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE (agent_id, name)
);

-- ── Step 2: RLS on public.skills ─────────────────────────────────────────────

ALTER TABLE public.skills ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.skills FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS skills_isolation ON public.skills;
CREATE POLICY skills_isolation ON public.skills
    USING (
        agent_id = NULLIF(current_setting('atman.current_agent', TRUE), '')::uuid
    );

-- ── Step 3: indexes on public.skills ─────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_skills_agent_status
    ON public.skills (agent_id, status);

-- Fast lookup of skills that need to be bootstrapped (pinned → always in session)
CREATE INDEX IF NOT EXISTS idx_skills_pinned
    ON public.skills (agent_id, user_pinned, auto_pinned)
    WHERE status = 'active';

-- Revision queue — skills flagged for review
CREATE INDEX IF NOT EXISTS idx_skills_revision
    ON public.skills (agent_id, revision_priority DESC)
    WHERE revision_needed = TRUE;

-- ── Step 4: public.skill_invocations ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.skill_invocations (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    skill_id              UUID NOT NULL REFERENCES public.skills(id) ON DELETE CASCADE,
    -- denormalized for RLS and fast filter without join
    agent_id              UUID NOT NULL REFERENCES public.agents(id) ON DELETE CASCADE,
    -- soft cross-schema ref to agent_{N}.sessions.id — no FK by design
    session_id            UUID NOT NULL,

    started_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at              TIMESTAMPTZ,

    -- status at time of execution (before reflection processes it)
    preliminary_status    TEXT
                              CHECK (preliminary_status IN (
                                  'executing', 'executed_ok', 'executed_fail', 'executed_unknown'
                              )),
    -- final verdict set by micro reflection; NULL until processed
    final_status          TEXT
                              CHECK (final_status IN ('helped', 'didnt_help', 'unclear')),

    -- explicit marker from agent (strongest signal)
    agent_marker          TEXT CHECK (agent_marker IN ('helped', 'didnt_help', 'unclear')),
    agent_marker_note     TEXT,

    -- passive signal arrays (append-only during session)
    user_feedback_hints   JSONB NOT NULL DEFAULT '[]',
    behavioral_hints      JSONB NOT NULL DEFAULT '[]',

    exit_code             INT,

    input_context_summary TEXT,
    output_summary        TEXT,

    -- timestamp set by micro reflection after processing
    processed_at          TIMESTAMPTZ
);

-- ── Step 5: RLS on public.skill_invocations ──────────────────────────────────

ALTER TABLE public.skill_invocations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.skill_invocations FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS skill_invocations_isolation ON public.skill_invocations;
CREATE POLICY skill_invocations_isolation ON public.skill_invocations
    USING (
        agent_id = NULLIF(current_setting('atman.current_agent', TRUE), '')::uuid
    );

-- ── Step 6: indexes on public.skill_invocations ──────────────────────────────

-- History lookup for a skill, newest first
CREATE INDEX IF NOT EXISTS idx_skill_invocations_skill_time
    ON public.skill_invocations (skill_id, started_at DESC);

-- Session-level lookup (used during micro reflection)
CREATE INDEX IF NOT EXISTS idx_skill_invocations_agent_session
    ON public.skill_invocations (agent_id, session_id);

-- Unprocessed invocations queue for micro reflection
CREATE INDEX IF NOT EXISTS idx_skill_invocations_unprocessed
    ON public.skill_invocations (agent_id, processed_at)
    WHERE processed_at IS NULL;

-- ── Step 7: grants ────────────────────────────────────────────────────────────

GRANT SELECT, INSERT, UPDATE ON public.skills TO atman_app;
GRANT SELECT, INSERT, UPDATE ON public.skill_invocations TO atman_app;
