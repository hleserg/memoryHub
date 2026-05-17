"""Tests for InMemorySkillStore — all store operations."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from atman.skills.in_memory_store import InMemorySkillStore
from atman.skills.models import Skill, SkillKind, SkillOrigin, SkillStatus


def _now() -> datetime:
    return datetime.now(UTC)


def _make_skill(
    agent_id=None,
    name="test-skill",
    status=SkillStatus.active,
    user_pinned=False,
    auto_pinned=False,
) -> Skill:
    now = _now()
    return Skill(
        id=uuid4(),
        agent_id=agent_id or uuid4(),
        entity_id=uuid4(),
        name=name,
        description="Test skill.",
        version="0.1.0",
        kind=SkillKind.active,
        status=status,
        origin=SkillOrigin.in_session,
        core=False,
        session_scoped=False,
        user_pinned=user_pinned,
        auto_pinned=auto_pinned,
        invocations_count=0,
        success_count=0,
        failure_count=0,
        last_used_at=None,
        sessions_since_use=0,
        revision_needed=False,
        revision_priority=0,
        last_revised_at=None,
        manifest_inferred=False,
        skill_root=Path(f"/tmp/skills/{name}"),
        manifest_path=Path(f"/tmp/skills/{name}/SKILL.md"),
        created_at=now,
        updated_at=now,
    )


class TestInMemorySkillStore:
    def setup_method(self):
        self.store = InMemorySkillStore()
        self.agent_id = uuid4()

    def test_save_and_get_by_name(self):
        skill = _make_skill(agent_id=self.agent_id)
        self.store.save_skill(skill)
        found = self.store.get_skill_by_name(self.agent_id, skill.name)
        assert found is not None
        assert found.name == skill.name

    def test_get_by_id(self):
        skill = _make_skill(agent_id=self.agent_id)
        self.store.save_skill(skill)
        assert self.store.get_skill_by_id(skill.id) is not None

    def test_get_missing_returns_none(self):
        assert self.store.get_skill_by_name(uuid4(), "nonexistent") is None

    def test_list_pinned_user(self):
        pinned = _make_skill(agent_id=self.agent_id, name="pinned", user_pinned=True)
        unpinned = _make_skill(agent_id=self.agent_id, name="unpinned")
        self.store.save_skill(pinned)
        self.store.save_skill(unpinned)
        result = self.store.list_pinned(self.agent_id)
        assert len(result) == 1
        assert result[0].name == "pinned"

    def test_list_pinned_auto(self):
        pinned = _make_skill(agent_id=self.agent_id, name="auto", auto_pinned=True)
        self.store.save_skill(pinned)
        assert len(self.store.list_pinned(self.agent_id)) == 1

    def test_list_pinned_disabled_excluded(self):
        pinned = _make_skill(
            agent_id=self.agent_id,
            name="pinned",
            user_pinned=True,
            status=SkillStatus.disabled,
        )
        self.store.save_skill(pinned)
        assert self.store.list_pinned(self.agent_id) == []

    def test_list_active_on_demand(self):
        pinned = _make_skill(agent_id=self.agent_id, name="pinned", auto_pinned=True)
        on_demand = _make_skill(agent_id=self.agent_id, name="on-demand")
        self.store.save_skill(pinned)
        self.store.save_skill(on_demand)
        result = self.store.list_active_on_demand(self.agent_id)
        assert len(result) == 1
        assert result[0].name == "on-demand"

    def test_update_status(self):
        skill = _make_skill(agent_id=self.agent_id)
        self.store.save_skill(skill)
        self.store.update_skill_status(skill.id, SkillStatus.disabled)
        updated = self.store.get_skill_by_id(skill.id)
        assert updated is not None
        assert updated.status == SkillStatus.disabled

    def test_update_pinning(self):
        skill = _make_skill(agent_id=self.agent_id)
        self.store.save_skill(skill)
        self.store.update_pinning(skill.id, user_pinned=True)
        updated = self.store.get_skill_by_id(skill.id)
        assert updated is not None
        assert updated.user_pinned is True

    def test_update_stats_success(self):
        skill = _make_skill(agent_id=self.agent_id)
        self.store.save_skill(skill)
        self.store.update_stats(skill.id, success_delta=1)
        updated = self.store.get_skill_by_id(skill.id)
        assert updated is not None
        assert updated.success_count == 1

    def test_update_stats_failure(self):
        skill = _make_skill(agent_id=self.agent_id)
        self.store.save_skill(skill)
        self.store.update_stats(skill.id, failure_delta=2)
        updated = self.store.get_skill_by_id(skill.id)
        assert updated is not None
        assert updated.failure_count == 2

    def test_bump_sessions_since_use(self):
        pinned = _make_skill(agent_id=self.agent_id, name="pinned", user_pinned=True)
        self.store.save_skill(pinned)
        # exclude nothing → should bump
        self.store.bump_sessions_since_use(self.agent_id, exclude_skill_ids=set())
        updated = self.store.get_skill_by_id(pinned.id)
        assert updated is not None
        assert updated.sessions_since_use == 1

    def test_bump_sessions_since_use_excludes(self):
        pinned = _make_skill(agent_id=self.agent_id, name="pinned", user_pinned=True)
        self.store.save_skill(pinned)
        # exclude this skill → sessions_since_use stays 0
        self.store.bump_sessions_since_use(self.agent_id, exclude_skill_ids={pinned.id})
        updated = self.store.get_skill_by_id(pinned.id)
        assert updated is not None
        assert updated.sessions_since_use == 0

    def test_bump_sessions_since_use_covers_unpinned_active(self):
        """Devin Review ANALYSIS_..._0004: the counter must keep advancing
        for auto-downgraded (now unpinned, still active) skills so deep-
        reflection archive thresholds are actually reachable.
        """
        from atman.skills.models import SkillStatus

        unpinned = _make_skill(
            agent_id=self.agent_id,
            name="unpinned-active",
            user_pinned=False,
        )
        self.store.save_skill(unpinned)
        self.store.bump_sessions_since_use(self.agent_id, exclude_skill_ids=set())

        updated = self.store.get_skill_by_id(unpinned.id)
        assert updated is not None
        assert updated.sessions_since_use == 1
        assert updated.status == SkillStatus.active

    def test_bump_sessions_since_use_skips_non_active_status(self):
        """Disabled and draft skills aren't reachable, so tracking their
        idleness is noise — they must NOT be bumped.
        """
        from atman.skills.models import SkillStatus

        disabled = _make_skill(agent_id=self.agent_id, name="disabled-skill", user_pinned=False)
        draft = _make_skill(agent_id=self.agent_id, name="draft-skill", user_pinned=False)
        self.store.save_skill(disabled)
        self.store.save_skill(draft)
        self.store.update_skill_status(disabled.id, SkillStatus.disabled)
        self.store.update_skill_status(draft.id, SkillStatus.draft)

        self.store.bump_sessions_since_use(self.agent_id, exclude_skill_ids=set())

        for sid in (disabled.id, draft.id):
            after = self.store.get_skill_by_id(sid)
            assert after is not None
            assert after.sessions_since_use == 0

    def test_set_revision_needed(self):
        skill = _make_skill(agent_id=self.agent_id)
        self.store.save_skill(skill)
        self.store.set_revision_needed(skill.id, priority_bump=3)
        updated = self.store.get_skill_by_id(skill.id)
        assert updated is not None
        assert updated.revision_needed is True
        assert updated.revision_priority == 3

    def test_create_invocation(self):
        skill = _make_skill(agent_id=self.agent_id)
        self.store.save_skill(skill)
        session_id = uuid4()
        inv_id = self.store.create_invocation(skill.id, self.agent_id, session_id)
        # invocations_count should be incremented on skill
        updated_skill = self.store.get_skill_by_id(skill.id)
        assert updated_skill is not None
        assert updated_skill.invocations_count == 1
        assert updated_skill.sessions_since_use == 0
        assert updated_skill.last_used_at is not None
        assert inv_id is not None

    def test_write_agent_marker(self):
        skill = _make_skill(agent_id=self.agent_id)
        self.store.save_skill(skill)
        inv_id = self.store.create_invocation(skill.id, self.agent_id, uuid4())
        self.store.write_agent_marker(inv_id, "helped", "worked great")
        invocations = self.store.get_unprocessed_invocations(
            self.agent_id, self.store._invocations[inv_id].session_id
        )
        assert invocations[0].agent_marker == "helped"
        assert invocations[0].agent_marker_note == "worked great"

    def test_set_preliminary_status(self):
        skill = _make_skill(agent_id=self.agent_id)
        self.store.save_skill(skill)
        session_id = uuid4()
        inv_id = self.store.create_invocation(skill.id, self.agent_id, session_id)
        self.store.set_preliminary_status(inv_id, "executed_ok", exit_code=0)
        inv = self.store._invocations[inv_id]
        assert inv.preliminary_status == "executed_ok"
        assert inv.exit_code == 0

    def test_get_unprocessed_invocations(self):
        skill = _make_skill(agent_id=self.agent_id)
        self.store.save_skill(skill)
        session_id = uuid4()
        inv_id = self.store.create_invocation(skill.id, self.agent_id, session_id)
        invs = self.store.get_unprocessed_invocations(self.agent_id, session_id)
        assert len(invs) == 1
        assert invs[0].id == inv_id

    def test_mark_processed_removes_from_unprocessed(self):
        skill = _make_skill(agent_id=self.agent_id)
        self.store.save_skill(skill)
        session_id = uuid4()
        inv_id = self.store.create_invocation(skill.id, self.agent_id, session_id)
        self.store.mark_processed(inv_id)
        invs = self.store.get_unprocessed_invocations(self.agent_id, session_id)
        assert invs == []

    def test_set_final_status(self):
        skill = _make_skill(agent_id=self.agent_id)
        self.store.save_skill(skill)
        inv_id = self.store.create_invocation(skill.id, self.agent_id, uuid4())
        self.store.set_final_status(inv_id, "helped")
        inv = self.store._invocations[inv_id]
        assert inv.final_status == "helped"
