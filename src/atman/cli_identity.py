"""
CLI for Identity Store operations.

Commands:
- identity init: Bootstrap a new identity
- identity show: Display current identity
- identity snapshot: Create a snapshot
- narrative render: Render NARRATIVE.md
- narrative validate: Validate NARRATIVE.md
"""

import sys
from pathlib import Path
from uuid import UUID, uuid4

from atman.adapters.storage import FileStateStore
from atman.core.services import IdentityService, NarrativeService
from atman.term import print_banner, print_err, print_ok


def cmd_identity_init(workspace: Path, agent_id: UUID | None = None) -> None:
    """Bootstrap a new identity."""
    print_banner("Identity Init")

    if agent_id is None:
        agent_id = uuid4()

    store = FileStateStore(workspace)
    service = IdentityService(store)

    # Check if identity already exists
    existing = service.get_identity(agent_id)
    if existing is not None:
        print_err(f"Identity {agent_id} already exists in {workspace}")
        print_err("Use a different workspace or agent ID.")
        sys.exit(1)

    # Bootstrap
    identity = service.bootstrap_identity(agent_id)

    print_ok(f"Created identity: {identity.id}")
    print_ok(f"Workspace: {workspace}")
    print()
    print(f"Self-description: {identity.self_description}")
    print()
    print(f"Open questions: {len(identity.open_questions)}")
    for q in identity.open_questions:
        print(f"  - {q.question}")


