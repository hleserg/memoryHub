"""
CLI for working with Experience Store.

Provides commands for:
- Adding experiences
- Getting experiences by ID
- Adding reframing notes
- Searching experiences
- Previewing salience decay
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from atman.adapters.storage import JsonlExperienceStore
from atman.core.models import KeyMoment, SessionExperience
from atman.core.models.experience import EmotionalDepth
from atman.core.services import ExperienceService
from atman.term import (
    console,
    print_banner,
    print_err,
    print_experience_record,
    print_help_text,
    print_info,
    print_ok,
    print_salience_table,
)


def cmd_add(service: ExperienceService, args: list[str]):
    """Add a new experience from a JSON file."""
    if len(args) < 1:
        print_info("Usage: experience add <json_file>")
        print_info("\nJSON file should contain SessionExperience data.")
        print_info("See fixtures/ directory for examples.")
        return

    json_file = Path(args[0])
    if not json_file.exists():
        print_err(f"File not found: {json_file}")
        return

    try:
        with open(json_file, encoding="utf-8") as f:
            raw = json.load(f)

        if not isinstance(raw, dict):
            raise ValueError("JSON root must be an object")

        concrete_moments: list[KeyMoment] | None = None
        if raw.get("key_moments") and not raw.get("key_moment_ids"):
            concrete_moments = [KeyMoment.model_validate(m) for m in raw["key_moments"]]
            raw = dict(raw)
            raw.pop("key_moments")
            raw["key_moment_ids"] = [str(m.id) for m in concrete_moments]
            raw["avg_emotional_intensity"] = sum(
                m.how_i_felt.emotional_intensity for m in concrete_moments
            ) / len(concrete_moments)
            raw["has_profound_moment"] = any(
                m.how_i_felt.depth == EmotionalDepth.PROFOUND for m in concrete_moments
            )

        experience = SessionExperience.model_validate(raw)
        record = service.create_experience(experience)
        if concrete_moments:
            service.store.store_key_moments(experience.session_id, concrete_moments)

        print_ok("Experience created:")
        print_experience_record(record)

    except Exception as e:
        print_err(f"Error creating experience: {e}")


def cmd_get(service: ExperienceService, args: list[str]):
    """Get an experience by ID."""
    if len(args) < 1:
        print_info("Usage: experience get <experience_id>")
        return

    try:
        experience_id = UUID(args[0])
    except ValueError:
        print_err("Invalid UUID format")
        return

    record = service.get_experience(experience_id)
    if record:
        print_ok("Experience found:")
        print_experience_record(record)
    else:
        print_err("Experience not found")


def cmd_reflect(service: ExperienceService, args: list[str]):
    """Add a reframing note to an experience."""
    if len(args) < 2:
        print_info(
            "Usage: experience reflect <experience_id> <reflection_text> [type] [triggered_by]"
        )
        return

    try:
        experience_id = UUID(args[0])
    except ValueError:
        print_err("Invalid UUID format")
        return

    reflection = args[1]
    reflection_type = args[2] if len(args) > 2 else "general"
    triggered_by = args[3] if len(args) > 3 else None

    record = service.add_reframing_note(
        experience_id=experience_id,
        reflection=reflection,
        reflection_type=reflection_type,
        triggered_by=triggered_by,
    )

    if record:
        print_ok("Reframing note added:")
        print_experience_record(record)
    else:
        print_err("Experience not found")


def cmd_search(service: ExperienceService, args: list[str]):
    """Search experiences by various criteria."""
    if len(args) < 2:
        print_info("Usage: experience search <type> <value> [limit]")
        print_info("\nSearch types:")
        print_info("  session <session_id>          - Search by session ID")
        print_info("  values <value1,value2>        - Search by values touched")
        print_info("  depth <surface|meaningful|profound> - Search by depth")
        print_info("  recent [limit]                - List recent experiences")
        return

    search_type = args[0]
    limit = 10

    try:
        if search_type == "session":
            session_id = UUID(args[1])
            results = service.search_by_session(session_id, limit=limit)

        elif search_type == "values":
            values = [v.strip() for v in args[1].split(",")]
            results = service.search_by_values(values, limit=limit)

        elif search_type == "depth":
            depth = args[1]
            results = service.search_by_depth(depth, limit=limit)

        elif search_type == "recent":
            limit = int(args[1]) if len(args) > 1 else 10
            results = service.list_recent(limit=limit)

        else:
            print_err(f"Unknown search type: {search_type}")
            return

        if results:
            print_ok(f"Found {len(results)} experience(s):")
            for record in results:
                print_experience_record(record, prefix="  ")
        else:
            print_err("No experiences found")

    except Exception as e:
        print_err(f"Error searching: {e}")


def cmd_decay_preview(service: ExperienceService, args: list[str]):
    """Preview salience decay for an experience."""
    if len(args) < 1:
        print_info("Usage: experience decay-preview <experience_id> [days_forward]")
        return

    try:
        experience_id = UUID(args[0])
    except ValueError:
        print_err("Invalid UUID format")
        return

    days_forward = int(args[1]) if len(args) > 1 else 30

    record = service.get_experience(experience_id)
    if not record:
        print_err("Experience not found")
        return

    print_ok("Salience decay preview")
    print_info(f"Experience: {experience_id}")
    print_info(f"Current salience: {record.experience.salience:.4f}\n")

    current_time = datetime.now(UTC)
    rows: list[tuple[int, float]] = []
    for days in [0, 1, 3, 7, 14, 30, 60, 90]:
        if days > days_forward:
            break
        future_time = current_time + timedelta(days=days)
        salience = record.experience.calculate_current_salience(current_time=future_time)
        rows.append((days, salience))
    print_salience_table(rows)


def cmd_help(_service, _args):
    """Print help information."""
    print_help_text("""
