-- Migration 0018: extend validation_findings.finding_type CHECK
--
-- Aligns the per-agent ``validation_findings.finding_type`` CHECK constraint
-- with the current ``FindingType`` Python enum (`core/models/validation.py`).
-- Three categories of values were drifting:
--
--   * HLE-28 async-pipeline signals already in the Python enum:
--     ``pending_structured_markers``, ``analysis_failed``, ``affect_detector_silent``.
--   * HLE-31 Level-C psychological quality metrics added in this PR:
--     ``divergence_pattern``, ``stance_formation_too_fast``.
--   * Also widens ``resolution`` to accept ``requires_attention`` (already in
--     the ``ResolutionStatus`` enum, missing from the original CHECK).
--
-- Existing rows are unaffected — the new CHECK is a superset of the old one,
-- so the constraint replacement is a non-blocking metadata change.
--
-- Depends on: migration 0010.
--
-- Usage:
--   psql -d atman -f migrations/versions/0018_validation_findings_check_expand.sql
--
-- Rollback (per agent schema):
--   ALTER TABLE agent_N.validation_findings
--     DROP CONSTRAINT validation_findings_finding_type_check;
--   ALTER TABLE agent_N.validation_findings
--     ADD CONSTRAINT validation_findings_finding_type_check
--     CHECK (finding_type IN ('orphan_entity','similar_entities','stale_moment',
--                             'quality_metric','embedding_missing','other'));

-- ── Step 1: helper that widens the CHECK on one schema ──────────────────────

CREATE OR REPLACE FUNCTION public.extend_agent_schema_0018(schema_name TEXT)
RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN

    -- finding_type — broaden to match the Python `FindingType` enum.
    EXECUTE format($sql$
        ALTER TABLE %I.validation_findings
            DROP CONSTRAINT IF EXISTS validation_findings_finding_type_check;
        ALTER TABLE %I.validation_findings
            ADD CONSTRAINT validation_findings_finding_type_check
            CHECK (finding_type IN (
                'orphan_entity',
                'similar_entities',
                'stale_moment',
                'quality_metric',
                'embedding_missing',
                'pending_structured_markers',
                'analysis_failed',
                'affect_detector_silent',
                'divergence_pattern',
                'stance_formation_too_fast',
                'other'
            ));
    $sql$, schema_name, schema_name);

    -- resolution — add 'requires_attention' which R8 introduced to the
    -- Python ResolutionStatus enum. CHECK accepts NULL (unresolved).
    EXECUTE format($sql$
        ALTER TABLE %I.validation_findings
            DROP CONSTRAINT IF EXISTS validation_findings_resolution_check;
        ALTER TABLE %I.validation_findings
            ADD CONSTRAINT validation_findings_resolution_check
            CHECK (
                resolution IS NULL
                OR resolution IN ('fixed','ignored','escalated','requires_attention')
            );
    $sql$, schema_name, schema_name);

END;
$$;

-- ── Step 2: backfill every existing per-agent schema ────────────────────────

DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT serial_id
          FROM public.agents
         ORDER BY serial_id
    LOOP
        PERFORM public.extend_agent_schema_0018('agent_' || r.serial_id);
    END LOOP;
END;
$$;
