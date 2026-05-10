"""
Agent tools for Atman — functions the agent can call during a session.

These tools allow the agent to:
1. Record key moments during the session
2. Log experiences to the experience store
3. Search similar experiences (read-only)
4. Get identity snapshot (read-only)

All tools receive RunContext[AtmanDeps] as the first parameter,
giving them access to services and session state.
"""

from pydantic_ai import RunContext

from atman.adapters.agent.deps import AtmanDeps
from atman.core.models import KeyMomentInput
from atman.core.models.experience import EmotionalDepth


def record_key_moment(
    ctx: RunContext[AtmanDeps],
    what_happened: str,
    why_it_matters: str,
    emotional_valence: float = 0.0,
    emotional_intensity: float = 0.5,
    depth: str = "meaningful",
) -> str:
    """
    Record a key moment during the current session.

    Args:
        ctx: Run context with AtmanDeps
        what_happened: Description of what happened
        why_it_matters: Why this moment is significant
        emotional_valence: Emotional tone (-1.0 negative to +1.0 positive)
        emotional_intensity: Intensity of emotion (0.0 to 1.0)
        depth: How deeply this touched the agent's identity
            ("surface" | "meaningful" | "profound")

    Returns:
        Confirmation message

    This tool allows the agent to mark significant moments as they happen.
    These moments will be packaged into SessionExperience at session end.
    """
    if not ctx.deps.session_id:
        return "Error: No active session. Cannot record key moment outside of a session."

    # Validate emotional values
    if not -1.0 <= emotional_valence <= 1.0:
        return f"Error: emotional_valence must be between -1.0 and 1.0, got {emotional_valence}"

    if not 0.0 <= emotional_intensity <= 1.0:
        return f"Error: emotional_intensity must be between 0.0 and 1.0, got {emotional_intensity}"

    try:
        emotional_depth = EmotionalDepth(depth)
    except ValueError:
        allowed = ", ".join(d.value for d in EmotionalDepth)
        return f"Error: depth must be one of [{allowed}], got {depth!r}"

    try:
        key_moment = KeyMomentInput(
            what_happened=what_happened,
            why_it_matters=why_it_matters,
            emotional_valence=emotional_valence,
            emotional_intensity=emotional_intensity,
            depth=emotional_depth,
        )
        ctx.deps.session_manager.record_key_moment(ctx.deps.session_id, key_moment)
        return f"Key moment recorded: {what_happened[:50]}..."
    except Exception as e:
        return f"Error recording key moment: {e!s}"


def log_experience(
    ctx: RunContext[AtmanDeps],
    description: str,
    key_insight: str = "",
) -> str:
    """
    Log an experience directly to the experience store.

    Args:
        ctx: Run context with AtmanDeps
        description: Description of the experience
        key_insight: Main insight from this experience

    Returns:
        Confirmation message

    This is typically called automatically at session end,
    but can be used manually for out-of-band experiences.
    """
    # This is a simplified version - normally SessionManager handles this
    # via finish_session which creates a complete SessionExperience
    _ = ctx, key_insight  # currently unused; reserved for future direct-log path
    return (
        "Experience logging is handled automatically at session end. "
        f"Use record_key_moment to capture significant moments: {description[:30]}..."
    )
