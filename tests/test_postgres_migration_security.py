from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _migration(name: str) -> str:
    return (ROOT / "migrations" / "versions" / name).read_text(encoding="utf-8")


def _script(name: str) -> str:
    return (ROOT / "scripts" / name).read_text(encoding="utf-8")


def _compact(sql: str) -> str:
    return " ".join(sql.upper().split())


def test_legacy_reflections_migration_had_rls() -> None:
    """Migration 0001 created public.reflections with RLS (superseded by 0015/0016)."""
    sql = _compact(_migration("0001_create_reflections_table.sql"))

    assert "ALTER TABLE REFLECTIONS ENABLE ROW LEVEL SECURITY" in sql
    assert "ALTER TABLE REFLECTIONS FORCE ROW LEVEL SECURITY" in sql


def test_subjective_tables_live_in_per_agent_schema() -> None:
    sql = _compact(_migration("0015_move_subjective_tables.sql"))

    assert "CREATE TABLE IF NOT EXISTS %I.REFLECTIONS" in sql
    assert "CREATE TABLE IF NOT EXISTS %I.SELF_APPLIED_CHANGES" in sql
    assert "CREATE TABLE IF NOT EXISTS %I.PENDING_HUMAN_REVIEW" in sql
    assert "PERFORM PUBLIC.EXTEND_AGENT_SCHEMA_0015(SCHEMA_NAME)" in sql
    assert (
        "ROW LEVEL SECURITY"
        not in sql.split("EXTEND_AGENT_SCHEMA_0015")[1].split("MIGRATE_SUBJECTIVE_DATA_TO_AGENT")[0]
    )


def test_drop_public_subjective_tables_migration() -> None:
    sql = _compact(_migration("0016_drop_public_subjective_tables.sql"))

    assert "DROP TABLE IF EXISTS PUBLIC.REFLECTIONS" in sql
    assert "DROP TABLE IF EXISTS PUBLIC.SELF_APPLIED_CHANGES" in sql
    assert "DROP TABLE IF EXISTS PUBLIC.PENDING_HUMAN_REVIEW" in sql


def test_facts_migration_protects_relation_edges_with_rls() -> None:
    sql = _compact(_migration("0002_create_facts_table.sql"))

    assert "ALTER TABLE PUBLIC.FACTS FORCE ROW LEVEL SECURITY" in sql
    assert "ALTER TABLE PUBLIC.FACT_RELATIONS ENABLE ROW LEVEL SECURITY" in sql
    assert "ALTER TABLE PUBLIC.FACT_RELATIONS FORCE ROW LEVEL SECURITY" in sql
    assert "CREATE POLICY FACT_RELATIONS_ISOLATION ON PUBLIC.FACT_RELATIONS" in sql
    assert "WITH CHECK" in sql

    current_agent = "NULLIF(CURRENT_SETTING('ATMAN.CURRENT_AGENT', TRUE), '')::UUID"
    assert f"F.AGENT_ID = {current_agent}" in sql
    assert "WHERE F.ID = SOURCE_ID" in sql
    assert "WHERE F.ID = TARGET_ID" in sql


def test_facts_migration_matches_bge_m3_embedding_dimension() -> None:
    sql = _compact(_migration("0002_create_facts_table.sql"))

    assert "EMBEDDING HALFVEC(1024)" in sql
    assert "HALFVEC(2560) EMBEDDING" not in sql


def test_agent_schema_matches_bge_m3_embedding_dimension() -> None:
    sql = _compact(_migration("0004_agent_schema.sql"))

    assert "EMBEDDING HALFVEC(1024)" in sql
    assert "HALFVEC(2560)" not in sql


def test_embedding_migration_rebuilds_schema_before_writing_vectors() -> None:
    script = _script("migrate_embeddings.py")

    assert "ALTER COLUMN embedding TYPE halfvec({dimension})" in script
    assert "USING NULL::halfvec({dimension})" in script
    assert "DROP INDEX IF EXISTS public.idx_facts_embedding" in script
    assert "ALTER TABLE public.facts ADD COLUMN IF NOT EXISTS embed_model TEXT" in script
    assert "SET embedding = %s::halfvec, embed_model = %s" in script
