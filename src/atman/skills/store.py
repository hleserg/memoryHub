"""SkillStore port — abstract storage interface for skills and invocations.

Concrete implementations:
  InMemorySkillStore      — for tests
  PostgresSkillStore      — production (public.skills + public.skill_invocations)
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable
from uuid import UUID

from atman.skills.models import Skill, SkillInvocation, SkillStatus


@runtime_checkable
class SkillStore(Protocol):
    # ── Skill CRUD ────────────────────────────────────────────────────────────

    def save_skill(self, skill: Skill) -> None:
        """Insert or update a skill row."""
        ...

    def get_skill_by_name(self, agent_id: UUID, name: str) -> Skill | None: ...

    def get_skill_by_id(self, skill_id: UUID) -> Skill | None: ...

    def list_pinned(self, agent_id: UUID) -> list[Skill]:
        """Return active skills where user_pinned OR auto_pinned."""
        ...

    def list_by_status(self, agent_id: UUID, status: SkillStatus) -> list[Skill]: ...

    def list_active_on_demand(self, agent_id: UUID) -> list[Skill]:
        """Return active, non-pinned skills for retriever scanning."""
        ...

    def list_by_revision_needed(self, agent_id: UUID) -> list[Skill]:
        """Return skills with ``revision_needed=True``, highest priority first."""
        ...

    def update_skill_status(self, skill_id: UUID, status: SkillStatus) -> None: ...

    def update_pinning(
        self,
        skill_id: UUID,
        *,
        auto_pinned: bool | None = None,
        user_pinned: bool | None = None,
    ) -> None: ...

    def update_stats(
        self,
        skill_id: UUID,
        *,
        success_delta: int = 0,
        failure_delta: int = 0,
        last_used_at: datetime | None = None,
    ) -> None: ...

    def bump_sessions_since_use(self, agent_id: UUID, exclude_skill_ids: set[UUID]) -> None:
        """Increment ``sessions_since_use`` for every active skill NOT in
        ``exclude_skill_ids``.

        Applies to every ``status='active'`` skill (pinned or not) — the
        counter must continue advancing after auto-downgrade so deep-
        reflection archive thresholds remain reachable. Disabled / draft
        skills are excluded.
        """
        ...

    def set_revision_needed(self, skill_id: UUID, priority_bump: int = 1) -> None: ...

    def reset_sessions_since_use(self, skill_id: UUID) -> None: ...

    # ── Invocation log ────────────────────────────────────────────────────────

    def create_invocation(
        self,
        skill_id: UUID,
        agent_id: UUID,
        session_id: UUID,
        input_context_summary: str | None = None,
    ) -> UUID:
        """Create a new invocation row in 'executing' state. Returns invocation_id."""
        ...

    def set_preliminary_status(
        self,
        invocation_id: UUID,
        status: str,
        exit_code: int | None = None,
        output_summary: str | None = None,
    ) -> None: ...

    def write_agent_marker(self, invocation_id: UUID, marker: str, note: str | None) -> None: ...

    def append_behavioral_hint(self, invocation_id: UUID, hint: str) -> None: ...

    def append_user_feedback_hint(self, invocation_id: UUID, hint: str) -> None: ...

    def get_unprocessed_invocations(
        self, agent_id: UUID, session_id: UUID
    ) -> list[SkillInvocation]:
        """Return invocations not yet processed by micro reflection."""
        ...

    def set_final_status(self, invocation_id: UUID, final_status: str) -> None: ...

    def mark_processed(self, invocation_id: UUID) -> None: ...
