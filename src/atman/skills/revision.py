"""HLE-40 — Skill Revision Workflow.

Takes skills flagged as ``revision_needed=True`` and asks a
:class:`SkillReviser` (typically LLM-backed) to propose a better SKILL.md
body based on the skill's failure history. The old manifest is preserved
as ``SKILL.md.bak.<timestamp>`` before any write, the version is bumped
(minor), and the skill row is updated to clear the revision flag.

By design this never runs in the chat hot path — it is invoked from the
daily/deep reflection scheduler or the ``atman-skills revise`` CLI.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable
from uuid import UUID

from atman.skills.manifest import SkillManifest, parse_skill_md, write_skill_md
from atman.skills.models import Skill
from atman.skills.store import SkillStore

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SkillRevisionProposal:
    """LLM-proposed revision for a single skill.

    Either the entire SKILL.md body is rewritten (``new_body``), or the
    proposer chose not to revise (``new_body is None``) — in which case the
    service records the attempt without touching the manifest.
    """

    new_body: str | None
    new_description: str | None = None  # optional: rewrite description too
    rationale: str = ""  # short note for the audit log


@runtime_checkable
class SkillReviser(Protocol):
    """Port: LLM-backed skill body rewriter.

    Implementations should be deterministic enough to be re-runnable and
    must NOT modify the skill row themselves — this is a read-only oracle.
    """

    def propose_revision(
        self,
        skill: Skill,
        manifest_body: str,
        failure_summary: str,
    ) -> SkillRevisionProposal: ...


class NoopSkillReviser:
    """Default reviser used when no LLM is configured — never proposes changes."""

    def propose_revision(
        self,
        skill: Skill,
        manifest_body: str,
        failure_summary: str,
    ) -> SkillRevisionProposal:
        _ = (skill, manifest_body, failure_summary)
        return SkillRevisionProposal(new_body=None, rationale="noop reviser")


@dataclass(frozen=True)
class RevisionOutcome:
    """One revise_pending() outcome row."""

    skill_name: str
    revised: bool
    new_version: str | None
    backup_path: Path | None
    rationale: str


class SkillRevisionService:
    """Drives the skill-revision lifecycle."""

    def __init__(
        self,
        store: SkillStore,
        reviser: SkillReviser,
    ) -> None:
        self._store = store
        self._reviser = reviser

    # ── public API ────────────────────────────────────────────────────────

    def revise_pending(
        self,
        agent_id: UUID,
        max_skills: int = 3,
        *,
        dry_run: bool = False,
    ) -> list[RevisionOutcome]:
        """Take the top ``max_skills`` candidates and try to revise each.

        ``dry_run`` runs the reviser but skips both the disk backup/write
        and the store update, so the caller can show the operator what
        would change before committing.
        """
        if max_skills <= 0:
            raise ValueError(f"max_skills must be positive, got {max_skills}")

        try:
            candidates = self._store.list_by_revision_needed(agent_id)
        except Exception as exc:
            _log.warning("revise_pending: store lookup failed: %s", exc)
            return []

        outcomes: list[RevisionOutcome] = []
        for skill in candidates[:max_skills]:
            try:
                outcomes.append(self._revise_one(skill, dry_run=dry_run))
            except Exception as exc:
                _log.warning(
                    "revise_pending: skill '%s' revision raised: %s", skill.name, exc
                )
                outcomes.append(
                    RevisionOutcome(
                        skill_name=skill.name,
                        revised=False,
                        new_version=None,
                        backup_path=None,
                        rationale=f"error: {exc}",
                    )
                )
        return outcomes

    # ── internals ─────────────────────────────────────────────────────────

    def _revise_one(self, skill: Skill, *, dry_run: bool) -> RevisionOutcome:
        manifest = parse_skill_md(skill.manifest_path)
        failure_summary = self._failure_summary(skill)
        proposal = self._reviser.propose_revision(
            skill=skill,
            manifest_body=manifest.body,
            failure_summary=failure_summary,
        )

        if proposal.new_body is None or not proposal.new_body.strip():
            return RevisionOutcome(
                skill_name=skill.name,
                revised=False,
                new_version=None,
                backup_path=None,
                rationale=proposal.rationale or "reviser declined to propose changes",
            )

        new_version = _bump_minor_version(skill.version)
        if dry_run:
            return RevisionOutcome(
                skill_name=skill.name,
                revised=False,
                new_version=new_version,
                backup_path=None,
                rationale=f"(dry-run) {proposal.rationale}",
            )

        backup_path = _backup_manifest(skill.manifest_path)

        new_manifest = SkillManifest(
            **{
                **manifest.__dict__,
                "version": new_version,
                "description": (
                    proposal.new_description.strip()
                    if proposal.new_description and proposal.new_description.strip()
                    else manifest.description
                ),
                "body": proposal.new_body.strip(),
            }
        )
        write_skill_md(new_manifest, skill.manifest_path)

        now = datetime.now(UTC)
        updated_skill = replace(
            skill,
            version=new_version,
            description=new_manifest.description,
            revision_needed=False,
            revision_priority=0,
            last_revised_at=now,
            updated_at=now,
        )
        self._store.save_skill(updated_skill)

        _log.info(
            "Revised skill '%s' (%s → %s; backup at %s)",
            skill.name,
            skill.version,
            new_version,
            backup_path,
        )
        return RevisionOutcome(
            skill_name=skill.name,
            revised=True,
            new_version=new_version,
            backup_path=backup_path,
            rationale=proposal.rationale or "applied revision",
        )

    def _failure_summary(self, skill: Skill) -> str:
        """One-paragraph summary the reviser can use as prompt input."""
        invocations = max(1, skill.invocations_count)
        failure_rate = skill.failure_count / invocations
        return (
            f"Skill '{skill.name}' has been invoked {skill.invocations_count} time(s); "
            f"failures={skill.failure_count} success={skill.success_count} "
            f"(rate={failure_rate:.2f}). "
            f"Idle for {skill.sessions_since_use} session(s). "
            f"revision_priority={skill.revision_priority}."
        )


# ── helpers ───────────────────────────────────────────────────────────────


def _bump_minor_version(version: str) -> str:
    """Bump the minor component of a semver-ish ``MAJOR.MINOR.PATCH`` string.

    Falls back to appending ``+rev<n>`` for unparseable values.
    """
    parts = version.split(".")
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
        return f"{major}.{minor + 1}.0"
    except (ValueError, IndexError):
        return f"{version}+rev1"


def _backup_manifest(manifest_path: Path) -> Path:
    """Copy ``SKILL.md`` to ``SKILL.md.bak.<utc-timestamp>`` and return the path."""
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup = manifest_path.with_suffix(f"{manifest_path.suffix}.bak.{timestamp}")
    shutil.copy2(manifest_path, backup)
    return backup
