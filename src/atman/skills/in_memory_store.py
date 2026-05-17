"""In-memory SkillStore implementation for tests."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from atman.skills.models import Skill, SkillInvocation, SkillStatus


def _now() -> datetime:
    return datetime.now(UTC)


class InMemorySkillStore:
    def __init__(self) -> None:
        self._skills: dict[UUID, Skill] = {}
        self._invocations: dict[UUID, SkillInvocation] = {}

    # ── helpers ───────────────────────────────────────────────────────────────

    def _skills_for(self, agent_id: UUID) -> list[Skill]:
        return [s for s in self._skills.values() if s.agent_id == agent_id]

    # ── Skill CRUD ────────────────────────────────────────────────────────────

    def save_skill(self, skill: Skill) -> None:
        self._skills[skill.id] = skill

    def get_skill_by_name(self, agent_id: UUID, name: str) -> Skill | None:
        return next((s for s in self._skills_for(agent_id) if s.name == name), None)

    def get_skill_by_id(self, skill_id: UUID) -> Skill | None:
        return self._skills.get(skill_id)

    def list_pinned(self, agent_id: UUID) -> list[Skill]:
        return [
            s
            for s in self._skills_for(agent_id)
            if s.status == SkillStatus.active and (s.user_pinned or s.auto_pinned)
        ]

    def list_by_status(self, agent_id: UUID, status: SkillStatus) -> list[Skill]:
        return [s for s in self._skills_for(agent_id) if s.status == status]

    def list_active_on_demand(self, agent_id: UUID) -> list[Skill]:
        return [
            s
            for s in self._skills_for(agent_id)
            if s.status == SkillStatus.active and not s.user_pinned and not s.auto_pinned
        ]

    def list_by_revision_needed(self, agent_id: UUID) -> list[Skill]:
        skills = [s for s in self._skills_for(agent_id) if s.revision_needed]
        return sorted(skills, key=lambda s: s.revision_priority, reverse=True)

    def update_skill_status(self, skill_id: UUID, status: SkillStatus) -> None:
        s = self._skills[skill_id]
        self._skills[skill_id] = replace(s, status=status, updated_at=_now())

    def update_pinning(
        self,
        skill_id: UUID,
        *,
        auto_pinned: bool | None = None,
        user_pinned: bool | None = None,
    ) -> None:
        s = self._skills[skill_id]
        kwargs: dict = {"updated_at": _now()}
        if auto_pinned is not None:
            kwargs["auto_pinned"] = auto_pinned
        if user_pinned is not None:
            kwargs["user_pinned"] = user_pinned
        self._skills[skill_id] = replace(s, **kwargs)

    def update_stats(
        self,
        skill_id: UUID,
        *,
        success_delta: int = 0,
        failure_delta: int = 0,
        last_used_at: datetime | None = None,
    ) -> None:
        s = self._skills[skill_id]
        self._skills[skill_id] = replace(
            s,
            success_count=s.success_count + success_delta,
            failure_count=s.failure_count + failure_delta,
            last_used_at=last_used_at if last_used_at is not None else s.last_used_at,
            updated_at=_now(),
        )

    def bump_sessions_since_use(self, agent_id: UUID, exclude_skill_ids: set[UUID]) -> None:
        for skill_id, s in list(self._skills.items()):
            if s.agent_id != agent_id:
                continue
            if not (s.user_pinned or s.auto_pinned):
                continue
            if skill_id in exclude_skill_ids:
                continue
            self._skills[skill_id] = replace(
                s, sessions_since_use=s.sessions_since_use + 1, updated_at=_now()
            )

    def set_revision_needed(self, skill_id: UUID, priority_bump: int = 1) -> None:
        s = self._skills[skill_id]
        self._skills[skill_id] = replace(
            s,
            revision_needed=True,
            revision_priority=s.revision_priority + priority_bump,
            updated_at=_now(),
        )

    def reset_sessions_since_use(self, skill_id: UUID) -> None:
        s = self._skills[skill_id]
        self._skills[skill_id] = replace(s, sessions_since_use=0, updated_at=_now())

    # ── Invocation log ────────────────────────────────────────────────────────

    def create_invocation(
        self,
        skill_id: UUID,
        agent_id: UUID,
        session_id: UUID,
        input_context_summary: str | None = None,
    ) -> UUID:
        inv_id = uuid4()
        inv = SkillInvocation(
            id=inv_id,
            skill_id=skill_id,
            agent_id=agent_id,
            session_id=session_id,
            started_at=_now(),
            ended_at=None,
            preliminary_status="executing",
            final_status=None,
            agent_marker=None,
            agent_marker_note=None,
            user_feedback_hints=[],
            behavioral_hints=[],
            exit_code=None,
            input_context_summary=input_context_summary,
            output_summary=None,
            processed_at=None,
        )
        self._invocations[inv_id] = inv
        # update invocations_count + last_used_at on the skill
        s = self._skills[skill_id]
        self._skills[skill_id] = replace(
            s,
            invocations_count=s.invocations_count + 1,
            sessions_since_use=0,
            last_used_at=_now(),
            updated_at=_now(),
        )
        return inv_id

    def set_preliminary_status(
        self,
        invocation_id: UUID,
        status: str,
        exit_code: int | None = None,
        output_summary: str | None = None,
    ) -> None:
        inv = self._invocations[invocation_id]
        self._invocations[invocation_id] = replace(
            inv,
            preliminary_status=status,
            exit_code=exit_code,
            output_summary=output_summary,
            ended_at=_now(),
        )

    def write_agent_marker(self, invocation_id: UUID, marker: str, note: str | None) -> None:
        inv = self._invocations[invocation_id]
        self._invocations[invocation_id] = replace(inv, agent_marker=marker, agent_marker_note=note)

    def append_behavioral_hint(self, invocation_id: UUID, hint: str) -> None:
        inv = self._invocations[invocation_id]
        self._invocations[invocation_id] = replace(
            inv, behavioral_hints=[*inv.behavioral_hints, hint]
        )

    def append_user_feedback_hint(self, invocation_id: UUID, hint: str) -> None:
        inv = self._invocations[invocation_id]
        self._invocations[invocation_id] = replace(
            inv, user_feedback_hints=[*inv.user_feedback_hints, hint]
        )

    def get_unprocessed_invocations(
        self, agent_id: UUID, session_id: UUID
    ) -> list[SkillInvocation]:
        return [
            inv
            for inv in self._invocations.values()
            if inv.agent_id == agent_id
            and inv.session_id == session_id
            and inv.processed_at is None
        ]

    def set_final_status(self, invocation_id: UUID, final_status: str) -> None:
        inv = self._invocations[invocation_id]
        self._invocations[invocation_id] = replace(inv, final_status=final_status)

    def mark_processed(self, invocation_id: UUID) -> None:
        inv = self._invocations[invocation_id]
        self._invocations[invocation_id] = replace(inv, processed_at=_now())
