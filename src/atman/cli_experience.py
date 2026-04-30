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
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

from atman.adapters.storage import JsonlExperienceStore
from atman.core.models import (
    ContextHalo,
    EmotionalDepth,
    ExperienceRecord,
    FeltSense,
    KeyMoment,
    SessionExperience,
)
from atman.core.services import ExperienceService


def print_experience(record: ExperienceRecord, prefix: str = ""):
    """Print experience information."""
    exp = record.experience
    print(f"{prefix}ID: {exp.id}")
    print(f"{prefix}Session: {exp.session_id}")
    print(f"{prefix}Recorded: {exp.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{prefix}Recorded by: {exp.recorded_by}")
    print(f"{prefix}Importance: {exp.importance:.2f}")
    print(f"{prefix}Salience: {exp.salience:.2f}")
    print(f"{prefix}Access count: {exp.access_count}")
    print(f"{prefix}Last accessed: {exp.last_accessed_at.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{prefix}Incomplete coloring: {exp.incomplete_coloring}")
    
    print(f"\n{prefix}Key Moments ({len(exp.key_moments)}):")
    for i, moment in enumerate(exp.key_moments, 1):
        print(f"{prefix}  [{i}] {moment.what_happened}")
        print(f"{prefix}      When: {moment.when.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{prefix}      Felt: valence={moment.how_i_felt.emotional_valence:.2f}, "
              f"intensity={moment.how_i_felt.emotional_intensity:.2f}, "
              f"depth={moment.how_i_felt.depth.value}")
        print(f"{prefix}      Why it matters: {moment.why_it_matters}")
        if moment.values_touched:
            print(f"{prefix}      Values: {', '.join(moment.values_touched)}")
        if moment.principles_confirmed:
            print(f"{prefix}      Confirmed: {', '.join(moment.principles_confirmed)}")
        if moment.principles_questioned:
            print(f"{prefix}      Questioned: {', '.join(moment.principles_questioned)}")
        if moment.what_changed:
            print(f"{prefix}      Changed: {moment.what_changed}")
        print()
    
    if exp.reframing_notes:
        print(f"{prefix}Reframing Notes ({len(exp.reframing_notes)}):")
        for i, note in enumerate(exp.reframing_notes, 1):
            print(f"{prefix}  [{i}] {note.added_at.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{prefix}      Type: {note.reflection_type}")
            print(f"{prefix}      Reflection: {note.reflection}")
            if note.triggered_by:
                print(f"{prefix}      Triggered by: {note.triggered_by}")
            print()


def cmd_add(service: ExperienceService, args: list[str]):
    """Add a new experience from a JSON file."""
    if len(args) < 1:
        print("Usage: experience add <json_file>")
        print("\nJSON file should contain SessionExperience data.")
        print("See fixtures/ directory for examples.")
        return
    
    json_file = Path(args[0])
    if not json_file.exists():
        print(f"✗ Error: File not found: {json_file}")
        return
    
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        experience = SessionExperience.model_validate(data)
        record = service.create_experience(experience)
        
        print("✓ Experience created:")
        print_experience(record)
        
    except Exception as e:
        print(f"✗ Error creating experience: {e}")


def cmd_get(service: ExperienceService, args: list[str]):
    """Get an experience by ID."""
    if len(args) < 1:
        print("Usage: experience get <experience_id>")
        return
    
    try:
        experience_id = UUID(args[0])
    except ValueError:
        print("✗ Error: Invalid UUID format")
        return
    
    record = service.get_experience(experience_id)
    if record:
        print("✓ Experience found:")
        print_experience(record)
    else:
        print("✗ Experience not found")


def cmd_reflect(service: ExperienceService, args: list[str]):
    """Add a reframing note to an experience."""
    if len(args) < 2:
        print("Usage: experience reflect <experience_id> <reflection_text> [type] [triggered_by]")
        return
    
    try:
        experience_id = UUID(args[0])
    except ValueError:
        print("✗ Error: Invalid UUID format")
        return
    
    reflection = args[1]
    reflection_type = args[2] if len(args) > 2 else "general"
    triggered_by = args[3] if len(args) > 3 else None
    
    record = service.add_reframing_note(
        experience_id=experience_id,
        reflection=reflection,
        reflection_type=reflection_type,
        triggered_by=triggered_by
    )
    
    if record:
        print("✓ Reframing note added:")
        print_experience(record)
    else:
        print("✗ Experience not found")


