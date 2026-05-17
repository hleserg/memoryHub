"""HLE-39 — full skill-loop E2E against real PostgreSQL.

Verifies the full capture → invoke → mark_result → process_session_skills
cycle on a real ``PostgresSkillStore``. The cycle is exercised end-to-end
through the :class:`SkillManager` orchestrator and asserted on the
resulting database state (invocations table + skill stats).

This test is skipped unless a test database URL is available. Run locally
with::

    pytest tests/integration/test_skill_e2e.py -v -m integration
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from atman.config import SkillsSettings

# ── env / DB helpers (mirrors tests/integration/test_postgres_facts.py) ──

_env = Path(__file__).parents[2] / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        if _line.strip() and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip())


def _replace_db(url: str) -> str:
    if url.endswith("/atman"):
        return url[: -len("atman")] + "atman_test"
    return url + "_test"


def _test_db_url() -> str | None:
    if url := os.environ.get("TEST_DATABASE_URL"):
        return url
    if url := os.environ.get("DATABASE_URL"):
        return _replace_db(url)
    return None


def _admin_db_url() -> str | None:
    if url := os.environ.get("TEST_ADMIN_DATABASE_URL"):
        return url
    if url := os.environ.get("ATMAN_ADMIN_DATABASE_URL"):
        return _replace_db(url)
    return _test_db_url()


# ── fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def skills_db():
    """Apply migrations 0004 + 0015 to atman_test and yield admin + app URLs.

    Skips gracefully when no test DB or required prerequisite migrations
    are missing — the test must not block the rest of the suite.
    """
    import psycopg

    admin_url = _admin_db_url()
    app_url = _test_db_url()
    if admin_url is None or app_url is None:
        pytest.skip(
            "No test DB URL (set TEST_DATABASE_URL / TEST_ADMIN_DATABASE_URL or "
            "DATABASE_URL / ATMAN_ADMIN_DATABASE_URL)"
        )

    migrations_dir = Path(__file__).parents[2] / "migrations" / "versions"
    agent_sql = (migrations_dir / "0004_agent_schema.sql").read_text()
    skills_sql = (migrations_dir / "0015_skills.sql").read_text()

    try:
        with psycopg.connect(admin_url) as conn:
            with conn.cursor() as cur:
                cur.execute(cast(Any, agent_sql))
                cur.execute(cast(Any, skills_sql))
            conn.commit()
    except Exception as exc:
        pytest.skip(f"Migration apply failed: {exc}")

    yield {"admin_url": admin_url, "app_url": app_url}


@pytest.fixture(scope="function")
def manager(skills_db, tmp_path: Path):
    """Build a real SkillManager backed by PostgresSkillStore.

    Inserts a fresh public.agents row for each test so the FK / RLS path
    is exercised.
    """
    import psycopg

    from atman.skills.manager import SkillManager
    from atman.skills.postgres_store import PostgresSkillStore
    from atman.skills.projection import PydanticAgentProjector
    from atman.skills.retriever import SkillRetriever

    agent_id = uuid4()
    with psycopg.connect(skills_db["admin_url"]) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO public.agents (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
                [agent_id, f"e2e-{agent_id}"],
            )
        conn.commit()

    store = PostgresSkillStore(db_url=skills_db["app_url"], agent_id=agent_id)
    retriever = SkillRetriever(store=store, embedding=None)
    mgr = SkillManager(
        store=store,
        retriever=retriever,
        projector=PydanticAgentProjector(),
        config=SkillsSettings(),
        agents_root=tmp_path / "agents",
    )

    yield mgr, agent_id

    # Clean up rows for this agent so re-runs don't accumulate.
    with psycopg.connect(skills_db["admin_url"]) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM public.skill_invocations WHERE agent_id = %s", [agent_id])
            cur.execute("DELETE FROM public.skills WHERE agent_id = %s", [agent_id])
            cur.execute("DELETE FROM public.agents WHERE id = %s", [agent_id])
        conn.commit()


# ── tests ─────────────────────────────────────────────────────────────────


@pytest.mark.integration
def test_capture_invoke_mark_reflect_cycle(manager) -> None:
    """capture → activate → invoke → mark_result → process_session_skills."""
    from atman.skills.models import SkillStatus

    mgr, agent_id = manager
    session_id = uuid4()

    # 1. Capture creates an in-session draft on disk + a row in the store.
    skill = mgr.capture(
        name="e2e-helper",
        description="An E2E helper skill",
        agent_id=agent_id,
        session_id=session_id,
        instructions="Do the thing well.",
    )
    assert skill.status == SkillStatus.draft
    assert skill.manifest_path.exists()

    # The PostgresSkillStore row should be retrievable by id.
    persisted = mgr._store.get_skill_by_id(skill.id)
    assert persisted is not None
    assert persisted.name == "e2e-helper"
    assert persisted.origin.value == "in_session"

    # 2. Promote to active so invoke proceeds (draft skills cannot be
    #    promoted to pinned via list_pinned, but invoke does not require
    #    that — the status check only refuses 'disabled').
    mgr._store.update_skill_status(skill.id, SkillStatus.active)

    # 3. Invoke — manifest has no runtime_entry, so we get 'executed_unknown'.
    invocation_id = mgr.invoke(skill.id, args={"x": 1}, agent_id=agent_id, session_id=session_id)
    assert isinstance(invocation_id, UUID)

    # 4. Agent records 'helped' marker.
    mgr.mark_result(invocation_id, "helped", note="great")

    # 5. Process via micro-reflection hook — must finalise the invocation,
    #    bump success_count, and mark processed_at.
    mgr.process_session_skills(agent_id, session_id)

    refreshed = mgr._store.get_skill_by_id(skill.id)
    assert refreshed is not None
    assert refreshed.invocations_count >= 1
    assert refreshed.success_count >= 1

    # No more unprocessed invocations after the hook ran.
    remaining = mgr._store.get_unprocessed_invocations(agent_id, session_id)
    assert remaining == []


@pytest.mark.integration
def test_session_skills_marker_writes_json(manager, tmp_path: Path) -> None:
    """Session-end marker JSON (HLE-35) reflects the live invocations."""
    import json

    mgr, agent_id = manager
    session_id = uuid4()

    skill = mgr.capture(
        name="e2e-marker",
        description="marker test",
        agent_id=agent_id,
        session_id=session_id,
        instructions="x",
    )
    from atman.skills.models import SkillStatus

    mgr._store.update_skill_status(skill.id, SkillStatus.active)
    inv = mgr.invoke(skill.id, args={}, agent_id=agent_id, session_id=session_id)
    mgr.mark_result(inv, "helped")

    workspace = tmp_path / "ws"
    workspace.mkdir()
    path = mgr.write_session_skills_marker(workspace, session_id, agent_id)
    assert path is not None and path.exists()

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["session_id"] == str(session_id)
    assert payload["total_invocations"] >= 1
    by_name = {e["skill_name"]: e for e in payload["skills_used"]}
    assert "e2e-marker" in by_name
