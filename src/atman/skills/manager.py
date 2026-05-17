"""SkillManager — real implementation of SkillManagerPort.

Orchestrates the full skill lifecycle:
- list_pinned / list_available / trigger_router
- invoke (creates invocation row, runs entry script if present)
- mark_result (explicit agent feedback)
- capture (in-session skill creation)
- process_session_skills (called by micro reflection)
"""

from __future__ import annotations

import json
import logging
import subprocess  # nosec B404
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from atman.config import SkillsSettings
from atman.skills.manifest import SkillManifest, write_skill_md
from atman.skills.models import Skill, SkillKind, SkillOrigin, SkillStatus, SkillSuggestion
from atman.skills.projection import ProjectionAdapter
from atman.skills.retriever import SkillRetriever
from atman.skills.store import SkillStore

_log = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def _dominant(counts: dict[str, int]) -> str | None:
    """Return the most-frequent key in ``counts`` (None on empty input)."""
    if not counts:
        return None
    return max(counts.items(), key=lambda kv: kv[1])[0]


class SkillManager:
    def __init__(
        self,
        store: SkillStore,
        retriever: SkillRetriever,
        projector: ProjectionAdapter,
        config: SkillsSettings,
        agents_root: Path,
    ) -> None:
        self._store = store
        self._retriever = retriever
        self._projector = projector
        self._config = config
        self._agents_root = agents_root
        # Per-session cache: set of skill names loaded in this session
        self._session_loaded: dict[UUID, set[str]] = {}

    # ── Read methods ──────────────────────────────────────────────────────────

    def list_pinned(self, agent_id: UUID) -> list[Skill]:
        return self._store.list_pinned(agent_id)

    def list_available(self, agent_id: UUID, session_id: UUID) -> list[Skill]:
        pinned = self._store.list_pinned(agent_id)
        loaded_names = self._session_loaded.get(session_id, set())
        extra: list[Skill] = []
        for name in loaded_names:
            skill = self._store.get_skill_by_name(agent_id, name)
            if skill and skill not in pinned:
                extra.append(skill)
        return pinned + extra

    def trigger_router(
        self,
        message: str,
        agent_id: UUID,
        session_id: UUID,
    ) -> list[SkillSuggestion]:
        return self._retriever.suggest(message, agent_id, session_id)

    def get_skill(self, agent_id: UUID, name: str) -> Skill | None:
        return self._store.get_skill_by_name(agent_id, name)

    # ── Write methods ─────────────────────────────────────────────────────────

    def invoke(
        self,
        skill_id: UUID,
        args: dict,
        agent_id: UUID,
        session_id: UUID,
    ) -> UUID:
        skill = self._store.get_skill_by_id(skill_id)
        if skill is None:
            raise ValueError(f"Skill {skill_id} not found")
        if skill.status == SkillStatus.disabled:
            raise ValueError(f"Skill '{skill.name}' is disabled")

        # Lazy-load tracking for on-demand skills
        self._session_loaded.setdefault(session_id, set()).add(skill.name)

        # Create invocation row
        invocation_id = self._store.create_invocation(
            skill_id=skill_id,
            agent_id=agent_id,
            session_id=session_id,
            input_context_summary=json.dumps(args)[:500] if args else None,
        )

        # Run entry script if present
        manifest_path = skill.manifest_path
        if manifest_path.exists():
            try:
                from atman.skills.manifest import parse_skill_md

                manifest = parse_skill_md(manifest_path)
                if manifest.runtime_entry:
                    self._run_entry(
                        skill=skill,
                        entry=manifest.runtime_entry,
                        sandbox=manifest.runtime_sandbox,
                        args=args,
                        invocation_id=invocation_id,
                    )
                    return invocation_id
            except Exception as exc:
                _log.warning("Error reading manifest for %s: %s", skill.name, exc)

        # No entry script — instruction-only skill
        self._store.set_preliminary_status(invocation_id, "executed_unknown")
        return invocation_id

    def _run_entry(
        self,
        skill: Skill,
        entry: str,
        sandbox: str,
        args: dict,
        invocation_id: UUID,
    ) -> None:
        entry_path = skill.skill_root / entry
        if not entry_path.exists():
            _log.warning("Entry script not found: %s", entry_path)
            self._store.set_preliminary_status(invocation_id, "executed_fail", exit_code=-1)
            return

        if sandbox == "subprocess":
            try:
                result = subprocess.run(  # nosec B603 B607
                    ["python", str(entry_path)],
                    input=json.dumps(args),
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                status = "executed_ok" if result.returncode == 0 else "executed_fail"
                self._store.set_preliminary_status(
                    invocation_id,
                    status,
                    exit_code=result.returncode,
                    output_summary=(result.stdout or result.stderr)[:500],
                )
            except subprocess.TimeoutExpired:
                self._store.set_preliminary_status(
                    invocation_id, "executed_fail", exit_code=-1, output_summary="timeout after 60s"
                )
            except Exception as exc:
                _log.warning("Skill subprocess error: %s", exc)
                self._store.set_preliminary_status(
                    invocation_id, "executed_fail", exit_code=-1, output_summary=str(exc)[:500]
                )
        else:
            # inline / none — mark as unknown (agent decides outcome)
            self._store.set_preliminary_status(invocation_id, "executed_unknown")

    def mark_result(
        self,
        invocation_id: UUID,
        status: str,
        note: str | None = None,
    ) -> None:
        valid = {"helped", "didnt_help", "unclear"}
        if status not in valid:
            raise ValueError(f"status must be one of {valid}, got {status!r}")
        self._store.write_agent_marker(invocation_id, status, note)

    def capture(
        self,
        name: str,
        description: str,
        agent_id: UUID,
        session_id: UUID,
        code_path: Path | None = None,
        instructions: str | None = None,
    ) -> Skill:
        if not name or not name.replace("-", "").replace("_", "").isalnum():
            raise ValueError(f"Skill name must be kebab-case alphanumeric, got {name!r}")

        skill_root = self._agents_root / str(agent_id) / "skills" / name
        skill_root.mkdir(parents=True, exist_ok=True)
        manifest_path = skill_root / "SKILL.md"

        body_parts = []
        if instructions:
            body_parts.append(f"## Instructions\n\n{instructions}\n")
        if code_path:
            body_parts.append(f"## Entry\n\nSee `scripts/{code_path.name}`\n")

        manifest = SkillManifest(
            name=name,
            description=description,
            kind=SkillKind.active,
            origin=SkillOrigin.in_session,
            runtime_entry=f"scripts/{code_path.name}" if code_path else None,
            body="\n".join(body_parts) if body_parts else "",
        )
        write_skill_md(manifest, manifest_path)

        if code_path and code_path.exists():
            scripts_dir = skill_root / "scripts"
            scripts_dir.mkdir(exist_ok=True)
            import shutil

            shutil.copy2(code_path, scripts_dir / code_path.name)

        # Create a placeholder entity_id — real entity registration happens
        # when the entity registry is integrated (future work)
        entity_id = uuid4()
        now = _now()
        skill = Skill(
            id=uuid4(),
            agent_id=agent_id,
            entity_id=entity_id,
            name=name,
            description=description,
            version="0.1.0",
            kind=SkillKind.active,
            status=SkillStatus.draft,
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
        self._store.save_skill(skill)
        _log.info("Captured skill '%s' for agent %s (draft)", name, agent_id)
        return skill

    # ── Session-end marker (HLE-35) ───────────────────────────────────────────

    SKILLS_MARKER_SCHEMA_VERSION = 1

    def write_session_skills_marker(
        self,
        workspace: Path,
        session_id: UUID,
        agent_id: UUID,
    ) -> Path | None:
        """Write ``atman_session_skills_<timestamp>.json`` for the session.

        The file lists each skill used during the session with invocation
        counts and the dominant preliminary status — readable for later
        dashboards / analytics. Returns the written path or ``None`` when
        there is nothing to write (no invocations).

        The marker is written **before** ``process_session_skills`` would
        normally run, so it captures the raw outcomes the runner observed,
        not the post-reflection ``final_status``.
        """
        try:
            invocations = self._store.get_unprocessed_invocations(agent_id, session_id)
        except Exception as exc:
            _log.warning("write_session_skills_marker: store lookup failed: %s", exc)
            return None

        if not invocations:
            return None

        # Aggregate per skill_id: dominant preliminary status (most common).
        per_skill: dict[UUID, dict] = {}
        for inv in invocations:
            entry = per_skill.setdefault(
                inv.skill_id,
                {
                    "skill_id": str(inv.skill_id),
                    "skill_name": None,
                    "invocations": 0,
                    "preliminary_status_counts": {},
                    "agent_marker_counts": {},
                },
            )
            entry["invocations"] += 1
            if inv.preliminary_status:
                counts = entry["preliminary_status_counts"]
                counts[inv.preliminary_status] = counts.get(inv.preliminary_status, 0) + 1
            if inv.agent_marker:
                counts = entry["agent_marker_counts"]
                counts[inv.agent_marker] = counts.get(inv.agent_marker, 0) + 1

        # Resolve skill names (best-effort: the row may have been deleted).
        for skill_id, entry in per_skill.items():
            try:
                skill = self._store.get_skill_by_id(skill_id)
            except Exception:
                skill = None
            entry["skill_name"] = skill.name if skill is not None else None
            # Reduce counts dicts to a single dominant value for compact output.
            entry["preliminary_status"] = _dominant(entry.pop("preliminary_status_counts"))
            entry["agent_marker"] = _dominant(entry.pop("agent_marker_counts"))

        now = _now()
        timestamp = now.strftime("%Y%m%dT%H%M%SZ")
        marker_path = workspace / f"atman_session_skills_{timestamp}.json"
        payload = {
            "schema_version": self.SKILLS_MARKER_SCHEMA_VERSION,
            "session_id": str(session_id),
            "agent_id": str(agent_id),
            "timestamp": now.isoformat(),
            "total_invocations": sum(int(e["invocations"]) for e in per_skill.values()),
            "skills_used": sorted(
                per_skill.values(),
                key=lambda e: int(e["invocations"]),
                reverse=True,
            ),
        }
        try:
            workspace.mkdir(parents=True, exist_ok=True)
            marker_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            _log.warning(
                "write_session_skills_marker: failed to write %s: %s", marker_path, exc
            )
            return None

        _log.debug(
            "Skills marker written: session=%s skills=%d path=%s",
            session_id,
            len(per_skill),
            marker_path,
        )
        return marker_path

    # ── Micro-reflection hook ─────────────────────────────────────────────────

    def process_session_skills(self, agent_id: UUID, session_id: UUID) -> None:
        """Finalise all invocations for the session and update skill stats.

        Called by MicroReflectionService at end of session processing.
        """
        invocations = self._store.get_unprocessed_invocations(agent_id, session_id)
        if not invocations:
            return

        used_skill_ids: set[UUID] = set()

        for inv in invocations:
            final_status = self._determine_final_status(inv)
            self._store.set_final_status(inv.id, final_status)
            self._store.mark_processed(inv.id)

            used_skill_ids.add(inv.skill_id)

            if final_status == "helped":
                self._store.update_stats(inv.skill_id, success_delta=1, last_used_at=_now())
            elif final_status == "didnt_help":
                self._store.update_stats(inv.skill_id, failure_delta=1, last_used_at=_now())
                self._store.set_revision_needed(inv.skill_id)
            # 'unclear' — no stat change, no revision flag

        # Bump sessions_since_use for pinned skills that were NOT used this session
        self._store.bump_sessions_since_use(agent_id, exclude_skill_ids=used_skill_ids)

        # Recalculate auto-pin / auto-downgrade
        self._recalculate_pinning(agent_id, used_skill_ids)

        _log.debug(
            "process_session_skills: processed %d invocations for session %s",
            len(invocations),
            session_id,
        )

    def _determine_final_status(self, inv) -> str:
        """Hierarchy: agent_marker > user_feedback_hints > behavioral_hints > exit_code > unclear."""
        if inv.agent_marker in {"helped", "didnt_help", "unclear"}:
            return inv.agent_marker

        # Majority vote on user feedback hints
        if inv.user_feedback_hints:
            positive = sum(1 for h in inv.user_feedback_hints if "positive" in h)
            negative = sum(1 for h in inv.user_feedback_hints if "negative" in h or "not" in h)
            if positive > negative:
                return "helped"
            if negative > positive:
                return "didnt_help"

        # Behavioral hints
        if inv.behavioral_hints:
            helped_hints = sum(
                1 for h in inv.behavioral_hints if "helped" in h or "topic_closed" in h
            )
            failed_hints = sum(1 for h in inv.behavioral_hints if "didnt_help" in h or "retry" in h)
            if helped_hints > failed_hints:
                return "helped"
            if failed_hints > helped_hints:
                return "didnt_help"

        # Exit code fallback
        if inv.preliminary_status == "executed_ok":
            return "helped"
        if inv.preliminary_status == "executed_fail":
            return "didnt_help"

        return "unclear"

    def _recalculate_pinning(self, agent_id: UUID, used_skill_ids: set[UUID]) -> None:
        """Apply auto-pin and auto-downgrade rules for active skills."""
        active_skills = self._store.list_by_status(agent_id, SkillStatus.active)
        for skill in active_skills:
            # Auto-downgrade: only for auto_pinned (user_pinned is sacred)
            if (
                skill.auto_pinned
                and not skill.user_pinned
                and skill.sessions_since_use >= self._config.auto_downgrade_sessions
            ):
                self._store.update_pinning(skill.id, auto_pinned=False)
                _log.info(
                    "Auto-downgraded skill '%s' (idle %d sessions)",
                    skill.name,
                    skill.sessions_since_use,
                )

            # Auto-pin: skill used enough times in recent window
            # Simplified: check if invocations_count justifies auto-pin
            # (full window tracking would require per-session history query)
            if (
                not skill.auto_pinned
                and not skill.user_pinned
                and skill.invocations_count >= self._config.auto_pin_threshold_uses
            ):
                self._store.update_pinning(skill.id, auto_pinned=True)
                _log.info(
                    "Auto-pinned skill '%s' (%d invocations)", skill.name, skill.invocations_count
                )
