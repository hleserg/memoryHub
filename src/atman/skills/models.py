"""Domain models for the skill-loop."""

from __future__ import annotations

from dataclasses import dataclass, field  # noqa: F401 (field used below)
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from uuid import UUID


class SkillKind(StrEnum):
    active = "active"
    passive = "passive"


class SkillStatus(StrEnum):
    draft = "draft"
    active = "active"
    disabled = "disabled"


class SkillOrigin(StrEnum):
    in_session = "in_session"
    reflection_pattern = "reflection_pattern"
    external = "external"


@dataclass(frozen=True)
class Skill:
    id: UUID
    agent_id: UUID
    entity_id: UUID  # soft ref → agent_{N}.entities.id
    name: str  # kebab-case, matches SKILL.md metadata.name
    description: str
    version: str
    kind: SkillKind
    status: SkillStatus
    origin: SkillOrigin
    core: bool
    session_scoped: bool
    user_pinned: bool
    auto_pinned: bool
    invocations_count: int
    success_count: int
    failure_count: int
    last_used_at: datetime | None
    sessions_since_use: int
    revision_needed: bool
    revision_priority: int
    last_revised_at: datetime | None
    manifest_inferred: bool
    skill_root: Path
    manifest_path: Path
    created_at: datetime
    updated_at: datetime

    @property
    def is_pinned(self) -> bool:
        return self.user_pinned or self.auto_pinned

    @property
    def description_short(self) -> str:
        """First line of description for bootstrap injection."""
        return self.description.split("\n")[0].strip()


@dataclass(frozen=True)
class SkillInvocation:
    id: UUID
    skill_id: UUID
    agent_id: UUID
    session_id: UUID
    started_at: datetime
    ended_at: datetime | None
    preliminary_status: str | None  # executing|executed_ok|executed_fail|executed_unknown
    final_status: str | None  # helped|didnt_help|unclear; None until micro reflection
    agent_marker: str | None  # helped|didnt_help|unclear (explicit agent signal)
    agent_marker_note: str | None
    user_feedback_hints: list[str] = field(default_factory=list)
    behavioral_hints: list[str] = field(default_factory=list)
    exit_code: int | None = None
    input_context_summary: str | None = None
    output_summary: str | None = None
    processed_at: datetime | None = None


class SuggestionStrength(StrEnum):
    suggest = "suggest"
    strong_suggest = "strong-suggest"
    passive_auto_invoke = "passive-auto-invoke"


@dataclass(frozen=True)
class SkillSuggestion:
    skill_id: str
    skill_name: str
    card_text: str  # first ~500 chars of SKILL.md body
    confidence: float  # 0..1
    reason: str  # human-readable explanation of why this skill was suggested
    strength: SuggestionStrength


# ── Reflection hook summaries (HLE-36) ────────────────────────────────────


@dataclass(frozen=True)
class DailySkillSummary:
    """Result of :meth:`SkillManagerPort.process_daily_skills`.

    ``high_priority_revisions`` are the skill names whose ``revision_priority``
    is already above the alert threshold and warrant operator attention in
    the daily summary. ``revision_priority_bumped`` counts how many skills
    received an idle-driven priority increment during this run.
    """

    revision_needed_count: int = 0
    revision_priority_bumped: int = 0
    high_priority_revisions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DeepSkillSummary:
    """Result of :meth:`SkillManagerPort.process_deep_skills`.

    ``archive_candidates`` — names of long-idle, non-user-pinned skills
    suitable for archiving. ``problematic_skills`` — names of frequently-
    invoked skills with high failure rates. Both are inputs to the deep-
    reflection health assessment; this hook never modifies skills directly.
    """

    archive_candidates: list[str] = field(default_factory=list)
    problematic_skills: list[str] = field(default_factory=list)
