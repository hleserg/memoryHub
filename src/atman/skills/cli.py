"""CLI for skill-loop management.

Entry point: atman-skills

Read-only commands (list, show, inspect-invocations) work regardless of
atman.skills.enabled. Write commands return an error when skills are disabled.

All user-facing output uses Rich via :mod:`atman.term` (per AGENTS.md
"Пользовательский вывод в терминале (Rich)"). Bare ``print()`` is forbidden.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING
from uuid import UUID

from rich import box
from rich.panel import Panel
from rich.table import Table

from atman.term import (
    console,
    print_banner,
    print_err,
    print_help_text,
    print_info,
    print_ok,
    print_warn,
)

if TYPE_CHECKING:
    from atman.skills.models import Skill


def _get_store(agent_id: UUID | None = None):
    """Build a PostgresSkillStore or fail with a helpful message.

    ``agent_id`` is required for any RLS-isolated query — pass it through so
    the store binds to the right tenant.
    """
    from atman.config import settings
    from atman.skills.postgres_store import PostgresSkillStore

    return PostgresSkillStore(db_url=settings.database_url, agent_id=agent_id)


def _require_enabled() -> None:
    from atman.config import settings

    if not settings.skills.enabled:
        print_err(
            "skill-loop is disabled (atman.skills.enabled = false). "
            "Enable it in your config to make changes."
        )
        sys.exit(1)


def _parse_agent_id(args: list[str]) -> tuple[UUID, list[str]]:
    """Extract --agent <uuid> from args if present."""
    if "--agent" in args:
        idx = args.index("--agent")
        if idx + 1 >= len(args):
            print_err("--agent requires a UUID argument")
            sys.exit(1)
        agent_id = UUID(args[idx + 1])
        remaining = args[:idx] + args[idx + 2 :]
        return agent_id, remaining
    return UUID(int=0), args  # null UUID as sentinel when not provided


def _pin_label(skill: Skill) -> str:
    if skill.user_pinned:
        return "[term.label]user-pinned[/term.label]"
    if skill.auto_pinned:
        return "[term.dim]auto-pinned[/term.dim]"
    return ""


def _render_skill_table(skills: list[Skill], title: str | None = None) -> Table:
    table = Table(
        title=title,
        box=box.ROUNDED,
        show_header=True,
        header_style="term.label",
        padding=(0, 1),
    )
    table.add_column("Name", style="term.title")
    table.add_column("Status")
    table.add_column("Pin")
    table.add_column("Uses", justify="right")
    table.add_column("OK", justify="right", style="term.ok")
    table.add_column("Fail", justify="right", style="term.err")
    table.add_column("Revision")
    table.add_column("Description", ratio=2)

    for s in skills:
        revision = "[term.warn]needs revision[/term.warn]" if s.revision_needed else ""
        table.add_row(
            s.name,
            s.status.value,
            _pin_label(s),
            str(s.invocations_count),
            str(s.success_count),
            str(s.failure_count),
            revision,
            s.description_short or "",
        )
    return table


def cmd_list(args: list[str]) -> None:
    """atman-skills list [--agent <uuid>] [--status active|disabled|draft]"""
    from atman.skills.models import SkillStatus

    status_filter: SkillStatus | None = None
    if "--status" in args:
        idx = args.index("--status")
        try:
            status_filter = SkillStatus(args[idx + 1])
        except (ValueError, IndexError) as exc:
            print_err(f"--status expects active|disabled|draft (got {exc!s})")
            sys.exit(1)
        args = args[:idx] + args[idx + 2 :]

    agent_id, _ = _parse_agent_id(args)
    store = _get_store(agent_id)

    if status_filter:
        skills = store.list_by_status(agent_id, status_filter)
        title = f"Skills (status = {status_filter.value})"
    else:
        skills = []
        for st in SkillStatus:
            skills.extend(store.list_by_status(agent_id, st))
        title = "Skills (all statuses)"

    if not skills:
        print_warn("No skills found.")
        return

    console.print(_render_skill_table(skills, title=title))


def cmd_show(args: list[str]) -> None:
    """atman-skills show <name> [--agent <uuid>]"""
    if not args:
        print_help_text("Usage: atman-skills show <name> [--agent <uuid>]")
        sys.exit(1)

    name = args[0]
    agent_id, _ = _parse_agent_id(args[1:])
    store = _get_store(agent_id)
    skill = store.get_skill_by_name(agent_id, name)
    if skill is None:
        print_err(f"Skill '{name}' not found.")
        sys.exit(1)

    print_banner(f"Skill: {skill.name}", subtitle=skill.description_short or None)

    summary = Table(show_header=False, box=box.SIMPLE, pad_edge=False, padding=(0, 1, 0, 0))
    summary.add_column(style="term.label", justify="right", min_width=12)
    summary.add_column(ratio=1)
    summary.add_row("Status", skill.status.value)
    summary.add_row("Kind", skill.kind.value)
    summary.add_row("Origin", skill.origin.value)
    summary.add_row("Pinned", f"user={skill.user_pinned}  auto={skill.auto_pinned}")
    summary.add_row(
        "Stats",
        f"invocations={skill.invocations_count}  "
        f"success={skill.success_count}  fail={skill.failure_count}",
    )
    summary.add_row("Idle", f"sessions_since_use={skill.sessions_since_use}")
    summary.add_row(
        "Revision",
        f"needed={skill.revision_needed}  priority={skill.revision_priority}",
    )
    summary.add_row("Manifest", str(skill.manifest_path))
    summary.add_row("Root", str(skill.skill_root))
    console.print(summary)

    if skill.manifest_path.exists():
        body = skill.manifest_path.read_text(encoding="utf-8")[:2000]
        console.print(
            Panel(
                body,
                title="[term.title]SKILL.md (first 2000 chars)[/term.title]",
                border_style="term.border",
                padding=(1, 2),
            )
        )


def cmd_disable(args: list[str]) -> None:
    """atman-skills disable <name> [--agent <uuid>]"""
    _require_enabled()
    if not args:
        print_help_text("Usage: atman-skills disable <name> [--agent <uuid>]")
        sys.exit(1)

    name = args[0]
    agent_id, _ = _parse_agent_id(args[1:])
    store = _get_store(agent_id)
    skill = store.get_skill_by_name(agent_id, name)
    if skill is None:
        print_err(f"Skill '{name}' not found.")
        sys.exit(1)

    from atman.skills.models import SkillStatus

    store.update_skill_status(skill.id, SkillStatus.disabled)
    print_ok(f"Skill '{name}' disabled.")


def cmd_enable(args: list[str]) -> None:
    """atman-skills enable <name> [--agent <uuid>]"""
    _require_enabled()
    if not args:
        print_help_text("Usage: atman-skills enable <name> [--agent <uuid>]")
        sys.exit(1)

    name = args[0]
    agent_id, _ = _parse_agent_id(args[1:])
    store = _get_store(agent_id)
    skill = store.get_skill_by_name(agent_id, name)
    if skill is None:
        print_err(f"Skill '{name}' not found.")
        sys.exit(1)

    from atman.skills.models import SkillStatus

    store.update_skill_status(skill.id, SkillStatus.active)
    print_ok(f"Skill '{name}' enabled (active).")


def cmd_pin(args: list[str]) -> None:
    """atman-skills pin <name> [--agent <uuid>]"""
    _require_enabled()
    if not args:
        print_help_text("Usage: atman-skills pin <name> [--agent <uuid>]")
        sys.exit(1)

    name = args[0]
    agent_id, _ = _parse_agent_id(args[1:])
    store = _get_store(agent_id)
    skill = store.get_skill_by_name(agent_id, name)
    if skill is None:
        print_err(f"Skill '{name}' not found.")
        sys.exit(1)

    store.update_pinning(skill.id, user_pinned=True)
    print_ok(f"Skill '{name}' user-pinned.")


def cmd_unpin(args: list[str]) -> None:
    """atman-skills unpin <name> [--agent <uuid>]"""
    _require_enabled()
    if not args:
        print_help_text("Usage: atman-skills unpin <name> [--agent <uuid>]")
        sys.exit(1)

    name = args[0]
    agent_id, _ = _parse_agent_id(args[1:])
    store = _get_store(agent_id)
    skill = store.get_skill_by_name(agent_id, name)
    if skill is None:
        print_err(f"Skill '{name}' not found.")
        sys.exit(1)

    store.update_pinning(skill.id, user_pinned=False)
    print_ok(f"Skill '{name}' unpinned (user_pinned=false).")


def cmd_archive(args: list[str]) -> None:
    """atman-skills archive <name> [--agent <uuid>] — soft-disable, keeps data."""
    _require_enabled()
    # archive = disable for now (no separate archived status in schema)
    cmd_disable(args)
    print_info("(archived = disabled; files and history preserved)")


def cmd_inspect_invocations(args: list[str]) -> None:
    """atman-skills inspect-invocations <name> [--agent <uuid>] [--last N]"""
    if not args:
        print_help_text(
            "Usage: atman-skills inspect-invocations <name> [--agent <uuid>] [--last N]"
        )
        sys.exit(1)

    last_n = 10
    if "--last" in args:
        idx = args.index("--last")
        try:
            last_n = int(args[idx + 1])
        except (ValueError, IndexError) as exc:
            print_err(f"--last expects an integer (got {exc!s})")
            sys.exit(1)
        args = args[:idx] + args[idx + 2 :]

    name = args[0]
    agent_id, _ = _parse_agent_id(args[1:])
    store = _get_store(agent_id)
    skill = store.get_skill_by_name(agent_id, name)
    if skill is None:
        print_err(f"Skill '{name}' not found.")
        sys.exit(1)

    print_banner(f"Invocations: {skill.name}", subtitle=f"(last {last_n})")
    print_info(f"Skill ID: {skill.id}")
    # Help text — not an executed query. The interpolated values are a UUID
    # (validated by Pydantic upstream) and an int parsed from CLI args.
    print_help_text(
        "Full invocation history requires a direct DB query:\n"
        "  SELECT * FROM public.skill_invocations\n"
        f"   WHERE skill_id = '{skill.id}'\n"  # nosec B608
        f"   ORDER BY started_at DESC LIMIT {last_n};"  # nosec B608
    )


def cmd_force_revise(args: list[str]) -> None:
    """atman-skills force-revise <name> [--agent <uuid>]"""
    _require_enabled()
    if not args:
        print_help_text("Usage: atman-skills force-revise <name> [--agent <uuid>]")
        sys.exit(1)

    name = args[0]
    agent_id, _ = _parse_agent_id(args[1:])
    store = _get_store(agent_id)
    skill = store.get_skill_by_name(agent_id, name)
    if skill is None:
        print_err(f"Skill '{name}' not found.")
        sys.exit(1)

    store.set_revision_needed(skill.id, priority_bump=5)
    print_ok(f"Skill '{name}' flagged for revision (priority +5).")


def cmd_revise(args: list[str]) -> None:
    """atman-skills revise --agent <uuid> [--max N] [--dry-run]"""
    _require_enabled()
    max_skills = 3
    dry_run = False
    rest = list(args)
    if "--max" in rest:
        idx = rest.index("--max")
        try:
            max_skills = int(rest[idx + 1])
        except (ValueError, IndexError) as exc:
            print_err(f"--max expects an integer (got {exc!s})")
            sys.exit(1)
        rest = rest[:idx] + rest[idx + 2 :]
    if "--dry-run" in rest:
        rest.remove("--dry-run")
        dry_run = True

    agent_id, _ = _parse_agent_id(rest)
    if agent_id == UUID(int=0):
        print_err("--agent <uuid> is required for revise")
        sys.exit(1)

    store = _get_store(agent_id)

    # By default the CLI wires the NoopSkillReviser — real LLM reviser is
    # configured elsewhere (see SkillRevisionService docstring). The CLI is
    # still useful with the noop: it lists candidates and applies dry-run
    # bookkeeping without hitting any LLM.
    from atman.skills.revision import NoopSkillReviser, SkillRevisionService

    service = SkillRevisionService(store=store, reviser=NoopSkillReviser())
    outcomes = service.revise_pending(agent_id, max_skills=max_skills, dry_run=dry_run)

    if not outcomes:
        print_info("No skills currently flagged for revision.")
        return

    for outcome in outcomes:
        if outcome.revised:
            print_ok(
                f"Revised '{outcome.skill_name}' → version {outcome.new_version} "
                f"(backup at {outcome.backup_path}) — {outcome.rationale}"
            )
        else:
            print_info(
                f"Skipped '{outcome.skill_name}' "
                f"(new_version={outcome.new_version or 'n/a'}): {outcome.rationale}"
            )


def cmd_install_external(args: list[str]) -> None:
    """atman-skills install-external <source> --agent <uuid> [--name N] [--dry-run] [--yes]

    Sources:
      /local/path/to/skill/        — directory containing SKILL.md
      /local/path/to/skill.zip     — local zip archive
      https://example.com/x.zip    — HTTPS zip archive
    """
    from pathlib import Path

    _require_enabled()
    if not args:
        print_help_text(
            "Usage: atman-skills install-external <source> --agent <uuid> "
            "[--name <override>] [--dry-run] [--yes]"
        )
        sys.exit(1)

    rest = list(args)
    name_override: str | None = None
    dry_run = False
    assume_yes = False
    if "--name" in rest:
        idx = rest.index("--name")
        try:
            name_override = rest[idx + 1]
        except IndexError:
            print_err("--name requires a value")
            sys.exit(1)
        rest = rest[:idx] + rest[idx + 2 :]
    if "--dry-run" in rest:
        rest.remove("--dry-run")
        dry_run = True
    if "--yes" in rest or "-y" in rest:
        rest = [a for a in rest if a not in ("--yes", "-y")]
        assume_yes = True

    if not rest:
        print_err("Missing <source>")
        sys.exit(1)
    source = rest[0]
    agent_id, _ = _parse_agent_id(rest[1:])
    if agent_id == UUID(int=0):
        print_err("--agent <uuid> is required for install-external")
        sys.exit(1)

    from atman.config import settings as _settings
    from atman.skills.installer import (
        InstallResult,
        SkillInstallError,
        install_external,
    )

    store = _get_store(agent_id)
    agents_root = Path(_settings.skills.skills_root).expanduser()

    # Confirmation when the manifest declares a runtime_entry — those skills
    # execute code on invoke, so the operator must consent. The simplest path
    # is to do a dry-run first so we can surface runtime_entry status before
    # any disk/DB writes happen.
    try:
        preview = install_external(
            source,
            agent_id,
            store=store,
            agents_root=agents_root,
            name_override=name_override,
            dry_run=True,
        )
    except SkillInstallError as exc:
        print_err(str(exc))
        sys.exit(1)

    _render_install_preview(preview)

    if preview.runtime_warning and not assume_yes and not dry_run:
        print_warn(
            "This skill declares runtime_entry and will execute code when invoked. "
            "Re-run with --yes to confirm installation, or --dry-run to inspect only."
        )
        sys.exit(2)

    if dry_run:
        print_info("(dry-run) no files written, no DB row created.")
        return

    try:
        result: InstallResult = install_external(
            source,
            agent_id,
            store=store,
            agents_root=agents_root,
            name_override=name_override,
            dry_run=False,
        )
    except SkillInstallError as exc:
        print_err(str(exc))
        sys.exit(1)

    print_ok(
        f"Installed '{result.manifest.name}' "
        f"(skill_id={result.skill_id}) at {result.target_path}"
    )


def _render_install_preview(preview) -> None:
    """Render the parsed manifest before any side effects fire."""
    from rich import box
    from rich.table import Table

    table = Table(show_header=False, box=box.SIMPLE, pad_edge=False, padding=(0, 1, 0, 0))
    table.add_column(style="term.label", justify="right", min_width=14)
    table.add_column(ratio=1)
    table.add_row("Name", preview.manifest.name)
    table.add_row("Version", preview.manifest.version)
    table.add_row("Kind", preview.manifest.kind.value)
    table.add_row("Origin", preview.manifest.origin.value)
    table.add_row("Description", preview.manifest.description)
    table.add_row("Runtime entry", preview.manifest.runtime_entry or "(none)")
    table.add_row("Sandbox", preview.manifest.runtime_sandbox)
    table.add_row("Target", str(preview.target_path))
    console.print(table)


_COMMANDS = {
    "list": cmd_list,
    "show": cmd_show,
    "disable": cmd_disable,
    "enable": cmd_enable,
    "pin": cmd_pin,
    "unpin": cmd_unpin,
    "archive": cmd_archive,
    "inspect-invocations": cmd_inspect_invocations,
    "force-revise": cmd_force_revise,
    "install-external": cmd_install_external,
    "revise": cmd_revise,
}

_HELP = """atman-skills — skill-loop management

Commands:
  list [--agent <uuid>] [--status active|disabled|draft]
  show <name> [--agent <uuid>]
  disable <name> [--agent <uuid>]
  enable <name> [--agent <uuid>]
  pin <name> [--agent <uuid>]
  unpin <name> [--agent <uuid>]
  archive <name> [--agent <uuid>]
  inspect-invocations <name> [--agent <uuid>] [--last N]
  force-revise <name> [--agent <uuid>]
  install-external <source> --agent <uuid> [--name <override>] [--dry-run] [--yes]
  revise --agent <uuid> [--max N] [--dry-run]

Read-only commands (list, show, inspect-invocations) work even when
atman.skills.enabled = false.
"""


def main() -> None:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print_help_text(_HELP)
        sys.exit(0)

    cmd = args[0]
    rest = args[1:]

    if cmd not in _COMMANDS:
        print_err(f"Unknown command: {cmd}")
        print_help_text(_HELP)
        sys.exit(1)

    _COMMANDS[cmd](rest)


if __name__ == "__main__":
    main()
