from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _migration(name: str) -> str:
    return (ROOT / "migrations" / "versions" / name).read_text(encoding="utf-8")


def _compact(sql: str) -> str:
    return " ".join(sql.upper().split())


def test_reflections_migration_forces_rls_for_owner_connections() -> None:
    sql = _compact(_migration("0001_create_reflections_table.sql"))

    assert "ALTER TABLE REFLECTIONS ENABLE ROW LEVEL SECURITY" in sql
    assert "ALTER TABLE REFLECTIONS FORCE ROW LEVEL SECURITY" in sql


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
