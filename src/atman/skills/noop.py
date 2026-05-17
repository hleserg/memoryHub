"""NoopSkillManager — drop-in when atman.skills.enabled = false.

All read methods return empty results (safe for callers that check before using).
All write methods raise SkillsDisabledError with a clear message.
process_session_skills() is a silent no-op so micro reflection can always call it.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from atman.skills.models import DailySkillSummary, DeepSkillSummary, Skill, SkillSuggestion


class SkillsDisabledError(RuntimeError):
    """Raised when a write operation is attempted on the disabled skill-loop."""


class NoopSkillManager:
    """Satisfies SkillManagerPort with safe empty/no-op behaviour."""

    def list_pinned(self, agent_id: UUID) -> list[Skill]:
        return []

    def list_available(self, agent_id: UUID, session_id: UUID) -> list[Skill]:
        return []

    def trigger_router(
        self,
        message: str,
        agent_id: UUID,
        session_id: UUID,
    ) -> list[SkillSuggestion]:
        return []

    def invoke(
        self,
        skill_id: UUID,
        args: dict,
        agent_id: UUID,
        session_id: UUID,
    ) -> UUID:
        raise SkillsDisabledError(
            "Skill loop is disabled (atman.skills.enabled = false). "
            "Enable it in config to invoke skills."
        )

    def mark_result(
        self,
        invocation_id: UUID,
        status: str,
        note: str | None = None,
    ) -> None:
        raise SkillsDisabledError("Skill loop is disabled. mark_result() has no effect.")

    def capture(
        self,
        name: str,
        description: str,
        agent_id: UUID,
        session_id: UUID,
        code_path: Path | None = None,
        instructions: str | None = None,
    ) -> Skill:
        raise SkillsDisabledError(
            "Skill loop is disabled. Cannot capture skills (atman.skills.enabled = false)."
        )

    def get_skill(self, agent_id: UUID, name: str) -> Skill | None:
        return None

    def process_session_skills(self, agent_id: UUID, session_id: UUID) -> None:
        # Silent no-op: micro reflection always calls this; when disabled, nothing happens.
        return

    def write_session_skills_marker(
        self,
        workspace: Path,
        session_id: UUID,
        agent_id: UUID,
    ) -> Path | None:
        # No invocations to summarise when the loop is disabled.
        return None

    def process_daily_skills(self, agent_id: UUID) -> DailySkillSummary:
        return DailySkillSummary()

    def process_deep_skills(self, agent_id: UUID) -> DeepSkillSummary:
        return DeepSkillSummary()
