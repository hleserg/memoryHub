"""SkillManagerPort — abstract interface consumed by all code outside atman.skills.

All other Atman components (AtmanDeps, factory, reflection, instructions) depend
only on this Protocol, never on the concrete SkillManager. This makes the entire
skill-loop swappable: pass NoopSkillManager when disabled, real SkillManager when on.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from uuid import UUID

if TYPE_CHECKING:
    from atman.skills.models import DailySkillSummary, DeepSkillSummary, Skill, SkillSuggestion


@runtime_checkable
class SkillManagerPort(Protocol):
    def list_pinned(self, agent_id: UUID) -> list[Skill]:
        """Return all pinned (user_pinned or auto_pinned) active skills for the agent."""
        ...

    def list_available(self, agent_id: UUID, session_id: UUID) -> list[Skill]:
        """Return pinned skills + any skills suggested/loaded so far in this session."""
        ...

    def trigger_router(
        self,
        message: str,
        agent_id: UUID,
        session_id: UUID,
    ) -> list[SkillSuggestion]:
        """Analyse message and return ranked skill suggestions."""
        ...

    def invoke(
        self,
        skill_id: UUID,
        args: dict,
        agent_id: UUID,
        session_id: UUID,
    ) -> UUID:
        """Start a skill invocation. Returns invocation_id for later mark_result()."""
        ...

    def mark_result(
        self,
        invocation_id: UUID,
        status: str,
        note: str | None = None,
    ) -> None:
        """Record the agent's explicit verdict: helped | didnt_help | unclear."""
        ...

    def capture(
        self,
        name: str,
        description: str,
        agent_id: UUID,
        session_id: UUID,
        code_path: Path | None = None,
        instructions: str | None = None,
    ) -> Skill:
        """Create a new skill from the current session (origin=in_session, status=draft)."""
        ...

    def get_skill(self, agent_id: UUID, name: str) -> Skill | None:
        """Look up a skill by name. Returns None if not found or disabled."""
        ...

    def process_session_skills(self, agent_id: UUID, session_id: UUID) -> None:
        """Called by micro reflection to finalize invocations and update stats.

        Determines final_status for each unprocessed invocation in the session,
        updates success/failure counts, handles auto-pin/auto-downgrade, and
        sets revision_needed flags.
        """
        ...

    def write_session_skills_marker(
        self,
        workspace: Path,
        session_id: UUID,
        agent_id: UUID,
    ) -> Path | None:
        """Write a JSON summary of this session's skill activity.

        Produces ``atman_session_skills_<timestamp>.json`` under
        ``workspace`` describing each skill used in the session, with
        invocation counts and the dominant preliminary status. Called by
        the runner at session end so the on-disk session bundle is
        self-contained for later dashboards / analytics.

        Returns the path on success, ``None`` when there is nothing to
        write or the loop is disabled.
        """
        ...

    def process_daily_skills(self, agent_id: UUID) -> DailySkillSummary:
        """Daily-reflection hook: surface revision-needed skills.

        Bumps ``revision_priority`` for skills whose ``revision_needed``
        flag has been set and that have stayed idle for at least
        ``daily_revision_idle_bump_sessions`` sessions, and returns a
        compact summary the DailyReflectionService can fold into its
        ``ReflectionEvent`` notes.
        """
        ...

    def process_deep_skills(self, agent_id: UUID) -> DeepSkillSummary:
        """Deep-reflection hook: surface archive candidates + problem skills.

        Pure read — never modifies skill rows. The deep reflection service
        is the only place permitted to make identity-level decisions about
        archiving / removing skills; this hook merely classifies them.
        """
        ...
