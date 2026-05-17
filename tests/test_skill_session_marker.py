"""HLE-35 — session-end skill marker JSON written by SkillManager."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from atman.config import SkillsSettings
from atman.skills.in_memory_store import InMemorySkillStore
from atman.skills.manager import SkillManager
from atman.skills.models import Skill, SkillKind, SkillOrigin, SkillStatus
from atman.skills.noop import NoopSkillManager
from atman.skills.projection import PydanticAgentProjector
from atman.skills.retriever import SkillRetriever


def _now() -> datetime:
    return datetime.now(UTC)


def _make_skill(agent_id: UUID, name: str, manifest_path: Path) -> Skill:
    now = _now()
    return Skill(
        id=uuid4(),
        agent_id=agent_id,
        entity_id=uuid4(),
        name=name,
        description=f"{name} description",
        version="0.1.0",
        kind=SkillKind.active,
        status=SkillStatus.active,
        origin=SkillOrigin.in_session,
        core=False,
        session_scoped=False,
        user_pinned=False,
        auto_pinned=False,
        invocations_count=0,
        success_count=0,
        failure_count=0,
        last_used_at=None,
        sessions_since_use=0,
        revision_needed=False,
        revision_priority=0,
        last_revised_at=None,
        manifest_inferred=False,
        skill_root=manifest_path.parent,
        manifest_path=manifest_path,
        created_at=now,
        updated_at=now,
    )


def _make_manager(tmp_path: Path) -> SkillManager:
    store = InMemorySkillStore()
    retriever = SkillRetriever(store=store, embedding=None)
    return SkillManager(
        store=store,
        retriever=retriever,
        projector=PydanticAgentProjector(),
        config=SkillsSettings(),
        agents_root=tmp_path / "agents",
    )


def test_marker_written_with_skill_summary(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    manager = _make_manager(tmp_path)
    agent_id, session_id = uuid4(), uuid4()

    # Two skills with multiple invocations each
    skill_a = _make_skill(agent_id, "skill-a", tmp_path / "a" / "SKILL.md")
    skill_b = _make_skill(agent_id, "skill-b", tmp_path / "b" / "SKILL.md")
    skill_a.manifest_path.parent.mkdir(parents=True)
    skill_b.manifest_path.parent.mkdir(parents=True)
    manager._store.save_skill(skill_a)
    manager._store.save_skill(skill_b)

    inv1 = manager._store.create_invocation(skill_a.id, agent_id, session_id)
    inv2 = manager._store.create_invocation(skill_a.id, agent_id, session_id)
    inv3 = manager._store.create_invocation(skill_b.id, agent_id, session_id)

    manager._store.set_preliminary_status(inv1, "executed_ok")
    manager._store.set_preliminary_status(inv2, "executed_ok")
    manager._store.set_preliminary_status(inv3, "executed_fail")
    manager._store.write_agent_marker(inv1, "helped", None)

    path = manager.write_session_skills_marker(workspace, session_id, agent_id)
    assert path is not None
    assert path.exists()
    assert path.name.startswith("atman_session_skills_")
    assert path.name.endswith(".json")

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["session_id"] == str(session_id)
    assert payload["agent_id"] == str(agent_id)
    assert payload["total_invocations"] == 3
    assert "timestamp" in payload

    # skill-a (2 invocations) sorts before skill-b (1 invocation)
    by_name = {e["skill_name"]: e for e in payload["skills_used"]}
    assert payload["skills_used"][0]["skill_name"] == "skill-a"
    assert by_name["skill-a"]["invocations"] == 2
    assert by_name["skill-a"]["preliminary_status"] == "executed_ok"
    assert by_name["skill-a"]["agent_marker"] == "helped"
    assert by_name["skill-b"]["invocations"] == 1
    assert by_name["skill-b"]["preliminary_status"] == "executed_fail"


def test_marker_returns_none_when_no_invocations(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    manager = _make_manager(tmp_path)

    result = manager.write_session_skills_marker(workspace, uuid4(), uuid4())
    assert result is None
    assert list(workspace.iterdir()) == []


def test_marker_handles_missing_skill_row(tmp_path: Path) -> None:
    """Skill row deleted between invocation and marker write — name=None."""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    manager = _make_manager(tmp_path)
    agent_id, session_id = uuid4(), uuid4()

    skill = _make_skill(agent_id, "ghost", tmp_path / "g" / "SKILL.md")
    skill.manifest_path.parent.mkdir(parents=True)
    manager._store.save_skill(skill)
    manager._store.create_invocation(skill.id, agent_id, session_id)
    del manager._store._skills[skill.id]

    path = manager.write_session_skills_marker(workspace, session_id, agent_id)
    assert path is not None
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["skills_used"][0]["skill_name"] is None
    assert payload["skills_used"][0]["skill_id"] == str(skill.id)


def test_marker_creates_workspace_if_missing(tmp_path: Path) -> None:
    workspace = tmp_path / "nested" / "ws"
    manager = _make_manager(tmp_path)
    agent_id, session_id = uuid4(), uuid4()

    skill = _make_skill(agent_id, "s", tmp_path / "s" / "SKILL.md")
    skill.manifest_path.parent.mkdir(parents=True)
    manager._store.save_skill(skill)
    manager._store.create_invocation(skill.id, agent_id, session_id)

    path = manager.write_session_skills_marker(workspace, session_id, agent_id)
    assert path is not None
    assert workspace.exists()
    assert path.parent == workspace


def test_noop_marker_returns_none(tmp_path: Path) -> None:
    noop = NoopSkillManager()
    assert noop.write_session_skills_marker(tmp_path, uuid4(), uuid4()) is None
    # Must not create any file in the workspace
    assert not any(tmp_path.iterdir())


def test_marker_satisfies_port_protocol() -> None:
    from atman.skills.port import SkillManagerPort

    assert isinstance(NoopSkillManager(), SkillManagerPort)
