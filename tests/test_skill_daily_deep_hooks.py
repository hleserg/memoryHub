"""HLE-36 — Daily/Deep reflection hooks for the skill loop."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from atman.config import SkillsSettings
from atman.skills.in_memory_store import InMemorySkillStore
from atman.skills.manager import SkillManager
from atman.skills.models import (
    DailySkillSummary,
    DeepSkillSummary,
    Skill,
    SkillKind,
    SkillOrigin,
    SkillStatus,
)
from atman.skills.noop import NoopSkillManager
from atman.skills.projection import PydanticAgentProjector
from atman.skills.retriever import SkillRetriever


def _now() -> datetime:
    return datetime.now(UTC)


def _make_skill(
    agent_id: UUID,
    name: str,
    *,
    revision_needed: bool = False,
    revision_priority: int = 0,
    sessions_since_use: int = 0,
    invocations_count: int = 0,
    failure_count: int = 0,
    user_pinned: bool = False,
    status: SkillStatus = SkillStatus.active,
) -> Skill:
    now = _now()
    return Skill(
        id=uuid4(),
        agent_id=agent_id,
        entity_id=uuid4(),
        name=name,
        description=f"{name}",
        version="0.1.0",
        kind=SkillKind.active,
        status=status,
        origin=SkillOrigin.in_session,
        core=False,
        session_scoped=False,
        user_pinned=user_pinned,
        auto_pinned=False,
        invocations_count=invocations_count,
        success_count=max(0, invocations_count - failure_count),
        failure_count=failure_count,
        last_used_at=None,
        sessions_since_use=sessions_since_use,
        revision_needed=revision_needed,
        revision_priority=revision_priority,
        last_revised_at=None,
        manifest_inferred=False,
        skill_root=Path(f"/tmp/{name}"),
        manifest_path=Path(f"/tmp/{name}/SKILL.md"),
        created_at=now,
        updated_at=now,
    )


def _make_manager(tmp_path: Path, **settings_overrides) -> SkillManager:
    store = InMemorySkillStore()
    retriever = SkillRetriever(store=store, embedding=None)
    return SkillManager(
        store=store,
        retriever=retriever,
        projector=PydanticAgentProjector(),
        config=SkillsSettings(**settings_overrides),
        agents_root=tmp_path / "agents",
    )


# ── process_daily_skills ──────────────────────────────────────────────────


class TestProcessDailySkills:
    def test_no_pending_returns_empty_summary(self, tmp_path: Path) -> None:
        manager = _make_manager(tmp_path)
        summary = manager.process_daily_skills(uuid4())

        assert isinstance(summary, DailySkillSummary)
        assert summary.revision_needed_count == 0
        assert summary.revision_priority_bumped == 0
        assert summary.high_priority_revisions == []

    def test_bumps_priority_for_idle_revision_pending(self, tmp_path: Path) -> None:
        manager = _make_manager(tmp_path, daily_revision_idle_bump_sessions=5)
        agent_id = uuid4()

        # Idle 7 sessions → should be bumped
        idle = _make_skill(
            agent_id, "idle", revision_needed=True, sessions_since_use=7, revision_priority=1
        )
        # Idle 2 sessions → should NOT be bumped
        active = _make_skill(
            agent_id, "active", revision_needed=True, sessions_since_use=2, revision_priority=1
        )
        manager._store.save_skill(idle)
        manager._store.save_skill(active)

        summary = manager.process_daily_skills(agent_id)

        assert summary.revision_needed_count == 2
        assert summary.revision_priority_bumped == 1

        # 'idle' priority went up; 'active' did not
        refreshed_idle = manager._store.get_skill_by_id(idle.id)
        refreshed_active = manager._store.get_skill_by_id(active.id)
        assert refreshed_idle is not None and refreshed_idle.revision_priority == 2
        assert refreshed_active is not None and refreshed_active.revision_priority == 1

    def test_high_priority_threshold_lifted(self, tmp_path: Path) -> None:
        manager = _make_manager(tmp_path)
        agent_id = uuid4()

        manager._store.save_skill(
            _make_skill(agent_id, "high-1", revision_needed=True, revision_priority=3)
        )
        manager._store.save_skill(
            _make_skill(agent_id, "high-2", revision_needed=True, revision_priority=5)
        )
        manager._store.save_skill(
            _make_skill(agent_id, "low", revision_needed=True, revision_priority=1)
        )

        summary = manager.process_daily_skills(agent_id)
        assert sorted(summary.high_priority_revisions) == ["high-1", "high-2"]
        assert summary.revision_needed_count == 3

    def test_store_failure_returns_empty_summary(self, tmp_path: Path) -> None:
        manager = _make_manager(tmp_path)
        manager._store.list_by_revision_needed = MagicMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("db down")
        )
        summary = manager.process_daily_skills(uuid4())
        assert summary == DailySkillSummary()


# ── process_deep_skills ───────────────────────────────────────────────────


class TestProcessDeepSkills:
    def test_no_active_skills_returns_empty(self, tmp_path: Path) -> None:
        summary = _make_manager(tmp_path).process_deep_skills(uuid4())
        assert isinstance(summary, DeepSkillSummary)
        assert summary.archive_candidates == []
        assert summary.problematic_skills == []

    def test_archive_candidates_filtered_by_threshold_and_pin(self, tmp_path: Path) -> None:
        manager = _make_manager(tmp_path, deep_archive_sessions=50)
        agent_id = uuid4()

        manager._store.save_skill(
            _make_skill(agent_id, "long-idle", sessions_since_use=60)
        )
        manager._store.save_skill(
            _make_skill(agent_id, "recent", sessions_since_use=10)
        )
        # User-pinned must NEVER appear in archive candidates
        manager._store.save_skill(
            _make_skill(
                agent_id, "pinned-idle", sessions_since_use=99, user_pinned=True
            )
        )
        # Disabled skill: list_by_status(active) skips this one anyway
        manager._store.save_skill(
            _make_skill(
                agent_id, "disabled", sessions_since_use=99, status=SkillStatus.disabled
            )
        )

        summary = manager.process_deep_skills(agent_id)
        assert summary.archive_candidates == ["long-idle"]

    def test_problematic_skills_failure_rate(self, tmp_path: Path) -> None:
        manager = _make_manager(
            tmp_path,
            deep_failure_rate_threshold=0.5,
            deep_min_invocations_for_failure_rate=5,
        )
        agent_id = uuid4()

        # 8/10 failures → 0.8 > 0.5 → problematic
        manager._store.save_skill(
            _make_skill(agent_id, "broken", invocations_count=10, failure_count=8)
        )
        # 1/10 failures → 0.1 not problematic
        manager._store.save_skill(
            _make_skill(agent_id, "ok", invocations_count=10, failure_count=1)
        )
        # 3/3 failures → fails ratio but below min_invocations → ignored
        manager._store.save_skill(
            _make_skill(agent_id, "too-young", invocations_count=3, failure_count=3)
        )

        summary = manager.process_deep_skills(agent_id)
        assert summary.problematic_skills == ["broken"]

    def test_does_not_mutate_skills(self, tmp_path: Path) -> None:
        """Deep hook is read-only."""
        manager = _make_manager(tmp_path)
        agent_id = uuid4()
        skill = _make_skill(agent_id, "broken", invocations_count=10, failure_count=8)
        manager._store.save_skill(skill)

        before = replace(skill)
        manager.process_deep_skills(agent_id)
        after = manager._store.get_skill_by_id(skill.id)
        assert after is not None
        assert after.revision_needed == before.revision_needed
        assert after.revision_priority == before.revision_priority
        assert after.status == before.status


# ── port + noop conformance ───────────────────────────────────────────────


def test_noop_returns_empty_summaries() -> None:
    noop = NoopSkillManager()
    assert noop.process_daily_skills(uuid4()) == DailySkillSummary()
    assert noop.process_deep_skills(uuid4()) == DeepSkillSummary()


# ── DailyReflectionService wiring ─────────────────────────────────────────


class TestDailyReflectionServiceHook:
    def _make_service(self, skill_manager=None, agent_id=None):
        from atman.adapters.storage.in_memory_reflection_store import (
            InMemoryReflectionEventStore,
        )
        from atman.core.services.reflection_service import DailyReflectionService

        session_repo = MagicMock()
        session_repo.get_sessions_in_range.return_value = []  # empty day path

        return DailyReflectionService(
            session_repo=session_repo,
            identity_repo=MagicMock(),
            pattern_store=MagicMock(),
            reflection_model=MagicMock(),
            event_store=InMemoryReflectionEventStore(),
            skill_manager=skill_manager,
            agent_id=agent_id,
        )

    def test_hook_called_when_wired(self) -> None:
        agent_id = uuid4()
        # Empty-day branch returns early — we test the hook in isolation
        # through the helper to avoid duplicating the full daily reflect setup.
        skill_manager = MagicMock()
        skill_manager.process_daily_skills.return_value = DailySkillSummary(
            revision_needed_count=2, high_priority_revisions=["a"]
        )
        svc = self._make_service(skill_manager=skill_manager, agent_id=agent_id)

        out = svc._process_skills_for_daily()
        skill_manager.process_daily_skills.assert_called_once_with(agent_id)
        assert out is not None and out.revision_needed_count == 2

    def test_hook_skipped_when_skill_manager_none(self) -> None:
        svc = self._make_service(skill_manager=None, agent_id=uuid4())
        assert svc._process_skills_for_daily() is None

    def test_hook_skipped_when_agent_id_none(self) -> None:
        svc = self._make_service(skill_manager=MagicMock(), agent_id=None)
        assert svc._process_skills_for_daily() is None

    def test_hook_failure_does_not_propagate(self) -> None:
        skill_manager = MagicMock()
        skill_manager.process_daily_skills.side_effect = RuntimeError("boom")
        svc = self._make_service(skill_manager=skill_manager, agent_id=uuid4())
        assert svc._process_skills_for_daily() is None


# ── DeepReflectionService wiring ──────────────────────────────────────────


class TestDeepReflectionServiceHook:
    def _make_service(self, skill_manager=None, agent_id=None):
        from atman.adapters.storage.in_memory_reflection_store import (
            InMemoryReflectionEventStore,
        )
        from atman.core.services.reflection_service import DeepReflectionService

        return DeepReflectionService(
            session_repo=MagicMock(),
            identity_repo=MagicMock(),
            narrative_repo=MagicMock(),
            pattern_store=MagicMock(),
            health_store=MagicMock(),
            reflection_model=MagicMock(),
            event_store=InMemoryReflectionEventStore(),
            skill_manager=skill_manager,
            agent_id=agent_id,
        )

    def test_hook_called_when_wired(self) -> None:
        agent_id = uuid4()
        skill_manager = MagicMock()
        skill_manager.process_deep_skills.return_value = DeepSkillSummary(
            archive_candidates=["a"], problematic_skills=["b"]
        )
        svc = self._make_service(skill_manager=skill_manager, agent_id=agent_id)

        out = svc._process_skills_for_deep()
        skill_manager.process_deep_skills.assert_called_once_with(agent_id)
        assert out is not None
        assert out.archive_candidates == ["a"]
        assert out.problematic_skills == ["b"]

    def test_hook_skipped_when_skill_manager_none(self) -> None:
        svc = self._make_service(skill_manager=None, agent_id=uuid4())
        assert svc._process_skills_for_deep() is None

    def test_hook_skipped_when_agent_id_none(self) -> None:
        svc = self._make_service(skill_manager=MagicMock(), agent_id=None)
        assert svc._process_skills_for_deep() is None

    def test_hook_failure_does_not_propagate(self) -> None:
        skill_manager = MagicMock()
        skill_manager.process_deep_skills.side_effect = RuntimeError("boom")
        svc = self._make_service(skill_manager=skill_manager, agent_id=uuid4())
        assert svc._process_skills_for_deep() is None


# ── store extension ───────────────────────────────────────────────────────


def test_list_by_revision_needed_orders_by_priority() -> None:
    store = InMemorySkillStore()
    agent_id = uuid4()
    store.save_skill(_make_skill(agent_id, "lo", revision_needed=True, revision_priority=1))
    store.save_skill(_make_skill(agent_id, "hi", revision_needed=True, revision_priority=5))
    store.save_skill(_make_skill(agent_id, "mid", revision_needed=True, revision_priority=3))
    store.save_skill(
        _make_skill(agent_id, "none", revision_needed=False, revision_priority=99)
    )

    result = store.list_by_revision_needed(agent_id)
    assert [s.name for s in result] == ["hi", "mid", "lo"]
