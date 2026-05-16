"""Tests for SkillManager — invoke, mark_result, capture, process_session_skills."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from atman.config import SkillsSettings
from atman.skills.in_memory_store import InMemorySkillStore
from atman.skills.manager import SkillManager
from atman.skills.models import Skill, SkillKind, SkillOrigin, SkillStatus
from atman.skills.projection import PydanticAgentProjector
from atman.skills.retriever import SkillRetriever


def _now():
    return datetime.now(timezone.utc)


def _make_active_skill(store: InMemorySkillStore, agent_id, name: str, tmp_path: Path) -> Skill:
    from atman.skills.manifest import SkillManifest, write_skill_md

    skill_root = tmp_path / name
    skill_root.mkdir(exist_ok=True)
    manifest_path = skill_root / "SKILL.md"
    write_skill_md(SkillManifest(name=name, description=f"Skill {name}."), manifest_path)

    now = _now()
    skill = Skill(
        id=uuid4(),
        agent_id=agent_id,
        entity_id=uuid4(),
        name=name,
        description=f"Skill {name}.",
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
        skill_root=skill_root,
        manifest_path=manifest_path,
        created_at=now,
        updated_at=now,
    )
    store.save_skill(skill)
    return skill


def _make_manager(store, tmp_path) -> SkillManager:
    retriever = SkillRetriever(store=store, embedding=None)
    return SkillManager(
        store=store,
        retriever=retriever,
        projector=PydanticAgentProjector(),
        config=SkillsSettings(),
        agents_root=tmp_path,
    )


class TestSkillManagerInvoke:
    def setup_method(self):
        self.agent_id = uuid4()
        self.session_id = uuid4()

    def test_invoke_creates_invocation(self, tmp_path):
        store = InMemorySkillStore()
        skill = _make_active_skill(store, self.agent_id, "test-skill", tmp_path)
        manager = _make_manager(store, tmp_path)

        inv_id = manager.invoke(skill.id, {}, self.agent_id, self.session_id)
        assert inv_id is not None

        # invocation should be recorded
        invs = store.get_unprocessed_invocations(self.agent_id, self.session_id)
        assert len(invs) == 1

    def test_invoke_missing_skill_raises(self, tmp_path):
        store = InMemorySkillStore()
        manager = _make_manager(store, tmp_path)

        with pytest.raises(ValueError, match="not found"):
            manager.invoke(uuid4(), {}, self.agent_id, self.session_id)

    def test_invoke_disabled_skill_raises(self, tmp_path):
        store = InMemorySkillStore()
        skill = _make_active_skill(store, self.agent_id, "disabled-skill", tmp_path)
        store.update_skill_status(skill.id, SkillStatus.disabled)
        manager = _make_manager(store, tmp_path)

        with pytest.raises(ValueError, match="disabled"):
            manager.invoke(skill.id, {}, self.agent_id, self.session_id)

    def test_invoke_tracks_in_session(self, tmp_path):
        store = InMemorySkillStore()
        skill = _make_active_skill(store, self.agent_id, "tracked", tmp_path)
        manager = _make_manager(store, tmp_path)

        manager.invoke(skill.id, {}, self.agent_id, self.session_id)

        available = manager.list_available(self.agent_id, self.session_id)
        names = [s.name for s in available]
        assert "tracked" in names


class TestSkillManagerMarkResult:
    def setup_method(self):
        self.agent_id = uuid4()
        self.session_id = uuid4()

    def test_mark_result_helped(self, tmp_path):
        store = InMemorySkillStore()
        skill = _make_active_skill(store, self.agent_id, "s1", tmp_path)
        manager = _make_manager(store, tmp_path)
        inv_id = manager.invoke(skill.id, {}, self.agent_id, self.session_id)
        manager.mark_result(inv_id, "helped", "worked perfectly")
        inv = store._invocations[inv_id]
        assert inv.agent_marker == "helped"
        assert inv.agent_marker_note == "worked perfectly"

    def test_mark_result_invalid_status_raises(self, tmp_path):
        store = InMemorySkillStore()
        manager = _make_manager(store, tmp_path)
        with pytest.raises(ValueError, match="status must be one of"):
            manager.mark_result(uuid4(), "great")  # invalid


class TestSkillManagerCapture:
    def setup_method(self):
        self.agent_id = uuid4()
        self.session_id = uuid4()

    def test_capture_creates_draft_skill(self, tmp_path):
        store = InMemorySkillStore()
        manager = _make_manager(store, tmp_path)

        skill = manager.capture(
            name="my-automation",
            description="Automates something.",
            agent_id=self.agent_id,
            session_id=self.session_id,
            instructions="Step 1: do this. Step 2: do that.",
        )

        assert skill.name == "my-automation"
        assert skill.status == SkillStatus.draft
        assert skill.origin == SkillOrigin.in_session
        assert skill.manifest_path.exists()

        # Persisted in store
        found = store.get_skill_by_name(self.agent_id, "my-automation")
        assert found is not None

    def test_capture_writes_skill_md(self, tmp_path):
        store = InMemorySkillStore()
        manager = _make_manager(store, tmp_path)

        skill = manager.capture(
            name="parse-csv",
            description="Parses CSV files.",
            agent_id=self.agent_id,
            session_id=self.session_id,
        )

        from atman.skills.manifest import parse_skill_md
        manifest = parse_skill_md(skill.manifest_path)
        assert manifest.name == "parse-csv"
        assert "Parses CSV" in manifest.description

    def test_capture_invalid_name_raises(self, tmp_path):
        store = InMemorySkillStore()
        manager = _make_manager(store, tmp_path)

        with pytest.raises(ValueError, match="kebab-case"):
            manager.capture(
                name="invalid name!",
                description="Bad name.",
                agent_id=self.agent_id,
                session_id=self.session_id,
            )


class TestProcessSessionSkills:
    def setup_method(self):
        self.agent_id = uuid4()
        self.session_id = uuid4()

    def test_helped_increments_success(self, tmp_path):
        store = InMemorySkillStore()
        skill = _make_active_skill(store, self.agent_id, "s1", tmp_path)
        manager = _make_manager(store, tmp_path)

        inv_id = manager.invoke(skill.id, {}, self.agent_id, self.session_id)
        manager.mark_result(inv_id, "helped")
        manager.process_session_skills(self.agent_id, self.session_id)

        updated = store.get_skill_by_id(skill.id)
        assert updated is not None
        assert updated.success_count == 1
        assert updated.failure_count == 0

    def test_didnt_help_increments_failure_and_flags_revision(self, tmp_path):
        store = InMemorySkillStore()
        skill = _make_active_skill(store, self.agent_id, "s2", tmp_path)
        manager = _make_manager(store, tmp_path)

        inv_id = manager.invoke(skill.id, {}, self.agent_id, self.session_id)
        manager.mark_result(inv_id, "didnt_help")
        manager.process_session_skills(self.agent_id, self.session_id)

        updated = store.get_skill_by_id(skill.id)
        assert updated is not None
        assert updated.failure_count == 1
        assert updated.revision_needed is True

    def test_unclear_no_stat_change(self, tmp_path):
        store = InMemorySkillStore()
        skill = _make_active_skill(store, self.agent_id, "s3", tmp_path)
        manager = _make_manager(store, tmp_path)

        inv_id = manager.invoke(skill.id, {}, self.agent_id, self.session_id)
        manager.mark_result(inv_id, "unclear")
        manager.process_session_skills(self.agent_id, self.session_id)

        updated = store.get_skill_by_id(skill.id)
        assert updated is not None
        assert updated.success_count == 0
        assert updated.failure_count == 0
        assert updated.revision_needed is False

    def test_marks_invocations_processed(self, tmp_path):
        store = InMemorySkillStore()
        skill = _make_active_skill(store, self.agent_id, "s4", tmp_path)
        manager = _make_manager(store, tmp_path)

        manager.invoke(skill.id, {}, self.agent_id, self.session_id)
        manager.process_session_skills(self.agent_id, self.session_id)

        remaining = store.get_unprocessed_invocations(self.agent_id, self.session_id)
        assert remaining == []

    def test_exit_code_fallback_ok(self, tmp_path):
        store = InMemorySkillStore()
        skill = _make_active_skill(store, self.agent_id, "s5", tmp_path)
        manager = _make_manager(store, tmp_path)

        inv_id = manager.invoke(skill.id, {}, self.agent_id, self.session_id)
        # Simulate exit code 0 (no agent marker)
        store.set_preliminary_status(inv_id, "executed_ok", exit_code=0)
        manager.process_session_skills(self.agent_id, self.session_id)

        updated = store.get_skill_by_id(skill.id)
        assert updated is not None
        assert updated.success_count == 1

    def test_auto_pin_after_threshold(self, tmp_path):
        config = SkillsSettings(auto_pin_threshold_uses=2)
        store = InMemorySkillStore()
        skill = _make_active_skill(store, self.agent_id, "frequent", tmp_path)
        retriever = SkillRetriever(store=store, embedding=None)
        manager = SkillManager(
            store=store,
            retriever=retriever,
            projector=PydanticAgentProjector(),
            config=config,
            agents_root=tmp_path,
        )

        # Two separate invocations (simulating 2 sessions)
        for _ in range(2):
            sid = uuid4()
            inv_id = manager.invoke(skill.id, {}, self.agent_id, sid)
            manager.mark_result(inv_id, "helped")
            manager.process_session_skills(self.agent_id, sid)

        updated = store.get_skill_by_id(skill.id)
        assert updated is not None
        assert updated.auto_pinned is True

    def test_no_invocations_is_noop(self, tmp_path):
        store = InMemorySkillStore()
        manager = _make_manager(store, tmp_path)
        # Should not raise
        manager.process_session_skills(self.agent_id, self.session_id)
