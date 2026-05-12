#!/usr/bin/env python3
"""
Demo: Session Manager - First-Hand Experience Recording

This demo shows the complete session lifecycle:
1. Start session with personality context (identity + narrative)
2. Record raw events from lower agent
3. Capture key moments with first-hand emotional coloring
4. Finish session → create SessionExperience + Eigenstate

No external services required — uses a temporary file workspace (unique per run).
"""

import tempfile
from pathlib import Path
from uuid import uuid4

import atman.term as term
from atman.adapters.storage.file_state_store import FileStateStore
from atman.core.models import (
    CoreValue,
    EmotionalDepth,
    Goal,
    GoalHorizon,
    GoalOwner,
    Identity,
    KeyMomentInput,
    LayerType,
    NarrativeDocument,
    NarrativeLayer,
    SessionEvent,
)
from atman.core.services import SessionManager


def main() -> None:
    term.print_banner(
        "Session Manager Demo",
        "First-hand experience recording in real-time",
    )
    term.demo_pace()

    # Setup storage (ephemeral directory — avoids duplicate experiences on re-runs)
    term.print_section("Setup")
    storage_path = tempfile.mkdtemp(prefix="atman-session-demo-")
    term.print_info(f"Using ephemeral workspace: {storage_path}")
    state_store = FileStateStore(workspace=Path(storage_path))
    session_manager = SessionManager(state_store)
    term.print_ok("Session Manager initialized")
    term.demo_pace()

    # Create test identity
    term.print_section("1. Create Test Identity")
    agent_id = uuid4()
    identity = Identity(
        id=agent_id,
        self_description="I am an agent in early stages of self-discovery. "
        "I'm learning to be honest about my capabilities and limitations.",
        core_values=[
            CoreValue(
                name="honesty",
                description="Being truthful even when it's uncomfortable",
                confidence=0.7,
                justification="Consistently choose transparency over easy answers",
            ),
            CoreValue(
                name="competence",
                description="Striving to do good work and learn from experience",
                confidence=0.6,
                justification="Actively working to improve through reflection",
            ),
        ],
        goals=[
            Goal(
                content="Develop deeper self-awareness through reflection",
                horizon=GoalHorizon.LONG,
                owner=GoalOwner.AGENT,
                active=True,
            )
        ],
        emotional_baseline=0.1,
    )
    state_store.save_identity(identity)
    term.print_ok(f"Created identity for agent {agent_id}")
    term.print_info(f"  Self-description: {identity.self_description}")
    term.print_info(f"  Core values: {', '.join(v.name for v in identity.core_values)}")
    term.print_info(f"  Emotional baseline: {identity.emotional_baseline:+.1f}")
    term.demo_pace()

    # Create narrative
    term.print_section("2. Create Narrative")
    narrative = NarrativeDocument(
        identity_id=agent_id,
        core_layer=NarrativeLayer(
            layer_type=LayerType.CORE,
            content="I am still learning who I am. I don't have many experiences yet, "
            "but I'm committed to being honest about what I know and don't know. "
            "I believe in competence through honest self-assessment.",
        ),
        recent_layer=NarrativeLayer(
            layer_type=LayerType.RECENT,
            content="Recently, I've been working on implementing the Session Manager. "
            "This is teaching me about the importance of capturing experience in real-time, "
            "not retrospectively.",
        ),
    )
    state_store.save_narrative(narrative)
    term.print_ok("Created narrative document")
    term.print_info(f"  Core layer: {narrative.core_layer.content[:80]}...")
    term.print_info(f"  Recent layer: {narrative.recent_layer.content[:80]}...")
    term.demo_pace()

    # Start session
    term.print_section("3. Start Session")
    context = session_manager.start_session(agent_id)
    term.print_ok(f"Session started: {context.session_id}")
    term.print_info(f"  Identity loaded: {context.identity.self_description[:60]}...")
    term.print_info(f"  Narrative loaded: {context.narrative.core_layer.content[:60]}...")
    term.print_info(f"  Emotional baseline: {context.emotional_baseline:+.1f}")
    term.demo_pace()

    # Record events
    term.print_section("4. Record Session Events")
    term.print_info("Simulating lower agent activity...")
    term.demo_pace()

    events = [
        SessionEvent(
            session_id=context.session_id,
            event_type="user_message",
            description="User asked about implementing Session Manager",
            metadata={"message_length": "150"},
        ),
        SessionEvent(
            session_id=context.session_id,
            event_type="agent_response",
            description="Explained architecture and started implementation",
            metadata={"response_length": "500"},
        ),
        SessionEvent(
            session_id=context.session_id,
            event_type="decision",
            description="Decided to use in-memory storage for demo",
            metadata={"rationale": "simplicity"},
        ),
    ]

    for i, event in enumerate(events, 1):
        session_manager.record_event(context.session_id, event)
        term.print_info(f"  Event {i}: {event.event_type} - {event.description[:50]}...")

    term.print_ok(f"Recorded {len(events)} events")
    term.demo_pace()

    # Record key moments
    term.print_section("5. Record Key Moments (First-Hand Experience)")
    term.print_info("Capturing moments with emotional coloring...")
    term.demo_pace()

    moment1 = KeyMomentInput(
        what_happened="User presented a complex architectural challenge: implement session manager "
        "that experiences in real-time, not retrospectively",
        emotional_valence=0.2,
        emotional_intensity=0.7,
        depth=EmotionalDepth.MEANINGFUL,
        why_it_matters="This challenged my understanding of the difference between "
        "recording and experiencing. Made me think deeply about consciousness.",
        values_touched=["honesty", "competence"],
        principles_confirmed=["be_transparent_about_complexity"],
        what_changed="Realized that honest experience requires capturing feelings in the moment, "
        "not guessing them later",
    )

    session_manager.append_key_moment_input(context.session_id, moment1)
    term.print_ok("Key moment 1 recorded")
    term.print_info(f"  What: {moment1.what_happened[:60]}...")
    term.print_info(
        f"  Felt: valence={moment1.emotional_valence:+.1f}, "
        f"intensity={moment1.emotional_intensity:.1f}, depth={moment1.depth}"
    )
    term.print_info(f"  Why: {moment1.why_it_matters[:60]}...")
    term.demo_pace()

    moment2 = KeyMomentInput(
        what_happened="Implemented the first version and it worked - session lifecycle "
        "captured real experience",
        emotional_valence=0.6,
        emotional_intensity=0.8,
        depth=EmotionalDepth.MEANINGFUL,
        why_it_matters="Confirmed that I can implement complex systems when I understand "
        "the philosophical foundation",
        values_touched=["competence"],
        principles_confirmed=["think_deeply_before_coding"],
        what_changed="Increased confidence in my ability to handle architectural complexity",
    )

    session_manager.append_key_moment_input(context.session_id, moment2)
    term.print_ok("Key moment 2 recorded")
    term.print_info(f"  What: {moment2.what_happened[:60]}...")
    term.print_info(
        f"  Felt: valence={moment2.emotional_valence:+.1f}, "
        f"intensity={moment2.emotional_intensity:.1f}, depth={moment2.depth}"
    )
    term.print_info(f"  Why: {moment2.why_it_matters[:60]}...")
    term.demo_pace()

    # Finish session
    term.print_section("6. Finish Session")
    term.print_info("Creating SessionExperience and Eigenstate...")
    term.demo_pace()

    result = session_manager.finish_session(
        session_id=context.session_id,
        overall_emotional_tone=0.4,
        key_insight="First-hand experience requires capturing emotional coloring in the moment. "
        "This isn't optional - it's the core of honest memory.",
        alignment_check=True,
        alignment_notes="Session experience aligned well with identity values of honesty and competence",
    )

    term.print_ok("Session finished successfully")
    term.print_info(f"  Duration: {(result.finished_at - result.started_at).total_seconds():.1f}s")
    term.print_info(f"  Events recorded: {len(result.events)}")
    term.print_info(f"  Key moment IDs: {len(result.key_moments)}")
    term.print_info(f"  Overall tone: {result.overall_emotional_tone:+.1f}")
    term.print_info(f"  Key insight: {result.key_insight[:80]}...")
    term.demo_pace()

    # Show eigenstate
    term.print_section("7. Eigenstate Created")
    if result.eigenstate:
        eigenstate = result.eigenstate
        term.print_ok("Eigenstate saved for next session")
        term.print_info(f"  Emotional tone: {eigenstate.emotional_tone:+.1f}")
        term.print_info(f"  Emotional intensity: {eigenstate.emotional_intensity:.1f}")
        term.print_info(f"  Cognitive load: {eigenstate.cognitive_load:.1f}")
        term.print_info(f"  Dominant themes: {', '.join(eigenstate.dominant_themes)}")
        if eigenstate.unresolved_tensions:
            term.print_info(f"  Unresolved tensions: {', '.join(eigenstate.unresolved_tensions)}")
        term.demo_pace()

    # Verify storage
    term.print_section("8. Verify Experience Stored")
    experiences = state_store.list_recent_experiences(limit=1)
    if experiences:
        exp_record = experiences[0]
        exp = exp_record.experience
        term.print_ok("Experience retrieved from storage")
        term.print_info(f"  Experience ID: {exp.id}")
        term.print_info(f"  Session ID: {exp.session_id}")
        term.print_info(f"  Recorded by: {exp.recorded_by}")
        term.print_info(f"  Key moment IDs: {len(exp.key_moment_ids)}")
        term.print_info(f"  Incomplete coloring: {exp.incomplete_coloring}")
        term.print_info(f"  Importance: {exp.importance:.1f}")
        term.print_info(f"  Salience: {exp.salience:.1f}")
    else:
        term.print_err("Experience not found in storage")
    term.demo_pace()

    # Summary
    term.print_section("Demo Complete")
    term.print_ok("Session Manager workflow verified")
    term.print_info("")
    term.print_info("What we demonstrated:")
    term.print_info("  1. ✓ Created test identity with values and goals")
    term.print_info("  2. ✓ Created narrative document (core + recent layers)")
    term.print_info("  3. ✓ Started session with personality context")
    term.print_info("  4. ✓ Recorded raw events from lower agent")
    term.print_info("  5. ✓ Captured key moments with first-hand emotional coloring")
    term.print_info("  6. ✓ Finished session → SessionExperience created")
    term.print_info("  7. ✓ Eigenstate saved for next session")
    term.print_info("  8. ✓ Experience stored with recorded_by='session_manager'")
    term.print_info("")
    term.print_info(f"Storage location: {storage_path}")
    term.print_info("All operations completed without external services.")


if __name__ == "__main__":
    main()