def cmd_identity_show(workspace: Path, agent_id: UUID) -> None:
    """Show current identity."""
    print_banner("Identity")

    store = FileStateStore(workspace)
    service = IdentityService(store)

    identity = service.get_identity(agent_id)
    if identity is None:
        print_err(f"Identity {agent_id} not found in {workspace}")
        sys.exit(1)

    print(f"ID: {identity.id}")
    print(f"Created: {identity.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"Updated: {identity.updated_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print()

    print("Self-description:")
    print(f"  {identity.self_description}")
    print()

    print(f"Core values: {len(identity.core_values)}")
    for value in identity.core_values:
        print(f"  - {value.name}: {value.description}")
        print(f"    Confidence: {value.confidence:.2f}")

    print()
    print(f"Habits: {len(identity.habits)}")
    for habit in identity.habits:
        print(f"  - {habit.statement}")
        print(f"    Frequency: {habit.frequency:.2f}, Helpfulness: {habit.helpfulness}")

    print()
    print(f"Principles: {len(identity.principles)}")
    for principle in identity.principles:
        print(f"  - {principle.statement}")
        print(
            f"    Moral: {principle.moral_orientation}, Conscious: {principle.chosen_consciously}"
        )

    print()
    print(f"Goals: {len(identity.goals)}")
    for goal in identity.goals:
        status = "active" if goal.active else "inactive"
        print(f"  - {goal.content}")
        print(f"    Horizon: {goal.horizon}, Owner: {goal.owner}, Status: {status}")

    print()
    print(f"Open questions: {len(identity.open_questions)}")
    for question in identity.open_questions:
        print(f"  - {question.question}")

    print()
    print(f"Emotional baseline: {identity.emotional_baseline:.2f}")


def cmd_identity_snapshot(workspace: Path, agent_id: UUID, description: str) -> None:
    """Create identity snapshot."""
    print_banner("Create Snapshot")

    store = FileStateStore(workspace)
    service = IdentityService(store)

    identity = service.get_identity(agent_id)
    if identity is None:
        print_err(f"Identity {agent_id} not found in {workspace}")
        sys.exit(1)

    snapshot = service.create_snapshot(agent_id, description)

    print_ok(f"Created snapshot: {snapshot.id}")
    print(f"Description: {snapshot.description}")
    print(f"Timestamp: {snapshot.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}")


def cmd_narrative_render(
    workspace: Path, agent_id: UUID, eigenstate_path: Path | None = None
) -> None:
    """Render NARRATIVE.md."""
    print_banner("Render Narrative")

    store = FileStateStore(workspace)
    identity_service = IdentityService(store)
    narrative_service = NarrativeService(store)

    identity = identity_service.get_identity(agent_id)
    if identity is None:
        print_err(f"Identity {agent_id} not found in {workspace}")
        sys.exit(1)

    # Load eigenstate if provided
    eigenstate = None
    if eigenstate_path is not None:
        import json

        from atman.core.models import Eigenstate

        data = json.loads(eigenstate_path.read_text(encoding="utf-8"))
        eigenstate = Eigenstate.model_validate(data)

    # Update narrative
    narrative_service.update_from_identity_and_eigenstate(identity, eigenstate)

    # Render to file
    output_path = workspace / "NARRATIVE.md"
    narrative_service.render_to_file(identity.id, output_path)

    print_ok(f"Rendered narrative to: {output_path}")
    print()
    print("Content preview:")
    print("-" * 60)
    content = output_path.read_text(encoding="utf-8")
    lines = content.split("\n")[:20]
    print("\n".join(lines))
    if len(content.split("\n")) > 20:
        print("...")


def cmd_narrative_validate(narrative_path: Path) -> None:
    """Validate NARRATIVE.md."""
    print_banner("Validate Narrative")

    # Create dummy workspace just for validation service
    store = FileStateStore(Path("/tmp/dummy"))
    service = NarrativeService(store)

    is_valid, issues = service.validate_narrative_file(narrative_path)

    if is_valid:
        print_ok(f"Narrative is valid: {narrative_path}")
    else:
        print_err(f"Narrative validation failed: {narrative_path}")
        print()
        print("Issues found:")
        for issue in issues:
            print(f"  - {issue}")
        sys.exit(1)


def main() -> None:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Identity Store CLI")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # identity init
    init_parser = subparsers.add_parser("init", help="Bootstrap a new identity")
    init_parser.add_argument("--workspace", type=Path, required=True, help="Workspace directory")
    init_parser.add_argument("--agent-id", type=UUID, help="Agent ID (optional, will generate)")

    # identity show
    show_parser = subparsers.add_parser("show", help="Show current identity")
    show_parser.add_argument("--workspace", type=Path, required=True, help="Workspace directory")
    show_parser.add_argument("--agent-id", type=UUID, required=True, help="Agent ID")

    # identity snapshot
    snapshot_parser = subparsers.add_parser("snapshot", help="Create identity snapshot")
    snapshot_parser.add_argument(
        "--workspace", type=Path, required=True, help="Workspace directory"
    )
    snapshot_parser.add_argument("--agent-id", type=UUID, required=True, help="Agent ID")
    snapshot_parser.add_argument(
        "--description", type=str, required=True, help="Snapshot description"
    )

    # narrative render
    render_parser = subparsers.add_parser("render", help="Render NARRATIVE.md")
    render_parser.add_argument("--workspace", type=Path, required=True, help="Workspace directory")
    render_parser.add_argument("--agent-id", type=UUID, required=True, help="Agent ID")
    render_parser.add_argument("--eigenstate", type=Path, help="Path to eigenstate.json (optional)")

    # narrative validate
    validate_parser = subparsers.add_parser("validate", help="Validate NARRATIVE.md")
    validate_parser.add_argument("narrative_path", type=Path, help="Path to NARRATIVE.md file")

    args = parser.parse_args()

    if args.command == "init":
        cmd_identity_init(args.workspace, args.agent_id)
    elif args.command == "show":
        cmd_identity_show(args.workspace, args.agent_id)
    elif args.command == "snapshot":
        cmd_identity_snapshot(args.workspace, args.agent_id, args.description)
    elif args.command == "render":
        cmd_narrative_render(args.workspace, args.agent_id, args.eigenstate)
    elif args.command == "validate":
        cmd_narrative_validate(args.narrative_path)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
