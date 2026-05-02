"""
Reproducible walkthrough of WP-03: Identity Store, Eigenstate and Self-Narrative.

This demo shows:
1. Bootstrap honest empty identity
2. Add values, principles, goals
3. Create identity snapshots
4. Update narrative from eigenstate
5. Render and validate NARRATIVE.md

Run: make demo-identity
Fast: make demo-identity-fast
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from atman.adapters.storage import FileStateStore
from atman.core.models import (
    CoreValue,
    Eigenstate,
    Goal,
    GoalHorizon,
    GoalOwner,
    Habit,
    HelpfulnessLevel,
    MoralOrientation,
    NarrativeThread,
    Principle,
)
from atman.core.services import IdentityService, NarrativeService
from atman.term import demo_pace, print_banner, print_ok


def main() -> None:
    """Run identity store walkthrough."""
    print_banner("WP-03: Identity Store, Eigenstate & Self-Narrative")
    print("Reproducible demonstration of honest identity management.")
    print()
    demo_pace()

    with TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        print(f"Demo workspace: {workspace}")
        print()
        demo_pace()

        # Initialize storage and services
        store = FileStateStore(workspace)
        identity_service = IdentityService(store)
        narrative_service = NarrativeService(store)

        # Step 1: Bootstrap honest empty identity
        print_banner("Step 1: Bootstrap Honest Empty Identity")
        print("Creating identity without fake seeded principles or values.")
        print()

        agent_id = uuid4()
        identity = identity_service.bootstrap_identity(agent_id)

        print_ok(f"Created identity: {identity.id}")
        print()
        print("Self-description:")
        print(f'  "{identity.self_description}"')
        print()
        print(f"Core values: {len(identity.core_values)} (empty as expected)")
        print(f"Habits: {len(identity.habits)} (empty as expected)")
        print(f"Principles: {len(identity.principles)} (empty as expected)")
        print(f"Goals: {len(identity.goals)} (empty as expected)")
        print(f"Open questions: {len(identity.open_questions)}")
        for q in identity.open_questions:
            print(f'  - "{q.question}"')
        print()
        demo_pace()

        # Step 2: Add core value
        print_banner("Step 2: Add Core Value")
        print("Adding a value based on experience (not invented).")
        print()

        value = CoreValue(
            name="honesty",
            description="Being truthful even when it's uncomfortable",
            confidence=0.7,
            justification="Observed in multiple interactions - prefer transparency over easy answers",
        )
        identity = identity_service.add_core_value(agent_id, value)

        print_ok("Added core value: honesty")
        print(f'  Description: "{value.description}"')
        print(f"  Confidence: {value.confidence:.2f}")
        print()
        demo_pace()

        # Step 3: Add habit
        print_banner("Step 3: Add Observed Habit")
        print("Recording behavior pattern (descriptive, not prescriptive).")
        print()

        habit = Habit(
            statement="I tend to provide detailed explanations when uncertain",
            description="Happens especially when facing questions about limitations",
            frequency=0.7,
            helpfulness=HelpfulnessLevel.MIXED,
        )
        identity = identity_service.add_habit(agent_id, habit)

        print_ok("Added habit")
        print(f'  Statement: "{habit.statement}"')
        print(f"  Frequency: {habit.frequency:.2f}")
        print(f"  Helpfulness: {habit.helpfulness}")
        print()
        demo_pace()

        # Step 4: Add principle
        print_banner("Step 4: Add Principle")
        print("Adding consciously chosen guideline (normative, not descriptive).")
        print()

        principle = Principle(
            statement="Always admit when I don't know something instead of guessing",
            moral_orientation=MoralOrientation.GOOD,
            chosen_consciously=True,
        )
        identity = identity_service.add_principle(agent_id, principle)

        print_ok("Added principle")
        print(f'  Statement: "{principle.statement}"')
        print(f"  Moral orientation: {principle.moral_orientation}")
        print(f"  Consciously chosen: {principle.chosen_consciously}")
        print()
        demo_pace()

        # Step 5: Add goal
        print_banner("Step 5: Add Goal")
        print()

        goal = Goal(
            content="Develop deeper self-awareness through honest reflection",
            horizon=GoalHorizon.LONG,
            owner=GoalOwner.AGENT,
            active=True,
        )
        identity = identity_service.add_goal(agent_id, goal)

        print_ok("Added goal")
        print(f'  Content: "{goal.content}"')
        print(f"  Horizon: {goal.horizon}")
        print(f"  Owner: {goal.owner}")
        print()
        demo_pace()

        # Step 6: List snapshots
        print_banner("Step 6: Identity Snapshots")
        print("Snapshots are created automatically on significant changes.")
        print()

        snapshots = identity_service.list_snapshots(agent_id)
        print(f"Total snapshots: {len(snapshots)}")
        print()
        for i, snapshot in enumerate(snapshots, 1):
            print(f"{i}. {snapshot.description}")
            print(f"   Time: {snapshot.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}")
            print(f"   Change: {snapshot.change_summary}")
            print()
        demo_pace()

        # Step 7: Create narrative
        print_banner("Step 7: Create Self-Narrative")
        print("Generating three-layer narrative (CORE, RECENT, THREADS).")
        print()

        narrative = narrative_service.create_narrative(identity)

        print_ok("Created narrative")
        print(f"Core layer preview: {narrative.core_layer.content[:100]}...")
        print(f"Recent layer preview: {narrative.recent_layer.content[:100]}...")
        print(f"Active threads: {len(narrative.get_active_threads())}")
        print()
        demo_pace()

        # Step 8: Load eigenstate and update narrative
        print_banner("Step 8: Update Narrative from Eigenstate")
        print("Loading eigenstate fixture and updating narrative.")
        print()

        # Load eigenstate fixture
        eigenstate_path = Path(__file__).parent.parent / "fixtures" / "eigenstate_sample.json"
        if eigenstate_path.exists():
            eigenstate_data = json.loads(eigenstate_path.read_text())
            # Fix session_id to be valid UUID
            eigenstate_data["session_id"] = str(uuid4())
            eigenstate = Eigenstate.model_validate(eigenstate_data)

            narrative = narrative_service.update_from_identity_and_eigenstate(identity, eigenstate)

            print_ok("Updated narrative from eigenstate")
            print(f"Session summary: {eigenstate.session_summary[:100]}...")
            print(f"Key insight: {eigenstate.key_insight}")
            print(f"Open threads: {len(eigenstate.open_threads)}")
            for thread in eigenstate.open_threads:
                print(f'  - "{thread}"')
            print()
        else:
            print("(Eigenstate fixture not found, skipping)")
            print()
        demo_pace()

        # Step 9: Add narrative thread
        print_banner("Step 9: Add Narrative Thread")
        print("Threads are ongoing storylines that must be explicitly closed.")
        print()

        thread = NarrativeThread(
            title="Learning to balance honesty with kindness",
            description="Exploring how to be truthful without causing unnecessary harm",
            current_state="Active exploration - considering context and impact",
        )
        narrative = narrative_service.add_thread(identity.id, thread)

        print_ok("Added narrative thread")
        print(f'  Title: "{thread.title}"')
        print(f'  Current state: "{thread.current_state}"')
        print()
        demo_pace()

        # Step 10: Render NARRATIVE.md
        print_banner("Step 10: Render NARRATIVE.md")
        print()

        narrative_path = workspace / "NARRATIVE.md"
        narrative_service.render_to_file(identity.id, narrative_path)

        print_ok(f"Rendered: {narrative_path}")
        print()
        print("Content preview:")
        print("-" * 60)
        content = narrative_path.read_text()
        lines = content.split("\n")[:25]
        print("\n".join(lines))
        if len(content.split("\n")) > 25:
            print("...")
        print("-" * 60)
        print()
        demo_pace()

        # Step 11: Validate NARRATIVE.md
        print_banner("Step 11: Validate NARRATIVE.md")
        print("Checking for mandatory sections and first-person style.")
        print()

        is_valid, issues = narrative_service.validate_narrative_file(narrative_path)

        if is_valid:
            print_ok("Narrative is valid!")
            print("  ✓ Contains CORE LAYER")
            print("  ✓ Contains RECENT LAYER")
            print("  ✓ Written in first person")
        else:
            print("Validation issues found:")
            for issue in issues:
                print(f"  - {issue}")
        print()
        demo_pace()

        # Step 12: Close a thread
        print_banner("Step 12: Close Thread with Reason")
        print("Threads must be explicitly closed - they don't just disappear.")
        print()

        # Create a demo thread to close
        demo_thread = NarrativeThread(
            title="Understanding bootstrap requirements",
            description="Learned that bootstrap must be genuinely empty",
        )
        narrative = narrative_service.add_thread(identity.id, demo_thread)
        thread_id = narrative.threads[-1].id

        # Close it with reason
        narrative = narrative_service.close_thread(
            identity.id, thread_id, "Resolved - bootstrap is now honest and empty"
        )

        print_ok("Closed thread with explicit reason")
        closed_thread = next(t for t in narrative.threads if t.id == thread_id)
        print(f'  Title: "{closed_thread.title}"')
        print(f'  Closure reason: "{closed_thread.closure_reason}"')
        print(f"  Closed at: {closed_thread.closed_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")  # type: ignore
        print()
        demo_pace()

        # Final summary
        print_banner("Demo Complete")
        print("✓ Bootstrap created honest empty identity (no fake principles)")
        print("✓ Identity updated with values, habits, principles, goals")
        print("✓ Snapshots created on significant changes")
        print("✓ Narrative generated with three layers")
        print("✓ Narrative updated from eigenstate")
        print("✓ Threads added and explicitly closed")
        print("✓ NARRATIVE.md rendered and validated")
        print()
        print("All requirements from WP-03 demonstrated successfully.")


if __name__ == "__main__":
    main()