Atman Experience Store CLI

Commands:
  experience add <json_file>               Add experience from JSON file
  experience get <experience_id>           Get experience by ID
  experience reflect <id> <text> [type]   Add reframing note
  experience search <type> <value>        Search experiences
  experience decay-preview <id> [days]    Preview salience decay
  experience help                          Show this help
  exit                                     Exit

Search types:
  session <session_id>                     Search by session
  values <val1,val2>                       Search by values touched
  depth <surface|meaningful|profound>      Search by emotional depth
  recent [limit]                           List recent experiences

Examples:
  experience add fixtures/experience1.json
  experience get 123e4567-e89b-12d3-a456-426614174000
  experience reflect <id> "Now I see this differently" growth
  experience search values competence,honesty
  experience search depth profound
  experience decay-preview <id> 30
""")


COMMANDS = {
    "add": cmd_add,
    "get": cmd_get,
    "reflect": cmd_reflect,
    "search": cmd_search,
    "decay-preview": cmd_decay_preview,
    "help": cmd_help,
}


def main():
    """CLI entry point."""
    print_banner("Atman Experience Store CLI", "Type 'experience help' for available commands")

    storage_path = Path.home() / ".atman" / "experiences.jsonl"
    print_info(f"Using storage: {storage_path}\n")

    store = JsonlExperienceStore(storage_path)
    service = ExperienceService(store)

    while True:
        try:
            line = input("atman> ").strip()
            if not line:
                continue

            if line == "exit":
                break

            parts = line.split(maxsplit=2)
            if len(parts) < 1:
                continue

            if parts[0] == "experience" and len(parts) > 1:
                cmd = parts[1]
                args = parts[2].split() if len(parts) > 2 else []
            else:
                cmd = parts[0]
                args = parts[1:] if len(parts) > 1 else []

            if cmd in COMMANDS:
                COMMANDS[cmd](service, args)
            else:
                print_err(f"Unknown command: {cmd}")
                print_info("Type 'experience help' for available commands")

        except KeyboardInterrupt:
            print_info("\nGoodbye!")
            break
        except Exception as e:
            print_err(str(e))
            console.print_exception()


if __name__ == "__main__":
    main()