def cmd_search(service: ExperienceService, args: list[str]):
    """Search experiences by various criteria."""
    if len(args) < 2:
        print("Usage: experience search <type> <value> [limit]")
        print("\nSearch types:")
        print("  session <session_id>          - Search by session ID")
        print("  values <value1,value2>        - Search by values touched")
        print("  depth <surface|meaningful|profound> - Search by depth")
        print("  recent [limit]                - List recent experiences")
        return
    
    search_type = args[0]
    limit = 10
    
    try:
        if search_type == "session":
            session_id = UUID(args[1])
            results = service.search_by_session(session_id, limit=limit)
        
        elif search_type == "values":
            values = [v.strip() for v in args[1].split(',')]
            results = service.search_by_values(values, limit=limit)
        
        elif search_type == "depth":
            depth = args[1]
            results = service.search_by_depth(depth, limit=limit)
        
        elif search_type == "recent":
            limit = int(args[1]) if len(args) > 1 else 10
            results = service.list_recent(limit=limit)
        
        else:
            print(f"✗ Unknown search type: {search_type}")
            return
        
        if results:
            print(f"✓ Found {len(results)} experience(s):\n")
            for record in results:
                print_experience(record, prefix="  ")
                print()
        else:
            print("✗ No experiences found")
    
    except Exception as e:
        print(f"✗ Error searching: {e}")


def cmd_decay_preview(service: ExperienceService, args: list[str]):
    """Preview salience decay for an experience."""
    if len(args) < 1:
        print("Usage: experience decay-preview <experience_id> [days_forward]")
        return
    
    try:
        experience_id = UUID(args[0])
    except ValueError:
        print("✗ Error: Invalid UUID format")
        return
    
    days_forward = int(args[1]) if len(args) > 1 else 30
    
    record = service.get_experience(experience_id)
    if not record:
        print("✗ Experience not found")
        return
    
    print("✓ Salience decay preview:")
    print(f"Experience: {experience_id}")
    print(f"Current salience: {record.experience.salience:.4f}\n")
    
    print("Days  | Salience")
    print("------|----------")
    
    current_time = datetime.now(timezone.utc)
    for days in [0, 1, 3, 7, 14, 30, 60, 90]:
        if days > days_forward:
            break
        future_time = current_time + timedelta(days=days)
        salience = record.experience.calculate_current_salience(current_time=future_time)
        print(f"{days:5d} | {salience:.4f}")


def cmd_help(_service, _args):
    """Print help information."""
    print("""
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
    'add': cmd_add,
    'get': cmd_get,
    'reflect': cmd_reflect,
    'search': cmd_search,
    'decay-preview': cmd_decay_preview,
    'help': cmd_help,
}


def main():
    """CLI entry point."""
    print("Atman Experience Store CLI")
    print("Type 'experience help' for available commands\n")
    
    # Setup storage
    storage_path = Path.home() / '.atman' / 'experiences.jsonl'
    print(f"Using storage: {storage_path}\n")
    
    store = JsonlExperienceStore(storage_path)
    service = ExperienceService(store)
    
    # REPL
    while True:
        try:
            line = input("atman> ").strip()
            if not line:
                continue
            
            if line == 'exit':
                break
            
            parts = line.split(maxsplit=2)
            if len(parts) < 1:
                continue
            
            # Handle "experience <command>" format
            if parts[0] == 'experience' and len(parts) > 1:
                cmd = parts[1]
                args = parts[2].split() if len(parts) > 2 else []
            else:
                cmd = parts[0]
                args = parts[1:] if len(parts) > 1 else []
            
            if cmd in COMMANDS:
                COMMANDS[cmd](service, args)
            else:
                print(f"✗ Unknown command: {cmd}")
                print("Type 'experience help' for available commands")
        
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"✗ Error: {e}")
            import traceback
            traceback.print_exc()


if __name__ == '__main__':
    main()
