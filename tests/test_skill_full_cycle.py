"""HLE-39 — full skill-loop cycle against InMemorySkillStore.

The Postgres-backed counterpart lives in tests/integration/test_skill_e2e.py
and only runs when a test DB is configured. This in-memory test covers the
same cycle so the loop is verified end-to-end on every CI run without
requiring external services (per AGENTS.md "no external services
required").
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from atman.config import SkillsSettings
from atman.skills.in_memory_store import InMemorySkillStore
from atman.skills.manager import SkillManager
from atman.skills.models import SkillStatus
from atman.skills.projection import PydanticAgentProjector
from atman.skills.retriever import SkillRetriever


def _make_manager(tmp_path: Path) -> SkillManager:
    store = InMemorySkillStore()
    return SkillManager(
        store=store,
        retriever=SkillRetriever(store=store, embedding=None),
        projector=PydanticAgentProjector(),
        config=SkillsSettings(),
        agents_root=tmp_path / "agents",
    )


def test_full_cycle_capture_invoke_mark_reflect(tmp_path: Path) -> None:
    mgr = _make_manager(tmp_path)
    agent_id, session_id = uuid4(), uuid4()

    # 1. Capture
    skill = mgr.capture(
        name="full-cycle",
        description="full cycle skill",
        agent_id=agent_id,
        session_id=session_id,
        instructions="do it",
    )
    assert skill.status == SkillStatus.draft

    # 2. Activate (capture lands in draft; activation is a separate step)
    mgr._store.update_skill_status(skill.id, SkillStatus.active)

    # 3. Invoke
    invocation_id = mgr.invoke(skill.id, args={}, agent_id=agent_id, session_id=session_id)
    assert isinstance(invocation_id, UUID)

    # 4. Mark result
    mgr.mark_result(invocation_id, "helped", note="worked great")

    # 5. Micro-reflection hook finalises the invocation + bumps stats
    mgr.process_session_skills(agent_id, session_id)

    refreshed = mgr._store.get_skill_by_id(skill.id)
    assert refreshed is not None
    assert refreshed.invocations_count == 1
    assert refreshed.success_count == 1
    assert refreshed.failure_count == 0

    # No unprocessed invocations remain
    remaining = mgr._store.get_unprocessed_invocations(agent_id, session_id)
    assert remaining == []


def test_full_cycle_failure_path_flags_revision(tmp_path: Path) -> None:
    mgr = _make_manager(tmp_path)
    agent_id, session_id = uuid4(), uuid4()

    skill = mgr.capture(
        name="failing",
        description="x",
        agent_id=agent_id,
        session_id=session_id,
    )
    mgr._store.update_skill_status(skill.id, SkillStatus.active)
    inv = mgr.invoke(skill.id, args={}, agent_id=agent_id, session_id=session_id)
    mgr.mark_result(inv, "didnt_help", note="missed the mark")
    mgr.process_session_skills(agent_id, session_id)

    refreshed = mgr._store.get_skill_by_id(skill.id)
    assert refreshed is not None
    assert refreshed.failure_count == 1
    assert refreshed.revision_needed is True
    assert refreshed.revision_priority >= 1


def test_full_cycle_session_marker_then_processing(tmp_path: Path) -> None:
    """Marker is written BEFORE process_session_skills, capturing live invocations."""
    import json

    mgr = _make_manager(tmp_path)
    agent_id, session_id = uuid4(), uuid4()

    skill = mgr.capture(
        name="marker-cycle",
        description="x",
        agent_id=agent_id,
        session_id=session_id,
    )
    mgr._store.update_skill_status(skill.id, SkillStatus.active)
    mgr.invoke(skill.id, args={}, agent_id=agent_id, session_id=session_id)

    workspace = tmp_path / "ws"
    workspace.mkdir()
    path = mgr.write_session_skills_marker(workspace, session_id, agent_id)
    assert path is not None
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["total_invocations"] == 1

    mgr.process_session_skills(agent_id, session_id)
    # After processing, the marker file should still be on disk
    # (markers are append-only, never deleted by process_session_skills).
    assert path.exists()


def test_full_cycle_daily_hook_after_failure_path(tmp_path: Path) -> None:
    """Failure path + daily hook surfaces the skill in high-priority list."""
    mgr = _make_manager(tmp_path)
    agent_id, session_id = uuid4(), uuid4()

    skill = mgr.capture(name="problem", description="x", agent_id=agent_id, session_id=session_id)
    mgr._store.update_skill_status(skill.id, SkillStatus.active)
    inv = mgr.invoke(skill.id, args={}, agent_id=agent_id, session_id=session_id)
    mgr.mark_result(inv, "didnt_help")
    mgr.process_session_skills(agent_id, session_id)

    # First daily run — priority is at 1 so not yet high
    summary = mgr.process_daily_skills(agent_id)
    assert summary.revision_needed_count == 1
    assert summary.high_priority_revisions == []

    # Simulate three more failed cycles bumping priority
    for _ in range(3):
        inv = mgr.invoke(skill.id, args={}, agent_id=agent_id, session_id=session_id)
        mgr.mark_result(inv, "didnt_help")
        mgr.process_session_skills(agent_id, session_id)

    summary = mgr.process_daily_skills(agent_id)
    assert "problem" in summary.high_priority_revisions
